"""BioProject の定義ファイル（resources/definitions.json）ローダ。

cv_terms（管理語彙・Core.xsd 由来）と formats（min spec の数値・正規表現）を提供する。
ロード結果と正規表現のコンパイルは lru_cache で 1 回だけ行う。
"""
import json
import re
import functools
from pathlib import Path

_DEFS_PATH = Path(__file__).parent / "resources" / "definitions.json"


@functools.lru_cache(maxsize=1)
def load_definitions():
    with open(_DEFS_PATH, encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def compiled(pattern, flags=0):
    """パターン文字列を 1 回だけコンパイルして返す（rule から formats の正規表現を使う用）。"""
    return re.compile(pattern, flags)


def formats():
    return load_definitions().get("formats", {})


def cv_terms():
    return load_definitions().get("cv_terms", {})
