#!/usr/bin/env bash
# podman-compose ラッパ。validator の ghcr イメージタグを pyproject.toml の version へ自動追従させる。
#
# 目的: validator（検証エンジン）はリリース済み ghcr イメージを使う。どの版を使うかは固定せず、
#       いま git pull しているコードの版（pyproject.toml の version）にそのまま合わせる。
#       git pull で version が上がれば、次回の起動/入れ替えで対応する ghcr イメージを自動で使う。
#
# 使い方（podman-compose と同じ。--env-file は自動付与）:
#   ./compose.sh up -d              # web + validator 起動
#   ./compose.sh build web          # web だけ再ビルド（validator は build されない）
#   ./compose.sh up -d validator    # validator を（新タグの ghcr イメージで）入れ替え
#   ./compose.sh ps / logs -f web / down など
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# pyproject.toml の `version = "x.y.z"` を取り出して DDBJ_VALIDATOR_TAG にする。
DDBJ_VALIDATOR_TAG="$(sed -n 's/^version *= *"\(.*\)".*/\1/p' "$here/../pyproject.toml" | head -1)"
if [ -z "${DDBJ_VALIDATOR_TAG}" ]; then
  echo "compose.sh: pyproject.toml から version を取得できませんでした。中止します。" >&2
  exit 1
fi
export DDBJ_VALIDATOR_TAG

echo "compose.sh: DDBJ_VALIDATOR_TAG=${DDBJ_VALIDATOR_TAG}（pyproject.toml より自動取得）" >&2
exec podman-compose --env-file "$here/.env" "$@"
