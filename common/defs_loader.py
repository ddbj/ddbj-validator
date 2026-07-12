"""定義 JSON のロードと正規表現コンパイルの共通ユーティリティ。

bioproject / dra / metabobank の defs.py が個別に持っていた load_definitions()＋compiled() を集約。
各 app は自分の definitions.json パスを渡すだけ。結果は lru_cache で 1 回だけ読む。
"""
import json
import re
import functools


@functools.lru_cache(maxsize=None)
def load_json(path):
    """path（str）の JSON を読み込む（パス単位でキャッシュ）。"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@functools.lru_cache(maxsize=None)
def compiled(pattern, flags=0):
    """正規表現を 1 回だけコンパイルして返す。"""
    return re.compile(pattern, flags)
