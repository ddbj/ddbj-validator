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

# .env から値を1つ取り出す（値の "" は除去）。
env_val() { sed -n "s/^$1=//p" "$here/.env" | tr -d '"' | head -1; }

DATA_DIR_HOST="$(env_val DDBJ_DATA_DIR_HOST)"

# コンテナ名は環境ごとに .env で決まる（compose.sh と同じ既定値にそろえる）。
PROJECT="$(env_val DDBJ_COMPOSE_PROJECT)"; PROJECT="${PROJECT:-deploy}"
VALIDATOR="$(env_val DDBJ_VALIDATOR_NAME)"; VALIDATOR="${VALIDATOR:-ddbj-validator}"
WEB="${PROJECT}_web_1"          # podman-compose は <project>_<service>_<n> で命名する

# --- 実行中のクローンとホストの対応チェック -----------------------------------
# /home/w3const は a011 と a012 で共有（lustre）なので、両ホストから両方のクローン
# （~/ddbj-validator-api-production と ~/ddbj-validator-api-staging）が見える。
# 別環境のクローンで実行すると、そのホストに「別環境名の validator コンテナ」が新しく
# 作られ、web が実際に exec する本来の名前のコンテナは旧版のまま残る。つまり
# 「版を上げたつもりで上がっていない」状態になる（2026-08 に実際に発生）。
# compose.sh のガードは 1 つの .env 内の整合しか見ないためこれを検知できない。ここで止める。
ENV_NAME="$(env_val DDBJ_ENV)"
case "$(hostname -s)" in
    a011) EXPECTED_ENV="production" ;;
    a012) EXPECTED_ENV="staging" ;;
    *)    EXPECTED_ENV="" ;;        # 未知のホストでは判定しない（警告のみ）
esac
if [ -z "$ENV_NAME" ]; then
    echo "!! deploy/.env の DDBJ_ENV が読めません。環境の取り違えを検査できません。" >&2
elif [ -z "$EXPECTED_ENV" ]; then
    echo "[WARN] このホスト（$(hostname -s)）に対応する環境が未定義です。DDBJ_ENV=${ENV_NAME} として続行します。" >&2
elif [ "$ENV_NAME" != "$EXPECTED_ENV" ]; then
    echo "" >&2
    echo "!! 環境の取り違えです。中止します。" >&2
    echo "   ホスト $(hostname -s) は ${EXPECTED_ENV} 環境ですが、いま実行しているクローンは" >&2
    echo "   DDBJ_ENV=${ENV_NAME}（$(cd "$here/.." && pwd)）です。" >&2
    echo "   このまま実行すると ${ENV_NAME} 名のコンテナがこのホストに作られ、${EXPECTED_ENV} の" >&2
    echo "   validator は旧版のまま残ります（版が上がったつもりで上がらない）。" >&2
    echo "" >&2
    echo "   正しい実行場所: ~/ddbj-validator-api-${EXPECTED_ENV}/deploy" >&2
    echo "" >&2
    exit 1
fi

# validator に sleep infinity 以外のプロセスがあれば「検証中」。
validator_busy() {
  podman top "$VALIDATOR" 2>/dev/null | tail -n +2 | grep -vq 'sleep infinity'
}

abort_if_busy() {
  if validator_busy; then
    echo "" >&2
    echo "!! 検証が実行中です（${VALIDATOR} に sleep infinity 以外のプロセス）。中止します。" >&2
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
  podman rm -f "$VALIDATOR"
  "$compose" up -d validator
}

swap_web() {
  echo ""
  echo "==> web を再ビルドして差し替え"
  "$compose" build web
  abort_if_busy          # web を落とすと処理中の検証（podman exec の親）も死ぬため確認
  podman rm -f "$WEB"
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
podman ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" | grep -E "NAMES|${VALIDATOR}|${WEB}" || true
podman inspect "$VALIDATOR" --format 'validator image={{.ImageName}}' 2>/dev/null || true
podman inspect "$WEB"       --format 'web       image={{.ImageName}}' 2>/dev/null || true

# 別環境名の validator が動いていれば知らせる（過去の誤実行で作られた残骸の可能性）。
# STRAY_MIN_AGE 分より新しいものは無視する。release.sh のテストが `podman run --rm`
# （--name 無し＝ランダム名）で使い捨ての validator を秒単位に作るため、これを拾うと
# リリース中は毎回この警告が出る（monitor-probe.sh の stray 判定と同じ理由）。
STRAY_MIN_AGE="${STRAY_MIN_AGE:-5}"
stray="$(podman ps --format '{{.Names}} {{.Image}} {{.StartedAt}}' 2>/dev/null \
    | grep 'ghcr.io/ddbj/ddbj-validator' | grep -v "^${VALIDATOR} " \
    | awk -v now="$(date +%s)" -v min="$STRAY_MIN_AGE" '$3+0 > 0 && (now - $3) >= min*60 {$3=""; print}' || true)"
if [ -n "$stray" ]; then
    echo "" >&2
    echo "[WARN] このホストで別名の validator コンテナが動いています（誤実行の残骸の可能性）:" >&2
    printf '       %s\n' "$stray" >&2
    echo "       web が exec するのは ${VALIDATOR} です。不要なら podman rm -f <名前> で削除してください。" >&2
fi

bind="$(env_val DDBJ_BIND_HOST)"
port="$(env_val DDBJ_WEB_PORT)"
if [ -n "$bind" ] && [ -n "$port" ]; then
  echo "==> health http://${bind}:${port}/health"
  curl -s "http://${bind}:${port}/health" || echo "(health 取得失敗)"
  echo ""
fi
echo "==> 完了。動作確認後、不要なら 'podman image prune -f' で dangling を掃除（差し替え直後には実行しない）。"
