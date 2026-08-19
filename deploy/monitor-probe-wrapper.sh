#!/usr/bin/env bash
# =============================================================================
# monitor-probe.sh を ssh の forced command 経由で呼ぶためのラッパ。
#
# 目的: 居室の s1 に置く監視用 ssh 鍵で「probe の実行だけ」を許可する。
#   authorized_keys 側で command= を指定すると、クライアントが何を要求しても
#   このラッパしか起動しない。要求内容は SSH_ORIGINAL_COMMAND に入るので、
#   ここで mode 名だけのホワイトリストに落とす（任意コマンド実行を防ぐ）。
#
# ~w3const/.ssh/authorized_keys の書き方（1 行。<...> は環境に合わせる）:
#   command="/home/w3const/ddbj-validator-api-production/deploy/monitor-probe-wrapper.sh",restrict,from="<s1 の IP>" ssh-ed25519 AAAA... ddbj-validator-monitor
#     - command=  … この鍵で実行できるものを固定する
#     - restrict  … port/agent/X11 転送・pty・user-rc を全て無効化（OpenSSH 7.2+）
#     - from=     … 送信元 IP を限定（s1 の IP が固定でない場合は省略可）
#
# s1 側の呼び出し:
#   ssh -i ~/.ssh/ddbj_monitor w3const@a011 quick     # → mode=quick で probe が動く
#
# しきい値の環境変数（STUCK_MIN 等）はクライアントから渡せないよう明示的に unset する。
# ホスト固有の値を変えたい場合はこのラッパ内で export する。
# =============================================================================
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# クライアント由来の値を混ぜない（sshd の AcceptEnv 経由の注入対策）
unset STUCK_MIN ERR_MAX LEAK_MAX WEBLOG_ERR_MAX DF_MAX CONTRACT_TIMEOUT

# ホスト固有にしきい値を変える場合はここで export する（例）:
# export ERR_MAX=10

mode="${SSH_ORIGINAL_COMMAND:-${1:-}}"

case "$mode" in
    quick|host|deep|contract)
        exec "$here/monitor-probe.sh" "$mode"
        ;;
    *)
        # 想定外の要求は実行しない。probe の JSON とは別物だと分かるよう exit 2 で返す
        # （呼び出し側が「ホスト障害」と誤認しないように、理由を stderr にも出す）。
        printf '{"ok": false, "failures": ["wrapper:invalid_command"], "requested": %s}\n' \
            "$(printf '%s' "$mode" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()[:200]))' 2>/dev/null || echo '""')"
        echo "monitor-probe-wrapper: 許可されていない要求です（quick|host|deep|contract のみ）" >&2
        exit 2
        ;;
esac
