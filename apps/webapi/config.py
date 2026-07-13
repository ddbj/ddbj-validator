"""Web API の設定（環境変数から解決）。a011=本番 / a012=ステージングは env で切替。"""
import os
import shlex
import sys
from pathlib import Path

# 検証イベントの保存先ルート（web ⇔ validator コンテナで共有ボリューム）
DATA_DIR = os.environ.get("DDBJ_DATA_DIR", "/data")

# 実行環境ラベル（production / staging）。ログ・レスポンスの識別用
DDBJ_ENV = os.environ.get("DDBJ_ENV", "development")

# validator の起動コマンド接頭辞。
# 別コンテナ運用では `podman exec <validator> python /app/main.py` 等を設定する。
# 既定は同一環境での `python <repo>/main.py`（開発・単一コンテナ用）。
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CMD = f"{sys.executable} {_REPO_ROOT / 'main.py'}"
VALIDATOR_CMD = shlex.split(os.environ.get("DDBJ_VALIDATOR_CMD", _DEFAULT_CMD))

# 検証モード → CLI フラグ。web 既定は内部 DB（curator / D-way 連携）。
MODE_FLAG = {"local": "-l", "ncbi": "-n", "db": "-d"}
DEFAULT_MODE = os.environ.get("DDBJ_DEFAULT_MODE", "db")

# サブプロセスのタイムアウト秒
RUN_TIMEOUT = int(os.environ.get("DDBJ_RUN_TIMEOUT", "3600"))
