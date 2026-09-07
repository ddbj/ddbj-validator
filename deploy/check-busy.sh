#!/usr/bin/env bash
# 検証が走っていないかの確認（読み取り専用）。update.sh / podman rm -f の前に使う。
#
# update.sh の abort_if_busy と同じ判定を単体で実行できるようにしたもの。
# 手動で差し替えるときや、D-way から「終わらない」と言われたときの一次切り分け用。
#
# 2 系統を見る（片方だけでは足りない）:
#   A. podman top <validator> … いま CPU が回っているか。sleep infinity だけなら IDLE。
#   B. status.json の grep     … web が受け付けた記録。走行中に落ちたジョブは running のまま
#                                残るので「滞留」もここで見える（A は IDLE なのに B が running）。
#
# 使い方:
#   ./check-busy.sh          # 人間向けに表示
#   ./check-busy.sh -q       # 表示なし（終了コードだけ。スクリプト用）
#   ./check-busy.sh && ./update.sh both    # IDLE のときだけ差し替える
#
# 終了コード: 0=IDLE（差し替え可） / 1=RUNNING（走行中。待つ） / 2=引数エラー
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

quiet=""
case "${1:-}" in
  "")   ;;
  -q|--quiet) quiet=1 ;;
  *)    echo "usage: $0 [-q]" >&2; exit 2 ;;
esac

say() { [ -n "$quiet" ] || printf '%s\n' "$*"; }

# .env から値を1つ取り出す（値の "" は除去）。compose.sh / update.sh と同じ。
env_val() { sed -n "s/^$1=//p" "$here/.env" | tr -d '"' | head -1; }

ENV_NAME="$(env_val DDBJ_ENV)"
DATA_DIR_HOST="$(env_val DDBJ_DATA_DIR_HOST)"
VALIDATOR="$(env_val DDBJ_VALIDATOR_NAME)"; VALIDATOR="${VALIDATOR:-ddbj-validator}"

say "== ${ENV_NAME:-?} / ${VALIDATOR} =="

# --- A. podman top -----------------------------------------------------------
# validator は entrypoint: sleep infinity で常駐し、検証は web からの podman exec で
# その都度起動される。したがって sleep infinity 以外のプロセスがあれば「検証中」。
busy=""
if ! top_out="$(podman top "$VALIDATOR" 2>/dev/null)"; then
  # コンテナが無い/停止中。走行中の検証は無いので差し替えは可（IDLE 扱い）。
  say "[WARN] validator コンテナ ${VALIDATOR} が起動していません（走行中の検証は無し）。"
else
  procs="$(printf '%s\n' "$top_out" | tail -n +2 | grep -v 'sleep infinity' || true)"
  if [ -n "$procs" ]; then
    busy=1
    say "podman top: RUNNING（sleep infinity 以外のプロセスあり）"
    [ -n "$quiet" ] || printf '  %s\n' "$procs"
  else
    say "podman top: IDLE（sleep infinity のみ）"
  fi
fi

# --- B. status.json ----------------------------------------------------------
# run dir は $DATA/<uuid 先頭2文字>/<uuid>/status.json（shard 構造）。
# glob を */*/ にしておくと monitor-probe.sh の一時 dir（$DATA/.monitoring-XXXX/ は
# 1 階層かつ隠しなので `*` に当たらない）を自然に除外できる。find -maxdepth では拾ってしまう。
# grep は -E 必須（BRE だと (running|accepted) の | がリテラルになり何も当たらない）。
runs=""
if [ -n "$DATA_DIR_HOST" ]; then
  runs="$(grep -rlE '"status": "(running|accepted)"' "$DATA_DIR_HOST"/*/*/status.json 2>/dev/null || true)"
else
  say "[WARN] .env の DDBJ_DATA_DIR_HOST が読めません。status.json は確認できません。"
fi

if [ -n "$runs" ]; then
  n="$(printf '%s\n' "$runs" | wc -l | tr -d ' ')"
  say "status.json: running/accepted が ${n} 件"
  if [ -z "$quiet" ]; then
    printf '%s\n' "$runs" | while read -r f; do
      printf '  %s\n' "$(tr -d '\n' < "$f")"
    done
    # 30 分以上動いていない running/accepted は差し替え事故等で死んだジョブの残骸。
    # これは待っても終わらないので、待つべきかの判断のために区別して出す。
    # find は該当すればパスを出し、しなければ何も出さずに 0 を返す（テスト＋&& だと
    # 最後の反復が 1 を返し、set -e で代入ごと落ちる）。
    stale="$(printf '%s\n' "$runs" | while read -r f; do
               find "$f" -mmin +30 2>/dev/null
             done)"
    if [ -n "$stale" ]; then
      echo "  [WARN] うち 30 分以上更新が無いもの（死んだジョブの残骸の可能性。待っても終わりません）:"
      printf '%s\n' "$stale" | while read -r f; do
        printf '         %s\n' "$(basename "$(dirname "$f")")"
      done
    fi
  fi
else
  say "status.json: running/accepted なし"
fi

# --- 判定 --------------------------------------------------------------------
# 差し替えの可否は A（実プロセス）で決める。B だけが running のケースは残骸なので止めない
# （止めると残骸が消えるまで永久に差し替えられなくなる）。ただし上で残骸として表示済み。
if [ -n "$busy" ]; then
  say ""
  say "=> RUNNING: 完了を待ってください（走行中に落とすとそのジョブが死にます）。"
  exit 1
fi
say ""
say "=> IDLE: 差し替え可（./update.sh both など）。"
exit 0
