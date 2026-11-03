#!/bin/bash

# スクリプトのあるディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# キュレータ用: ddbj の --clean（前回の fixed/ aa/ reports/ を消してから実行）を既定にする。
# 名前を変えた登録ファイルの前回分が fixed/ に残り、load-nsub で二重登録になるのを防ぐ。--no-clean で打ち消せる
export DDBJ_VALIDATOR_CLEAN=1

# pipの生成物に頼らず、仮想環境のpythonで直接main.pyを叩く
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"