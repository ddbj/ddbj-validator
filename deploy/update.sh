#!/usr/bin/env bash
# コンテナ差し替え（更新）ラッパ。手打ちの手順をまとめ、順番間違い・走行中 rm を防ぐ。
#
# やること（対象は引数で選ぶ）:
#   1) git pull --ff-only            … 最新コード＋version を取得
#   2) validator … compose.sh pull validator → rm -f → up -d（版は pyproject に自動追従＝latest v）
#      web       … compose.sh build web       → rm -f → up -d（このリポジトリのコードで rebuild）
#   3) 差し替え後に稼働確認＋/health
#
# 安全策: rm -f の直前に「検証が走っていないか（sleep infinity 以外のプロセス）」を確認し、
#         走行中なら中止する（走行中に落とすとそのジョブが死ぬため）。
#
# 使い方:
#   ./update.sh both        # validator と web の両方（web=rebuild, validator=最新 ghcr）
#   ./update.sh validator   # validator だけ
#   ./update.sh web         # web だけ
#   ./update.sh both --skip-pull   # git pull を省略（既に pull 済みのとき）
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
compose="$here/compose.sh"

mode="${1:-}"
skip_pull=""
for a in "${@:2}"; do
  case "$a" in
    --skip-pull) skip_pull=1 ;;
    *) echo "update.sh: 不明なオプション: $a" >&2; exit 2 ;;
  esac
done

case "$mode" in
  validator|web) ;;
  both|all) mode=both ;;
  *)
    echo "usage: $0 {validator|web|both} [--skip-pull]" >&2
    exit 2
    ;;
esac

DATA_DIR_HOST="$(sed -n 's/^DDBJ_DATA_DIR_HOST=//p' "$here/.env" | tr -d '"' | head -1)"

# ddbj-validator に sleep infinity 以外のプロセスがあれば「検証中」。
validator_busy() {
  podman top ddbj-validator 2>/dev/null | tail -n +2 | grep -vq 'sleep infinity'
}

abort_if_busy() {
  if validator_busy; then
    echo "" >&2
    echo "!! 検証が実行中です（ddbj-validator に sleep infinity 以外のプロセス）。中止します。" >&2
    echo "   完了を待って再実行してください。処理中の uuid:" >&2
    grep -rlE '"status": "(running|accepted)"' "$DATA_DIR_HOST"/*/*/status.json 2>/dev/null >&2 || true
    exit 1
  fi
}

# 1) git pull
if [ -z "$skip_pull" ]; then
  echo "==> git pull --ff-only"
  git -C "$here/.." pull --ff-only
else
  echo "==> git pull はスキップ（--skip-pull）"
fi

ver="$(sed -n 's/^version *= *"\(.*\)".*/\1/p' "$here/../pyproject.toml" | head -1)"
echo "==> 対象 version: ${ver:-（取得失敗）}"
[ -n "$ver" ] || { echo "update.sh: pyproject.toml から version を取得できませんでした。中止します。" >&2; exit 1; }

swap_validator() {
  echo ""
  echo "==> validator を ${ver} に差し替え（ghcr から pull）"
  "$compose" pull validator
  abort_if_busy
  podman rm -f ddbj-validator
  "$compose" up -d validator
}

swap_web() {
  echo ""
  echo "==> web を再ビルドして差し替え"
  "$compose" build web
  abort_if_busy          # web を落とすと処理中の検証（podman exec の親）も死ぬため確認
  podman rm -f deploy_web_1
  "$compose" up -d web
}

case "$mode" in
  validator) swap_validator ;;
  web)       swap_web ;;
  both)      swap_validator; swap_web ;;
esac

# 3) 確認
echo ""
echo "==> 稼働確認"
sleep 1
podman ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" | grep -E 'NAMES|ddbj-validator|deploy_web_1' || true
podman inspect ddbj-validator --format 'validator image={{.ImageName}}' 2>/dev/null || true
podman inspect deploy_web_1   --format 'web       image={{.ImageName}}' 2>/dev/null || true

bind="$(sed -n 's/^DDBJ_BIND_HOST=//p' "$here/.env" | tr -d '"' | head -1)"
port="$(sed -n 's/^DDBJ_WEB_PORT=//p' "$here/.env" | tr -d '"' | head -1)"
if [ -n "$bind" ] && [ -n "$port" ]; then
  echo "==> health http://${bind}:${port}/health"
  curl -s "http://${bind}:${port}/health" || echo "(health 取得失敗)"
  echo ""
fi
echo "==> 完了。動作確認後、不要なら 'podman image prune -f' で dangling を掃除（差し替え直後には実行しない）。"
