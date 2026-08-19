"""検証イベント（run）の管理: UUID 採番・run ディレクトリ・status.json・per-run ログ。

Web API 専用の下回り（通常の CLW 実行では使わない）。現行 ruby validator の
ファイルベースのイベント機構（data_dir/<uuid[:2]>/<uuid>/ に status.json / result.json）を踏襲する。
UUID は標準の **ハイフンあり uuid4（8-4-4-4-12）**（現行 ruby と同形式）。
"""
import contextlib
import json
import logging
import os
import shutil
import time
import uuid as _uuid
from datetime import datetime, timedelta, timezone

# 日本標準時（tzdata 非依存の固定オフセット）。status.json / result.json / validation.log の
# 時刻表示に用いる。コンテナの TZ が UTC でも JST(+09:00) で出す。
_JST = timezone(timedelta(hours=9))
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
    """標準のハイフンあり uuid4（8-4-4-4-12）。現行 ruby と同形式。"""
    return str(_uuid.uuid4())


def is_valid_uuid(value):
    """標準 uuid 文字列（ハイフンあり）かどうか。"""
    try:
        return isinstance(value, str) and str(_uuid.UUID(value)) == value.lower()
    except Exception:
        return False


def run_dir(data_dir, uuid):
    """DATA_DIR/<uuid[:2]>/<uuid>/。先頭 2 文字でシャーディングして 1 階層の肥大を防ぐ。"""
    return Path(data_dir) / uuid[:2] / uuid


def _now_iso():
    return datetime.now(_JST).isoformat(timespec="seconds")


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


def publish_result(rdir, src):
    """src（validator が出した validation_report.json）を result.json として原子的に公開する。

    直接 copy すると、書き込み途中の result.json を GET /validation/{uuid} が読んで
    json パースに失敗し 500 になり得る（read_result は厳格にパースする）。status.json と同じく
    tmp + os.replace で、読み手からは「無い」か「完全」のどちらかにしか見えないようにする。
    """
    rdir = Path(rdir)
    dst = result_path(rdir)
    tmp = rdir / f"{_RESULT_NAME}.{os.getpid()}.{new_uuid()[:8]}.tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)
    return dst


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
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    # asctime を JST 表示に固定（コンテナ TZ が UTC でも +9h した壁時計で出す。tzdata 非依存）。
    formatter.converter = lambda secs: time.gmtime((secs if secs is not None else time.time()) + 9 * 3600)
    handler.setFormatter(formatter)
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
