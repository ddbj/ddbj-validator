#!/usr/bin/env bash
# =============================================================================
# 監視側（s1）の死活監視 — すぱこん側で動かす dead-man switch
#
# 監視本体は構築チーム居室の s1 で動く。s1 が落ちる／居室の経路が切れると **無音**に
# なるため、こちら側から「最近 probe が呼ばれているか」を見て、途切れたら Slack に出す。
# probe は実行のたびに ~/.cache/ddbj-validator-monitor/heartbeat-<env> を更新するので、
# そのファイルの鮮度＝s1 からの監視が生きている証跡になる。
#
# 注意: /home/w3const は a011 と a012 で共有（lustre）なので heartbeat も状態ファイルも
# 両ホストから同じものが見える。**二重通知を避けるため cron は a011（本番）だけに置く**
# （1 本で production/staging 両方の heartbeat を見る）。
#
# 配置（a011 の crontab）:
#   */10 * * * * /home/w3const/ddbj-validator-api-production/deploy/monitor-heartbeat-check.sh >> ~/log/ddbj-heartbeat.log 2>&1
#
# Slack webhook: ~/.config/ddbj-validator-monitor/webhook（chmod 600）
# しきい値: MAX_AGE_MIN（既定 30 分）。監視間隔（本番 quick=1 分）より十分長くする。
# =============================================================================
set -uo pipefail

CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ddbj-validator-monitor"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/ddbj-validator-monitor"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ddbj-validator-monitor"
mkdir -p "$STATE_DIR"

MAX_AGE_MIN="${MAX_AGE_MIN:-30}"
# 異常時のメンション（記法は monitor-s1.sh と同じ。空ならメンションしない）。
# 監視自体が止まっている状態なので既定は channel 全体。復旧通知には付けない。
MENTION_CRITICAL="${MENTION_CRITICAL-<!channel>}"
ENVS="${ENVS:-production staging}"

WEBHOOK="${WEBHOOK:-}"
if [ -z "$WEBHOOK" ] && [ -f "$CONF_DIR/webhook" ]; then
    WEBHOOK="$(head -1 "$CONF_DIR/webhook")"
fi

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

notify() {
    local text="$1"
    if [ -z "$WEBHOOK" ]; then
        log "[通知なし: webhook 未設定] $text"
        return 0
    fi
    local payload code
    payload="$(TEXT="$text" python3 -c 'import json,os; print(json.dumps({"text": os.environ["TEXT"]}))')"
    code="$(curl -sS -o /dev/null -w '%{http_code}' -m 15 -X POST \
        -H 'Content-type: application/json' --data "$payload" "$WEBHOOK" 2>/dev/null)"
    if [ "$code" = "200" ]; then
        log "[通知] $text"
    else
        log "[通知失敗 HTTP ${code:-?}] $text"
    fi
}

for env_name in $ENVS; do
    hb="$CACHE_DIR/heartbeat-${env_name}"
    state="$STATE_DIR/heartbeat-${env_name}.state"
    prev="none"; [ -f "$state" ] && prev="$(cat "$state")"

    if [ ! -f "$hb" ]; then
        age="-1"; status="MISSING"
    else
        age=$(( ( $(date +%s) - $(stat -c %Y "$hb") ) / 60 ))
        if [ "$age" -gt "$MAX_AGE_MIN" ]; then status="STALE"; else status="OK"; fi
    fi

    log "heartbeat-${env_name}: ${status}（${age} 分前 / しきい値 ${MAX_AGE_MIN} 分）"

    case "$status" in
        OK)
            if [ "$prev" != "none" ] && [ "$prev" != "OK" ]; then
                notify ":large_green_circle: 復旧: ${env_name} の外部監視（s1）からの probe が再開しました（${age} 分前）"
            fi
            echo "OK" > "$state"
            ;;
        STALE)
            if [ "$prev" != "STALE" ]; then
                notify "${MENTION_CRITICAL:+${MENTION_CRITICAL} }:rotating_light: 外部監視が停止している可能性: ${env_name} の probe が ${age} 分間ありません（しきい値 ${MAX_AGE_MIN} 分）。s1 または居室の経路を確認してください。※この通知はすぱこん側（a011）から出しています"
            fi
            echo "STALE" > "$state"
            ;;
        MISSING)
            if [ "$prev" != "MISSING" ]; then
                notify "${MENTION_CRITICAL:+${MENTION_CRITICAL} }:warning: ${env_name} の heartbeat がまだありません（${hb}）。s1 側の cron 設定を確認してください"
            fi
            echo "MISSING" > "$state"
            ;;
    esac
done

exit 0
