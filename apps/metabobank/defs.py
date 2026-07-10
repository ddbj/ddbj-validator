"""MetaboBank 定義ファイル（resources/definitions.json）ローダ。"""
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
    return re.compile(pattern, flags)
