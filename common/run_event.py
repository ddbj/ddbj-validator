"""検証イベント（run）の管理: UUID 採番・run ディレクトリ・status.json・per-run ログ。

Web API 専用の下回り（通常の CLW 実行では使わない）。現行 ruby validator の
ファイルベースのイベント機構（data_dir/<uuid[:2]>/<uuid>/ に status.json / result.json）を
踏襲しつつ、UUID は **ダッシュ無し 32 桁 hex**（`uuid4().hex`）にして現行（8-4-4-4-12）と区別する。
"""
import contextlib
import json
import logging
import os
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

# status.json の status 値
ACCEPTED = "accepted"
RUNNING = "running"
FINISHED = "finished"
ERROR = "error"

_STATUS_NAME = "status.json"
_RESULT_NAME = "result.json"
_LOG_NAME = "validation.log"


def new_uuid():
    """ダッシュ無し 32 桁 hex の UUID（現行 ruby の 8-4-4-4-12 と区別するため）。"""
    return _uuid.uuid4().hex


def is_python_uuid(value):
    """本ツール発行（32hex・ダッシュ無し）かどうか。"""
    return isinstance(value, str) and len(value) == 32 and all(c in "0123456789abcdef" for c in value)


def run_dir(data_dir, uuid):
    """DATA_DIR/<uuid[:2]>/<uuid>/。先頭 2 文字でシャーディングして 1 階層の肥大を防ぐ。"""
    return Path(data_dir) / uuid[:2] / uuid


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_status(rdir, **fields):
    """status.json をアトミックに書き換える（temp + os.replace）。web と worker の同時アクセス対策。"""
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)
    path = rdir / _STATUS_NAME
    tmp = rdir / f"{_STATUS_NAME}.{os.getpid()}.{new_uuid()[:8]}.tmp"
    tmp.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_status(rdir):
    path = Path(rdir) / _STATUS_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def result_path(rdir):
    return Path(rdir) / _RESULT_NAME


def read_result(rdir):
    path = result_path(rdir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def timestamp():
    return _now_iso()


@contextlib.contextmanager
def run_logger(rdir, level=logging.INFO):
    """run dir 直下の validation.log へ、その run の実行中だけログを集約する。

    ルートロガーに一時的に FileHandler を付け、終了時に外す。
    既存の各モジュール（getLogger(__name__)）の出力がこの UUID のログに集まる。
    """
    rdir = Path(rdir)
    rdir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(rdir / _LOG_NAME, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    prev_level = root.level
    if root.level > level:
        root.setLevel(level)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        handler.close()
        root.setLevel(prev_level)
