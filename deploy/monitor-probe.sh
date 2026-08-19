#!/usr/bin/env bash
# =============================================================================
# DDBJ Validator Web API 死活監視プローブ（読み取り専用）
#
# 事実を集めて JSON 1 行で標準出力に返すだけのスクリプト。判定に必要な期待値は
# 「そのホストの deploy/.env と pyproject.toml」から自分で導くため、呼び出し側
# （居室の s1 等）に版番号や環境名を持たせない＝リリースごとの設定更新が不要。
#
# 【重要】チェックが失敗しても **常に exit 0** で JSON を返す。
#   これにより呼び出し側は
#     ・JSON が返り ok=false          → サービス異常（ホストは生きている）
#     ・ssh/実行そのものが失敗        → ホストまたは経路の障害（UNREACHABLE）
#   を明確に区別できる。使い方の誤り（不正な mode）だけ exit 2。
#
# 実行位置: この環境のクローンの deploy/ に置いて実行する
#   （a011 なら ~/ddbj-validator-api-production/deploy/monitor-probe.sh）。
#   スクリプト自身の位置から repo root と .env を解決するので引数は mode だけ。
#
# 使い方:
#   ./monitor-probe.sh quick      # /health のみ（数十 ms。高頻度用）
#   ./monitor-probe.sh host       # コンテナ・版の3点照合・run 滞留・ログ・容量（HTTP 検証なし）
#   ./monitor-probe.sh deep       # host + /monitoring（実 XML がパイプライン全体を通る。約 3-5 秒）
#   ./monitor-probe.sh contract   # deep + 実 POST /validation → status → result 検証 → run dir 削除
#
# しきい値は環境変数で上書きできる:
#   STUCK_MIN(30) ERR_MAX(5) LEAK_MAX(0) LEAK_MIN_AGE(10) WEBLOG_ERR_MAX(0) DF_MAX(85) CONTRACT_TIMEOUT(120)
#
# 副作用: 実行ごとに heartbeat ファイルを更新する（呼び出し側が生きている証跡。
#         a011 側の dead-man 監視がこの鮮度を見る）。contract mode のみ、自分が
#         投入した合成 run の run dir を削除する（合成データを履歴に残さない）。
# =============================================================================
set -uo pipefail   # -e は付けない（個々のチェック失敗で中断せず、事実を集めきる）

MODE="${1:-}"
case "$MODE" in
  quick|host|deep|contract) ;;
  *) echo "usage: $0 {quick|host|deep|contract}" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"

# .env から値を1つ取り出す（compose.sh / update.sh と同じ方式）
env_val() { sed -n "s/^$1=//p" "$here/.env" 2>/dev/null | tr -d '"' | head -1; }

ENV_NAME="$(env_val DDBJ_ENV)"
VNAME="$(env_val DDBJ_VALIDATOR_NAME)";     VNAME="${VNAME:-ddbj-validator}"
PROJECT="$(env_val DDBJ_COMPOSE_PROJECT)";  PROJECT="${PROJECT:-deploy}"
WNAME="${PROJECT}_web_1"
BIND="$(env_val DDBJ_BIND_HOST)"
PORT="$(env_val DDBJ_WEB_PORT)"
DATA="$(env_val DDBJ_DATA_DIR_HOST)"
BASE="http://${BIND}:${PORT}"

STUCK_MIN="${STUCK_MIN:-30}"
ERR_MAX="${ERR_MAX:-5}"
LEAK_MAX="${LEAK_MAX:-0}"
LEAK_MIN_AGE="${LEAK_MIN_AGE:-10}"   # これより新しい .monitoring-* は実行中とみなして数えない（分）
WEBLOG_ERR_MAX="${WEBLOG_ERR_MAX:-0}"
DF_MAX="${DF_MAX:-85}"
CONTRACT_TIMEOUT="${CONTRACT_TIMEOUT:-120}"

FAILURES=()
fail() { FAILURES+=("$1"); }

# --- 収集する事実（未取得は null 相当の空文字） -------------------------------
PYPROJECT_VERSION=""; IMAGE_TAG=""; REPORT_VERSION=""
VALIDATOR_UP=""; WEB_UP=""; STRAY_VALIDATORS=""; BUSY=""
HEALTH_CODE=""; HEALTH_ENV=""; HEALTH_MS=""
MONITORING_STATUS=""; MONITORING_MS=""; MONITORING_MESSAGE=""
STUCK_RUNS=""; RECENT_ERRORS=""; LEAK_DIRS=""; WEBLOG_ERRORS=""; DF_PCT=""
CONTRACT_UUID=""; CONTRACT_STATUS=""; CONTRACT_VERSION=""; CONTRACT_RULES=""; CONTRACT_CLEANED=""

# 設定そのものの不備（これが欠けると他のチェックが無意味）
[ -n "$ENV_NAME" ] || fail "env_missing:deploy/.env の DDBJ_ENV が読めない"
[ -n "$BIND" ] && [ -n "$PORT" ] || fail "env_missing:DDBJ_BIND_HOST/DDBJ_WEB_PORT が読めない"
[ -n "$DATA" ] || fail "env_missing:DDBJ_DATA_DIR_HOST が読めない"

# --- /health（全 mode 共通） --------------------------------------------------
if [ -n "$BIND" ] && [ -n "$PORT" ]; then
    h="$(curl -s -m 5 -w '\n%{http_code} %{time_total}' "$BASE/health" 2>/dev/null)"
    HEALTH_CODE="$(printf '%s\n' "$h" | tail -1 | awk '{print $1}')"
    HEALTH_MS="$(printf '%s\n' "$h" | tail -1 | awk '{printf "%d", $2*1000}')"
    HEALTH_ENV="$(printf '%s\n' "$h" | head -n -1 | sed -n 's/.*"env"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    [ "$HEALTH_CODE" = "200" ] || fail "health_http:${HEALTH_CODE:-no_response}"
    # env の不一致 = 監視先の取り違え、または別環境の web が動いている
    if [ -n "$HEALTH_ENV" ] && [ -n "$ENV_NAME" ] && [ "$HEALTH_ENV" != "$ENV_NAME" ]; then
        fail "health_env_mismatch:${HEALTH_ENV}!=${ENV_NAME}"
    fi
fi

# --- host mode 以上: コンテナ・版・データの事実 --------------------------------
if [ "$MODE" != "quick" ]; then
    VALIDATOR_UP="$(podman inspect "$VNAME" --format '{{.State.Running}}' 2>/dev/null)"
    WEB_UP="$(podman inspect "$WNAME" --format '{{.State.Running}}' 2>/dev/null)"
    [ "$VALIDATOR_UP" = "true" ] || fail "validator_down:${VNAME}"
    [ "$WEB_UP" = "true" ]       || fail "web_down:${WNAME}"

    # 迷子コンテナ: この環境以外の名前で ddbj-validator イメージが動いていないか。
    # （別クローンの deploy/.env で update.sh を実行すると発生する。2026-08 に実際に発生）
    STRAY_VALIDATORS="$(podman ps --format '{{.Names}} {{.Image}}' 2>/dev/null \
        | grep 'ghcr.io/ddbj/ddbj-validator' | grep -v "^${VNAME} " | wc -l | tr -d ' ')"
    [ "${STRAY_VALIDATORS:-0}" -eq 0 ] || fail "stray_validator:${STRAY_VALIDATORS}"

    # 走行中判定（sleep infinity 以外のプロセスがあれば検証中）。誤検知回避と差し替え可否の判断用。
    if [ "$VALIDATOR_UP" = "true" ]; then
        BUSY="$(podman top "$VNAME" 2>/dev/null | tail -n +2 | grep -vc 'sleep infinity' | tr -d ' ')"
    fi

    # --- 版の3点照合 ---------------------------------------------------------
    # 1) pyproject.toml = 意図した版（ghcr タグの導出元）
    # 2) 稼働 validator の image tag
    # 3) コンテナ内の apps/<app>/__version__ = レポートと result.json に出る版
    # どれか1つでも食い違えば「意図した版で検証していない」= 2026-08 の事故。
    PYPROJECT_VERSION="$(sed -n 's/^version *= *"\(.*\)".*/\1/p' "$repo/pyproject.toml" 2>/dev/null | head -1)"
    img="$(podman inspect "$VNAME" --format '{{.ImageName}}' 2>/dev/null)"
    IMAGE_TAG="${img##*:}"
    if [ "$VALIDATOR_UP" = "true" ]; then
        REPORT_VERSION="$(podman exec "$VNAME" python -c 'from apps.biosample import __version__ as v; print(v)' 2>/dev/null | tr -d '\r')"
    fi
    if [ -n "$PYPROJECT_VERSION" ] && [ -n "$IMAGE_TAG" ] && [ "$PYPROJECT_VERSION" != "$IMAGE_TAG" ]; then
        fail "image_tag_mismatch:image=${IMAGE_TAG},expected=${PYPROJECT_VERSION}"
    fi
    if [ -n "$PYPROJECT_VERSION" ] && [ -n "$REPORT_VERSION" ] && [ "$PYPROJECT_VERSION" != "$REPORT_VERSION" ]; then
        fail "report_version_mismatch:report=${REPORT_VERSION},expected=${PYPROJECT_VERSION}"
    fi

    # --- データディレクトリの事実 --------------------------------------------
    if [ -n "$DATA" ] && [ -d "$DATA" ]; then
        # 滞留: running/accepted のまま放置された run（差し替え事故で死んだジョブ等）
        STUCK_RUNS="$(find "$DATA" -maxdepth 3 -name status.json -mmin "+${STUCK_MIN}" 2>/dev/null \
            | xargs grep -l '"status": "\(running\|accepted\)"' 2>/dev/null | wc -l | tr -d ' ')"
        [ "${STUCK_RUNS:-0}" -eq 0 ] || fail "stuck_runs:${STUCK_RUNS}(>${STUCK_MIN}min)"

        # 直近1時間の error（サービス異常と連携側の入力起因が混在するのでレート監視）
        RECENT_ERRORS="$(find "$DATA" -maxdepth 3 -name status.json -mmin -60 2>/dev/null \
            | xargs grep -l '"status": "error"' 2>/dev/null | wc -l | tr -d ' ')"
        [ "${RECENT_ERRORS:-0}" -le "$ERR_MAX" ] || fail "recent_errors:${RECENT_ERRORS}(>${ERR_MAX}/h)"

        # /monitoring の一時ディレクトリ残骸 = 所有権事故の再発カナリア。
        # 実行中の /monitoring も同じ名前で一時ディレクトリを作る（約 3 秒だけ存在する）ので、
        # 新しいものは数えない。数えると deep と host が同時刻に走ったときに誤報になる
        # （2026-08-19 23:25 に実際に発生）。本物の残骸は削除に失敗して残り続ける。
        LEAK_DIRS="$(find "$DATA" -maxdepth 1 -name '.monitoring-*' -mmin "+${LEAK_MIN_AGE}" 2>/dev/null | wc -l | tr -d ' ')"
        [ "${LEAK_DIRS:-0}" -le "$LEAK_MAX" ] || fail "monitoring_leak:${LEAK_DIRS}(>${LEAK_MAX})"

        # web.log の ERROR（未捕捉例外・run dir 作成失敗などがここに出る）
        if [ -f "$DATA/web.log" ]; then
            since="$(date -d '1 hour ago' '+%Y-%m-%d %H:%M' 2>/dev/null)"
            WEBLOG_ERRORS="$(awk -v d="$since" '$0 >= d && /ERROR/' "$DATA/web.log" 2>/dev/null | wc -l | tr -d ' ')"
            [ "${WEBLOG_ERRORS:-0}" -le "$WEBLOG_ERR_MAX" ] || fail "weblog_errors:${WEBLOG_ERRORS}(>${WEBLOG_ERR_MAX}/h)"
        fi

        DF_PCT="$(df -P "$DATA" 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5}')"
        if [ -n "$DF_PCT" ] && [ "$DF_PCT" -gt "$DF_MAX" ]; then
            fail "disk_usage:${DF_PCT}%(>${DF_MAX}%)"
        fi
    else
        fail "data_dir_missing:${DATA}"
    fi
fi

# --- deep / contract: /monitoring（実 XML がパイプライン全体を通る） ----------
# UUID を採番せず run dir も残さない（web が一時ディレクトリで実行して削除する）。
# 修正版では run dir 用 shard の書込可否チェックも含まれるので、2026-08 の 500 の
# 原因クラス（所有権ずれ）もここで NG になる。
if [ "$MODE" = "deep" ] || [ "$MODE" = "contract" ]; then
    m="$(curl -s -m 180 -w '\n%{time_total}' "$BASE/monitoring" 2>/dev/null)"
    MONITORING_MS="$(printf '%s\n' "$m" | tail -1 | awk '{printf "%d", $1*1000}')"
    body="$(printf '%s\n' "$m" | head -n -1)"
    MONITORING_STATUS="$(printf '%s' "$body" | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    MONITORING_MESSAGE="$(printf '%s' "$body" | sed -n 's/.*"message"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
    [ "$MONITORING_STATUS" = "OK" ] || fail "monitoring:${MONITORING_STATUS:-no_response}"
fi

# --- contract: D-way と同じ API 契約を実際に通す ------------------------------
# multipart アップロード → uuid 採番 → status 遷移 → result 取得までを検証し、
# 最後に自分が作った run dir を削除する（合成データを運用履歴に残さない）。
if [ "$MODE" = "contract" ]; then
    xml="$repo/apps/webapi/resources/monitoring.xml"
    if [ ! -f "$xml" ]; then
        fail "contract:monitoring.xml がない"
    else
        CONTRACT_UUID="$(curl -s -m 30 -F "biosample=@${xml};filename=SSUB000000.xml" "$BASE/validation" 2>/dev/null \
            | sed -n 's/.*"uuid"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
        if [ -z "$CONTRACT_UUID" ]; then
            fail "contract:POST /validation が uuid を返さない"
        else
            deadline=$(( $(date +%s) + CONTRACT_TIMEOUT ))
            while [ "$(date +%s)" -lt "$deadline" ]; do
                CONTRACT_STATUS="$(curl -s -m 10 "$BASE/validation/${CONTRACT_UUID}/status" 2>/dev/null \
                    | sed -n 's/.*"status"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
                case "$CONTRACT_STATUS" in finished|error) break ;; esac
                sleep 2
            done
            [ "$CONTRACT_STATUS" = "finished" ] || fail "contract_status:${CONTRACT_STATUS:-timeout}"

            # result の中身を検証（version が意図した版か／ルールが実際に評価されたか）
            res="$(curl -s -m 15 "$BASE/validation/${CONTRACT_UUID}" 2>/dev/null)"
            CONTRACT_VERSION="$(printf '%s' "$res" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("result",{}).get("version",""))
except Exception: print("")' 2>/dev/null)"
            CONTRACT_RULES="$(printf '%s' "$res" | python3 -c 'import sys,json
try: print(",".join(m["id"] for m in json.load(sys.stdin).get("result",{}).get("messages",[])))
except Exception: print("")' 2>/dev/null)"
            if [ -n "$PYPROJECT_VERSION" ] && [ "$CONTRACT_VERSION" != "$PYPROJECT_VERSION" ]; then
                fail "contract_version:${CONTRACT_VERSION:-none},expected=${PYPROJECT_VERSION}"
            fi
            # 同梱の合成サンプルは必須属性欠落で BS_R0027 が出る想定。出ないならルールが評価されていない。
            case ",${CONTRACT_RULES}," in
                *,BS_R0027,*) ;;
                *) fail "contract_rules:BS_R0027 が出ていない(${CONTRACT_RULES:-none})" ;;
            esac

            # 後片付け: 自分が作った run dir を削除する。入力ファイル名で二重確認してから消す
            # （実データの run を絶対に消さないため）。修正後の run dir は w3const 所有なので rm できる。
            rdir="$DATA/${CONTRACT_UUID:0:2}/${CONTRACT_UUID}"
            if [ -f "$rdir/SSUB000000.xml" ]; then
                rm -rf "$rdir" 2>/dev/null && CONTRACT_CLEANED="true" || CONTRACT_CLEANED="false"
                [ "$CONTRACT_CLEANED" = "true" ] || fail "contract_cleanup:run dir を削除できない(${rdir})"
            else
                CONTRACT_CLEANED="skipped"
            fi
        fi
    fi
fi

# --- heartbeat（呼び出し側が生きている証跡。a011 の dead-man 監視が鮮度を見る）---
hb_dir="${XDG_CACHE_HOME:-$HOME/.cache}/ddbj-validator-monitor"
mkdir -p "$hb_dir" 2>/dev/null && : > "$hb_dir/heartbeat-${ENV_NAME:-unknown}" 2>/dev/null

# --- JSON 出力（1行） --------------------------------------------------------
OK="true"; [ "${#FAILURES[@]}" -eq 0 ] || OK="false"
P_MODE="$MODE" P_ENV="$ENV_NAME" P_HOST="$(hostname)" P_OK="$OK" \
P_CLIENT_IP="${SSH_CLIENT%% *}" \
P_FAILURES="$(printf '%s\n' "${FAILURES[@]+"${FAILURES[@]}"}")" \
P_PYVER="$PYPROJECT_VERSION" P_IMGTAG="$IMAGE_TAG" P_REPVER="$REPORT_VERSION" \
P_VNAME="$VNAME" P_VUP="$VALIDATOR_UP" P_WNAME="$WNAME" P_WUP="$WEB_UP" \
P_STRAY="$STRAY_VALIDATORS" P_BUSY="$BUSY" \
P_HCODE="$HEALTH_CODE" P_HENV="$HEALTH_ENV" P_HMS="$HEALTH_MS" \
P_MSTATUS="$MONITORING_STATUS" P_MMS="$MONITORING_MS" P_MMSG="$MONITORING_MESSAGE" \
P_STUCK="$STUCK_RUNS" P_ERRORS="$RECENT_ERRORS" P_LEAK="$LEAK_DIRS" P_WLERR="$WEBLOG_ERRORS" P_DF="$DF_PCT" \
P_CUUID="$CONTRACT_UUID" P_CSTATUS="$CONTRACT_STATUS" P_CVER="$CONTRACT_VERSION" \
P_CRULES="$CONTRACT_RULES" P_CCLEAN="$CONTRACT_CLEANED" \
python3 -c '
import json, os
from datetime import datetime, timedelta, timezone

def s(k):
    v = os.environ.get(k, "")
    return v if v != "" else None

def n(k):
    v = os.environ.get(k, "")
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

def b(k):
    v = os.environ.get(k, "")
    return {"true": True, "false": False}.get(v)

failures = [l for l in os.environ.get("P_FAILURES", "").splitlines() if l.strip()]
out = {
    "ts": datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
    "host": s("P_HOST"), "env": s("P_ENV"), "mode": s("P_MODE"),
    # sshd が見た接続元 IP。authorized_keys の from= を書くときの実測値
    # （NAT や踏み台を経由すると s1 のローカル IP とは異なるため）。
    "client_ip": s("P_CLIENT_IP"),
    "ok": os.environ.get("P_OK") == "true",
    "failures": failures,
    "version": {"pyproject": s("P_PYVER"), "image_tag": s("P_IMGTAG"), "report": s("P_REPVER")},
    "containers": {"validator": s("P_VNAME"), "validator_up": b("P_VUP"),
                   "web": s("P_WNAME"), "web_up": b("P_WUP"),
                   "stray": n("P_STRAY"), "busy_procs": n("P_BUSY")},
    "health": {"code": n("P_HCODE"), "env": s("P_HENV"), "ms": n("P_HMS")},
    "monitoring": {"status": s("P_MSTATUS"), "ms": n("P_MMS"), "message": s("P_MMSG")},
    "data": {"stuck_runs": n("P_STUCK"), "recent_errors": n("P_ERRORS"),
             "monitoring_leak": n("P_LEAK"), "weblog_errors": n("P_WLERR"), "df_pct": n("P_DF")},
    "contract": {"uuid": s("P_CUUID"), "status": s("P_CSTATUS"), "version": s("P_CVER"),
                 "rules": s("P_CRULES"), "cleaned": s("P_CCLEAN")},
}
print(json.dumps(out, ensure_ascii=False))
'
exit 0
