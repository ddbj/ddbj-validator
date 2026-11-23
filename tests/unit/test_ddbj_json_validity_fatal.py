"""ddbj の JSON 報告（--json）は FATAL を error に数える。

以前は level="error" だけを数えていて、FATAL しか無い報告が validity: true / stats.error: 0 に
なっていた。FATAL は error より重いので、validity を false にし、stats.error に含める
（messages の level は "fatal" のまま）。
"""
import json

from common.jsonl import dumps_line
from apps.ddbj.reporter import ValidationReporter


def _report(tmp_path, levels):
    path = tmp_path / "a.ann.jsonl"
    with open(path, "wb") as f:
        for i, level in enumerate(levels):
            f.write(dumps_line({"type": "result", "data": {
                "rule": f"ANN{i:04d}", "level": level, "message": "m", "file": "a.ann", "entry": "ALL"}}))
    out = ValidationReporter(out_dir=tmp_path).write_json_report([str(path)], version="test")
    return json.loads(out.read_text())


def test_fatal_only_report_is_invalid(tmp_path):
    report = _report(tmp_path, ["FATAL"])
    assert report["validity"] is False
    assert report["stats"]["error"] == 1
    assert [m["level"] for m in report["messages"]] == ["fatal"]


def test_fatal_and_error_are_summed(tmp_path):
    report = _report(tmp_path, ["fatal", "error", "ERROR", "warning"])
    assert report["validity"] is False
    assert report["stats"] == {"error": 3, "warning": 1, "info": 0, "auto-cleanup": 0}


def test_warning_only_report_is_valid(tmp_path):
    report = _report(tmp_path, ["warning", "info"])
    assert report["validity"] is True and report["stats"]["error"] == 0
