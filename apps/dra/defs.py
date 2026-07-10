"""DRA の定義ファイル（resources/definitions.json）ローダ。cv_terms / formats を提供。

ロード実体と正規表現コンパイルは common/defs_loader に集約（bp/dra/metabobank で共通）。
"""
from pathlib import Path
from common.defs_loader import load_json, compiled  # noqa: F401  （compiled は再エクスポート）

_DEFS_PATH = str(Path(__file__).parent / "resources" / "definitions.json")


def load_definitions():
    return load_json(_DEFS_PATH)


def formats():
    return load_definitions().get("formats", {})


def cv_terms():
    return load_definitions().get("cv_terms", {})
