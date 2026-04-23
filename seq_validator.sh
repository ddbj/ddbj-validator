#!/bin/bash

# bsi-validator の DDBJ モードを呼び出す後方互換ラッパー
# readlink -f を使って、シンボリックリンク経由でも実体のディレクトリを正確に取得する
SCRIPT_PATH=$(readlink -f "${BASH_SOURCE[0]}")
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")

# 暗黙的に "ddbj" サブコマンドを差し込んで実行する
"$SCRIPT_DIR/bsi-validator.sh" ddbj "$@"