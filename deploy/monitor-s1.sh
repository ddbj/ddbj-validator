#!/usr/bin/env bash
# =============================================================================
# DDBJ Validator Web API 死活監視（**s1 に置いて cron から実行する側**）
#
# すぱこん（a011/a012）の monitor-probe.sh を ssh 経由で呼び、結果を判定して
# 状態が変化したときだけ Slack に通知する。すぱこんが停電・クラッシュで落ちても
# 監視ごと道連れにならないよう、監視は構築チーム居室の s1 で動かす前提。
#
# 配置（s1 の ~/monitor に置く運用）:
#   scp w3const@a012:ddbj-validator-api-staging/deploy/monitor-s1.sh ~/monitor/
#   chmod +x ~/monitor/monitor-s1.sh
#   mkdir -p ~/.config/ddbj-validator-monitor
#   printf '%s\n' 'https://hooks.slack.com/services/XXX/YYY/ZZZ' > ~/.config/ddbj-validator-monitor/webhook
#   chmod 600 ~/.config/ddbj-validator-monitor/webhook
#
# 使い方:
#   monitor-s1.sh quick|host|deep|contract   # 監視 1 巡
#   monitor-s1.sh summary                    # 現在の状態を 1 通まとめて通知（日次の生存確認用）
#
# cron 例（crontab では ~ を使わず絶対パスで書く。本番は高頻度・ステージングは控えめ。
# 重いモードは分をずらす。mode ごとにロックを取るので重複起動は自動でスキップされる）:
#   MAILTO=""
#   */1          * * * * TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh quick    >> /home/ykodama/monitor/monitor.log 2>&1
#   */5          * * * * TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh deep     >> /home/ykodama/monitor/monitor.log 2>&1
#   5,15,25,35,45,55 * * * * TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh host >> /home/ykodama/monitor/monitor.log 2>&1
#   17 */6       * * * TARGETS="a011-monitor:production" /home/ykodama/monitor/monitor-s1.sh contract    >> /home/ykodama/monitor/monitor.log 2>&1
#   */10         * * * * TARGETS="a012-monitor:staging"   /home/ykodama/monitor/monitor-s1.sh quick     >> /home/ykodama/monitor/monitor.log 2>&1
#   */30         * * * * TARGETS="a012-monitor:staging"   /home/ykodama/monitor/monitor-s1.sh deep      >> /home/ykodama/monitor/monitor.log 2>&1
#   23 3         * * *   TARGETS="a012-monitor:staging"   /home/ykodama/monitor/monitor-s1.sh contract  >> /home/ykodama/monitor/monitor.log 2>&1
#   30 7         * * *   TARGETS="a011-monitor:production a012-monitor:staging" /home/ykodama/monitor/monitor-s1.sh summary >> /home/ykodama/monitor/monitor.log 2>&1
#   5 0 1        * *     : > /home/ykodama/monitor/monitor.log      # 毎月 1 日にログを切り詰め
#
# 判定は 4 状態。probe は「チェックが失敗しても JSON を返して exit 0」なので、
# サービス異常とホスト/経路障害を区別できる:
#   OK          … JSON の ok=true
#   NG          … JSON の ok=false（failures[] に理由）＝ホストは生存、サービス異常
#   UNREACHABLE … ssh が失敗／JSON が返らない ＝ホストまたは経路の障害
#   CONFIG      … probe ラッパが要求を拒否（exit 2）＝監視設定の誤り
#
# 通知は**状態が変わったときだけ**。連続 N 回同じ異常が続いて初めて発報し（単発の
# ネットワーク揺らぎや DB メンテで鳴らさない）、復旧時にも 1 通出す。
# 全対象が同時に UNREACHABLE の場合は 1 通にまとめる（サイト障害を N 件に分裂させない）。
# =============================================================================
set -uo pipefail

MODE="${1:-}"
case "$MODE" in
  quick|host|deep|contract|summary) ;;
  *) echo "usage: $0 {quick|host|deep|contract|summary}" >&2; exit 2 ;;
esac

CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ddbj-validator-monitor"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ddbj-validator-monitor"
mkdir -p "$STATE_DIR"
[ -f "$CONF_DIR/config" ] && . "$CONF_DIR/config"      # 任意。下記変数を上書きできる

# 監視対象: "<ssh の別名>:<期待する env>" を空白区切りで
TARGETS="${TARGETS:-a011-monitor:production a012-monitor:staging}"

# 連続何回で発報するか（quick は高頻度なので多め、重いモードは少なめ）
THRESHOLD_QUICK="${THRESHOLD_QUICK:-3}"
THRESHOLD_OTHER="${THRESHOLD_OTHER:-2}"

# ssh 全体のタイムアウト（gateway 2 段のため probe の所要時間 + 余裕）
case "$MODE" in
  quick)    SSH_TIMEOUT="${SSH_TIMEOUT:-30}" ;;
  host)     SSH_TIMEOUT="${SSH_TIMEOUT:-60}" ;;
  deep)     SSH_TIMEOUT="${SSH_TIMEOUT:-120}" ;;
  contract) SSH_TIMEOUT="${SSH_TIMEOUT:-240}" ;;
  *)        SSH_TIMEOUT="${SSH_TIMEOUT:-30}" ;;
esac

WEBHOOK="${WEBHOOK:-}"
if [ -z "$WEBHOOK" ] && [ -f "$CONF_DIR/webhook" ]; then
    WEBHOOK="$(head -1 "$CONF_DIR/webhook")"
fi

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# --- 多重起動の防止 -----------------------------------------------------------
# quick は 1 分間隔で回すため、gateway が詰まって ssh が待たされると次の実行が重なって
# プロセスが積み上がる。mode ごとにロックを取り、前回が走っている間はスキップする
# （cron 側に flock を書かなくても安全。summary は軽いので対象外）。
if [ "$MODE" != "summary" ] && command -v flock >/dev/null 2>&1; then
    exec 9>"$STATE_DIR/.lock.$MODE" || true
    if ! flock -n 9; then
        log "前回の ${MODE} がまだ実行中のためスキップします"
        exit 0
    fi
fi

# Slack へ 1 通送る（webhook 未設定ならログだけ）
notify() {
    local text="$1"
    if [ -z "$WEBHOOK" ]; then
        log "[通知なし: webhook 未設定] $text"
        return 0
    fi
    local payload
    payload="$(TEXT="$text" python3 -c 'import json,os; print(json.dumps({"text": os.environ["TEXT"]}))')"
    local code
    code="$(curl -sS -o /dev/null -w '%{http_code}' -m 15 -X POST \
        -H 'Content-type: application/json' --data "$payload" "$WEBHOOK" 2>/dev/null)"
    if [ "$code" = "200" ]; then
        log "[通知] $text"
    else
        log "[通知失敗 HTTP ${code:-?}] $text"
    fi
}

# --- summary: 現在の状態を 1 通まとめて出す（監視が生きている証跡） -------------
if [ "$MODE" = "summary" ]; then
    lines=""
    for t in $TARGETS; do
        alias_name="${t%%:*}"
        for m in quick host deep contract; do
            f="$STATE_DIR/${alias_name}.${m}"
            [ -f "$f" ] || continue
            read -r st cnt _ < "$f"
            lines="${lines}
  ${alias_name} ${m}: ${st} (連続 ${cnt})"
        done
    done
    [ -n "$lines" ] || lines="
  （まだ状態がありません）"
    notify ":white_check_mark: DDBJ Validator 監視は稼働中（s1）$lines"
    exit 0
fi

# --- 1 対象を検査して状態を返す ------------------------------------------------
declare -A RESULT_STATUS RESULT_DETAIL
check_target() {
    local alias_name="$1" want_env="$2"
    local out rc status detail

    out="$(timeout "$SSH_TIMEOUT" ssh -o BatchMode=yes -o ConnectTimeout=10 \
            "$alias_name" "$MODE" 2>/dev/null)"
    rc=$?

    if [ "$rc" -eq 2 ]; then
        # ラッパが要求を拒否 = 監視側の設定ミス（mode 名の誤り等）
        status="CONFIG"; detail="probe ラッパが要求を拒否（exit 2）"
    elif [ "$rc" -ne 0 ] || [ -z "$out" ]; then
        status="UNREACHABLE"; detail="ssh 失敗（exit ${rc}${out:+ / 出力あり}）"
    else
        # JSON を解釈。ok と failures、env の一致を見る
        detail="$(printf '%s' "$out" | WANT_ENV="$want_env" python3 -c '
import json, os, sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print("PARSE\tJSON として解釈できない: %s" % e); raise SystemExit
want = os.environ.get("WANT_ENV", "")
env = d.get("env")
fails = list(d.get("failures") or [])
if want and env != want:
    fails.append("env_unexpected:%s!=%s" % (env, want))
extra = []
mon = (d.get("monitoring") or {}).get("ms")
if mon: extra.append("monitoring=%sms" % mon)
c = d.get("contract") or {}
if c.get("uuid"): extra.append("contract=%s/%s" % (c.get("status"), c.get("version")))
v = d.get("version") or {}
if v.get("pyproject"): extra.append("version=%s" % v.get("pyproject"))
tail = (" [" + ", ".join(extra) + "]") if extra else ""
if fails:
    print("NG\t%s%s" % ("; ".join(fails), tail))
else:
    print("OK\t%s%s" % ((d.get("health") or {}).get("ms","?"), tail))
' 2>/dev/null)"
        case "$detail" in
            OK*)     status="OK";     detail="${detail#OK	}" ;;
            NG*)     status="NG";     detail="${detail#NG	}" ;;
            PARSE*)  status="UNREACHABLE"; detail="${detail#PARSE	}" ;;
            *)       status="UNREACHABLE"; detail="probe の出力を解釈できない" ;;
        esac
    fi
    RESULT_STATUS["$alias_name"]="$status"
    RESULT_DETAIL["$alias_name"]="$detail"
}

# --- 状態遷移の管理と通知 ------------------------------------------------------
threshold() { [ "$MODE" = "quick" ] && echo "$THRESHOLD_QUICK" || echo "$THRESHOLD_OTHER"; }

PENDING_ALERTS=()          # 今回発報すべきメッセージ
RECOVERED=()               # 復旧メッセージ

for t in $TARGETS; do
    alias_name="${t%%:*}"; want_env="${t##*:}"
    check_target "$alias_name" "$want_env"
    st="${RESULT_STATUS[$alias_name]}"; dt="${RESULT_DETAIL[$alias_name]}"
    log "${alias_name} ${MODE}: ${st} — ${dt}"

    f="$STATE_DIR/${alias_name}.${MODE}"
    prev_st=""; prev_cnt=0; notified=""
    [ -f "$f" ] && read -r prev_st prev_cnt notified < "$f"
    notified="${notified:-none}"

    if [ "$st" = "$prev_st" ]; then
        cnt=$((prev_cnt + 1))
    else
        cnt=1
    fi

    if [ "$st" = "OK" ]; then
        # 発報済みの異常から復旧したときだけ 1 通
        if [ "$notified" != "none" ] && [ "$notified" != "OK" ]; then
            RECOVERED+=(":large_green_circle: 復旧: ${want_env} (${alias_name}) ${MODE} — ${dt}")
            notified="OK"
        fi
    else
        # しきい値に達した瞬間、かつ同じ状態で未発報のときだけ 1 通
        if [ "$cnt" -ge "$(threshold)" ] && [ "$notified" != "$st" ]; then
            PENDING_ALERTS+=("${st}|${want_env}|${alias_name}|${dt}")
            notified="$st"
        fi
    fi
    printf '%s %s %s\n' "$st" "$cnt" "$notified" > "$f"
done

# 全対象が同時に UNREACHABLE なら 1 通にまとめる（サイト/経路障害を分裂させない）
if [ "${#PENDING_ALERTS[@]}" -ge 2 ]; then
    all_unreach=1
    for a in "${PENDING_ALERTS[@]}"; do
        [ "${a%%|*}" = "UNREACHABLE" ] || all_unreach=0
    done
    if [ "$all_unreach" -eq 1 ]; then
        names=""
        for a in "${PENDING_ALERTS[@]}"; do
            IFS='|' read -r _ e n _ <<< "$a"
            names="${names}${names:+, }${e}(${n})"
        done
        notify ":rotating_light: DDBJ Validator: ${names} が同時に到達不能（${MODE}）— 経路またはサイト全体の障害の可能性。s1 から ssh が通りません"
        PENDING_ALERTS=()
    fi
fi

for a in "${PENDING_ALERTS[@]+"${PENDING_ALERTS[@]}"}"; do
    IFS='|' read -r st e n dt <<< "$a"
    case "$st" in
        NG)          icon=":red_circle:";  head="サービス異常" ;;
        UNREACHABLE) icon=":rotating_light:"; head="到達不能" ;;
        CONFIG)      icon=":warning:";     head="監視設定の誤り" ;;
        *)           icon=":warning:";     head="$st" ;;
    esac
    notify "${icon} DDBJ Validator ${head}: ${e} (${n}) ${MODE} — ${dt}"
done

for r in "${RECOVERED[@]+"${RECOVERED[@]}"}"; do
    notify "$r"
done

exit 0
