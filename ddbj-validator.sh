#!/bin/bash

# スクリプトのあるディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# pipの生成物に頼らず、仮想環境のpythonで直接main.pyを叩く
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py" "$@"