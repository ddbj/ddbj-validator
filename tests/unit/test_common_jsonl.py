"""common.jsonl（中間 JSONL の読み書き）のテスト。"""
import json

import pytest

from common import jsonl


SAMPLES = [
    {"type": "result", "data": {"rule": "ANN1250", "line_number": 12, "message": "Found: '日本'", "autofix": True}},
    {"type": "file_meta", "data": {"file": "a.ann", "entries": None}},
    {"type": "proposal", "data": {"updates": [{"action": "add_qualifier", "value": ["a", 1, 2.5]}], "t": (1, 2)}},
]


@pytest.mark.parametrize("obj", SAMPLES)
def test_round_trip_matches_stdlib(obj):
    line = jsonl.dumps_line(obj)
    assert isinstance(line, bytes) and line.endswith(b"\n") and line.count(b"\n") == 1
    # 標準の json を通したときと同じ値に戻る（tuple は list になる）
    assert jsonl.loads(line) == json.loads(json.dumps(obj))
    # 標準の json でも読める
    assert json.loads(line) == json.loads(json.dumps(obj))


def test_reads_stdlib_lines_as_str_and_bytes():
    text = json.dumps(SAMPLES[0]) + "\n"   # 日本語は \\u エスケープされる
    assert jsonl.loads(text) == SAMPLES[0]
    assert jsonl.loads(text.encode("utf-8")) == SAMPLES[0]


def test_values_orjson_cannot_write_fall_back_to_stdlib():
    # str 以外のキー、64 bit を超える整数、対にならないサロゲート
    obj = {"data": {1: "a", "big": 2 ** 70, "s": "\ud800"}}
    line = jsonl.dumps_line(obj)
    assert jsonl.loads(line) == json.loads(json.dumps(obj))


def test_works_without_orjson(monkeypatch):
    monkeypatch.setattr(jsonl, "orjson", None)
    line = jsonl.dumps_line(SAMPLES[0])
    assert line == (json.dumps(SAMPLES[0]) + "\n").encode("utf-8")
    assert jsonl.loads(line) == SAMPLES[0]
