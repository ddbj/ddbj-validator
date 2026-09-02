"""各 DB の定義 JSON（apps/<db>/resources/definitions.json）をそのまま提供する。

登録システム（MetaboBank の mb-system 等）が、フォームのプルダウン（Submission type /
Experimental Design、IDF の項目名と出力順、SDRF 列順、MAF 固定列）の**正本**としてこの定義を
読んでいる。従来はリポジトリ内のファイルを直接読んでいたが、それだと「登録システムが検証を
投げる先の API インスタンスが使っている定義」と一致する保証がない（同一ホストに複数クローンが
あり、ブランチも版もそろわない）。投げる先そのものから HTTP で取れるようにするためのモジュール。

中身は**加工しない**（キーの追加・変更を validator 側の都合で入れてよいようにする）。
代わりに出どころ（version / commit）を添えて、食い違ったときに切り分けられるようにする。
"""
import json
import os
import subprocess
from functools import lru_cache
from importlib import import_module
from pathlib import Path

# definitions.json を持つ DB。biosample は形式が異なり /package_list・/attribute_list が担当する。
DBS = ("ddbj", "bioproject", "dra", "gea", "metabobank")

_APPS = Path(__file__).resolve().parents[1]      # <repo>/apps
_REPO_ROOT = _APPS.parent


def has_db(db):
    return db in DBS


@lru_cache(maxsize=None)
def definitions(db):
    """apps/<db>/resources/definitions.json の中身（プロセス内キャッシュ）。"""
    return json.loads((_APPS / db / "resources" / "definitions.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def version(db):
    """サブコマンドごとの版（apps/<db>/__init__.py の __version__）。"""
    return getattr(import_module(f"apps.{db}"), "__version__", "")


@lru_cache(maxsize=1)
def commit():
    """稼働中コードの commit（短縮 hash）。取れなければ空文字（運用は version だけで回る）。

    コンテナに .git を含めない運用があるので、ビルド時に埋める DDBJ_COMMIT を優先し、
    無ければ git に聞く。1 プロセス 1 回だけ実行する。
    """
    env = os.environ.get("DDBJ_COMMIT", "").strip()
    if env:
        return env
    try:
        p = subprocess.run(["git", "-C", str(_REPO_ROOT), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""
