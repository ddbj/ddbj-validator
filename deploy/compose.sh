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

# .env から値を1つ取り出す（値の "" は除去）。
env_val() { sed -n "s/^$1=//p" "$here/.env" | tr -d '"' | head -1; }

# 環境ごとの compose project 名。コンテナ名は <project>_<service>_1 になるので、これで
# staging/production を分離する。未設定なら podman-compose 既定（=ディレクトリ名 deploy）。
project="$(env_val DDBJ_COMPOSE_PROJECT)"
project="${project:-deploy}"

# DDBJ_VALIDATOR_NAME（compose の container_name）と DDBJ_VALIDATOR_CMD の
# `podman exec <name>` がずれると web が存在しないコンテナを exec して全検証が失敗する。
vname="$(env_val DDBJ_VALIDATOR_NAME)"
vcmd="$(env_val DDBJ_VALIDATOR_CMD)"
cmd_name="$(printf '%s\n' "$vcmd" | awk '{for(i=1;i<NF;i++) if($i=="exec") {print $(i+1); exit}}')"
if [ -n "$cmd_name" ] && [ "$cmd_name" != "${vname:-ddbj-validator}" ]; then
  echo "compose.sh: !! .env 不整合: DDBJ_VALIDATOR_NAME=${vname:-(未設定→ddbj-validator)} だが" >&2
  echo "            DDBJ_VALIDATOR_CMD は '${cmd_name}' を exec しようとしています。中止します。" >&2
  exit 1
fi

echo "compose.sh: DDBJ_VALIDATOR_TAG=${DDBJ_VALIDATOR_TAG}（pyproject.toml より自動取得）" >&2
echo "compose.sh: compose project=${project} / validator=${vname:-ddbj-validator}" >&2
exec podman-compose -p "$project" --env-file "$here/.env" "$@"
