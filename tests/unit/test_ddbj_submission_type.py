"""ddbj --common-only で submission type を返す（2026-11-04）。CLI の JSON / テキストと web api の ddbj_annotation。

type は推定せず、COMMON の DATATYPE / DIVISION の申告から決める。KEYWORD から逆引きした type が
申告と合わないときは candidates に入れる。
"""
import json
import subprocess

from apps.ddbj.context import ValidationContext
from apps.ddbj.parser import parse_ddbj_submission
from apps.ddbj.reporter import ValidationReporter
from apps.ddbj.submission_type import detect_submission_type
from apps.webapi import runner

HEAD = "COMMON\tSUBMITTER\t\tab_name\tMishima,H.\n"


def _detect(common_lines):
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    lines = (HEAD + common_lines).splitlines()
    records, _, _ = parse_ddbj_submission("", "a.ann", lines, ctx.ddbj_dict)
    return detect_submission_type(records, ctx.ddbj_dict)


def test_wgs_declared():
    r = _detect("\tDATATYPE\t\ttype\tWGS\n\tKEYWORD\t\tkeyword\tWGS\n\t\t\tkeyword\tSTANDARD_DRAFT\n")
    assert r["submission_type"] == "WGS"
    assert r["keywords"] == ["WGS", "STANDARD_DRAFT"]
    assert r["candidates"] == []


def test_tpa_and_wgs_written_separately_are_composed():
    r = _detect("\tDATATYPE\t\ttype\tTPA\n\t\t\ttype\tWGS\n\tKEYWORD\t\tkeyword\tTPA\n")
    assert r["submission_type"] == "TPA-WGS"
    assert r["candidates"] == []


def test_division_only_type():
    r = _detect("\tDIVISION\t\tdivision\tEST\n\tKEYWORD\t\tkeyword\tEST\n")
    assert r["submission_type"] == "EST"
    assert r["divisions"] == ["EST"]


def test_taxonomic_division_is_not_a_type():
    assert _detect("\tDIVISION\t\tdivision\tBCT\n")["submission_type"] is None


def test_not_declared_keyword_suggests_candidates():
    r = _detect("\tKEYWORD\t\tkeyword\tWGS\n")
    assert r["submission_type"] is None
    assert r["candidates"] == ["WGS"]


def test_keyword_disagrees_with_declared_type():
    r = _detect("\tDATATYPE\t\ttype\tTLS\n\tKEYWORD\t\tkeyword\tWGS\n")
    assert r["submission_type"] == "TLS"
    assert r["candidates"] == ["WGS"]


def _jsonl(tmp_path, name, sub_type):
    p = tmp_path / f"{name}.jsonl"
    p.write_text(json.dumps({"type": "submission_type", "data": {"file": name, **sub_type}}) + "\n")
    return str(p)


def test_json_report_carries_submission_types(tmp_path):
    t = {"submission_type": "WGS", "datatypes": ["WGS"], "divisions": [], "keywords": [], "candidates": []}
    paths = [_jsonl(tmp_path, "a.ann", t), _jsonl(tmp_path, "b.ann", t)]
    out = ValidationReporter(tmp_path).write_json_report(paths, version="x", scope="common_only")
    d = json.loads(out.read_text())
    assert d["submission_type"] == "WGS"
    assert [t["file"] for t in d["submission_types"]] == ["a.ann", "b.ann"]


def test_json_report_mixed_types_has_no_overall(tmp_path):
    a = {"submission_type": "WGS", "candidates": []}
    b = {"submission_type": "TSA", "candidates": []}
    out = ValidationReporter(tmp_path).write_json_report(
        [_jsonl(tmp_path, "a.ann", a), _jsonl(tmp_path, "b.ann", b)], scope="common_only")
    assert json.loads(out.read_text())["submission_type"] is None


def test_json_report_without_common_only_has_no_type_keys(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text(json.dumps({"type": "result", "data": {"rule": "ANN0001", "level": "ERROR"}}) + "\n")
    d = json.loads(ValidationReporter(tmp_path).write_json_report([str(p)]).read_text())
    assert "submission_type" not in d and "submission_types" not in d


def test_text_report_header(tmp_path):
    t = {"submission_type": None, "candidates": ["WGS"]}
    s, _ = ValidationReporter(tmp_path).generate_report([_jsonl(tmp_path, "a.ann", t)], print_console=False)
    assert "Submission Type: not declared (keywords suggest: WGS)" in s.read_text()


# ---- web api: ddbj_annotation ロール ----

def test_webapi_annotation_saved_with_ann_extension(tmp_path):
    p = runner.save_upload(tmp_path, "ddbj_annotation", "NSUB000001", b"x")
    assert p.name == "NSUB000001.ann"
    assert runner.save_upload(tmp_path, "ddbj_annotation", "a.ann.txt", b"x").name == "a.ann.txt"
    assert runner.save_upload(tmp_path, "ddbj_annotation", None, b"x").name == "ddbj_annotation.ann"


def test_webapi_annotation_runs_common_only_with_json(tmp_path, monkeypatch):
    ann = runner.save_upload(tmp_path, "ddbj_annotation", "a.ann", b"x")
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner.run_validation(tmp_path, {"ddbj_annotation": ann}, {"account": "acc1"})
    cmd = seen["cmd"]
    i = cmd.index("ddbj")
    # ddbj の -d は --dir、-j は --jobs なので付けない（JSON は --json、モードは既定の内部 DB）
    assert cmd[i:] == ["ddbj", "--scope", "common", str(ann), "--json", "-o", str(tmp_path), "--account", "acc1"]


def test_webapi_annotation_source_scope_applies_autofix(tmp_path, monkeypatch):
    ann = runner.save_upload(tmp_path, "ddbj_annotation", "a.ann", b"x")
    assert runner.plan({"ddbj_annotation": ann}, {"scope": "source"}) == ["ddbj", "--scope", "source", str(ann), "-f"]


def test_webapi_unknown_scope_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        runner.normalise_ddbj_scope("all")
    assert runner.normalise_ddbj_scope(" Source ") == "source"
    assert runner.normalise_ddbj_scope("") is None
