#!/usr/bin/env bash

# コンテナを起動し、'ddbj' サブコマンドと '--local' をデフォルトで付与
docker run --rm -v "$(pwd):/work" ddbj-validator:0.1.0-beta ddbj --local "$@"