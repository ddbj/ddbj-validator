"""patent app（特許の ann + FASTA の検査）の単体テスト。

規則ごとの pass / fail は E2E（apps/patent/tests/run_tests.py）で見る。ここでは E2E で見にくいもの
（taxonomy を引く PAT0043、値に手を入れない前処理、使う検査だけを残す絞り込み、報告の flag）を見る。
"""
import json
from datetime import date

import pytest

from apps.ddbj.preprocessor import preprocess_files
from apps.patent import constants as C
from apps.patent import runner
from apps.patent.reporter import PatentReporter
from apps.patent.rules.fields import parse_date
from apps.patent.rules.sequence import iter_fasta

_ANN = "\n".join([
    "Entry\tFeature\tLocation\tQualifier\tValue",
    "COMMON\tDIVISION\t\tdivision\tPAT",
    "1\tKEYWORD\t\tkeyword\tJP 2026524816-A/1",
    "\tREFERENCE\t1..20\ttitle\tEXAMPLE",
    "\t\t\tjournal\tPatent: JP 2026524816-A 1 24-JUL-2026;",
    "\t\t\tjournal\tExample Pharma AG",
    "\tCOMMENT\t\tline\tOS   Examplea  testensis",
    "\t\t\tline\tPN   JP 2026524816-A/1",
    "\t\t\tline\tPD   24-JUL-2026",
    "\t\t\tline\tPS   1",
    "\t\t\tline\tFH   Key             Location/Qualifiers",
    "\t\t\tline\tFT                   /note=\"quoted  value\"",
    "\tsource\t1..20\torganism\tExamplea testensis",
    "\t\t\tmol_type\tother DNA",
    "\t\t\tff_definition\tJP 2026524816-A/1: EXAMPLE.",
]) + "\n"
_FASTA = ">1\nacgtacgtacgtacgtacgt\n//\n"


@pytest.fixture
def one_set(tmp_path):
    ann = tmp_path / "00001_JP2026524816_na.ann"
    ann.write_text(_ANN)
    (tmp_path / "00001_JP2026524816_na.fasta").write_text(_FASTA)
    return ann


def _messages(tmp_path, ann, known):
    task = runner.PatentTask(str(ann), str(ann.with_suffix(".fasta")), str(tmp_path), known, date(2026, 11, 23))
    path = runner.validate_set(task)
    return [json.loads(line)["data"] for line in open(path) if json.loads(line)["type"] == "result"]


def test_cleanup_false_keeps_values_as_they_are(one_set):
    lines, _, warns = preprocess_files(str(one_set), str(one_set.with_suffix(".fasta")), cleanup=False)
    assert "\t\t\tline\tFT                   /note=\"quoted  value\"" in lines   # 連続する空白も引用符もそのまま
    assert "\tCOMMENT\t\tline\tOS   Examplea  testensis" in lines
    assert lines[0] == ""            # 見出し行は読み飛ばす（行番号は保つ）
    assert warns == []               # ANN0170 / 0180 / 0185 / 0190 を出さない


def test_cleanup_default_is_unchanged(one_set):
    lines, _, warns = preprocess_files(str(one_set), str(one_set.with_suffix(".fasta")))
    assert "\tCOMMENT\t\tline\tOS Examplea testensis" in lines
    assert {w["rule"] for w in warns} >= {"ANN0170", "ANN0185", "ANN0190"}


def test_clean_set_has_no_message_without_taxonomy(tmp_path, one_set):
    assert _messages(tmp_path, one_set, None) == []


def test_pat0043_organism_not_in_taxonomy_is_info(tmp_path, one_set):
    msgs = _messages(tmp_path, one_set, set())
    assert [(m["rule"], m["level"], m["entry"]) for m in msgs] == [("PAT0043", "info", "1")]
    assert _messages(tmp_path, one_set, {"Examplea testensis"}) == []


def test_pat0043_fixed_names_are_always_ok(tmp_path, one_set):
    one_set.write_text(_ANN.replace("organism\tExamplea testensis", "organism\tsynthetic construct"))
    assert _messages(tmp_path, one_set, set()) == []


def test_filter_keeps_only_selected_rules_and_maps_fatal_to_error():
    results = [{"rule": "ANN0185", "level": "FATAL"}, {"rule": "ANN0040", "level": "fatal"},
               {"rule": "SEQ0090", "level": "error"}, {"rule": "PAT0041", "level": "flag"}, {"rule": "MODE", "level": "info"}]
    assert [(r["rule"], r["level"]) for r in runner.filter_results(results)] == [("ANN0040", "error"), ("PAT0041", "flag")]


def test_set_kind_from_file_name():
    assert C.set_kind("00001_JP2024054176_na.ann") == C.KIND_NA
    assert C.set_kind("/x/00002_JP2024054176_aa.ann") == C.KIND_AA
    assert C.set_kind("PAT0012_1.fail_na.ann") == C.KIND_NA
    assert C.set_kind("sample.ann") is None


def test_amino_acid_codes_come_from_ddbj_definitions():
    assert "J" in C.AA_CHARS and "O" in C.AA_CHARS and "U" in C.AA_CHARS
    assert "*" not in C.AA_CHARS
    assert {"ALA", "ARG", "XLE"} <= C.AA_THREE_LETTER and "AAD" not in C.AA_THREE_LETTER


def test_parse_date():
    assert parse_date("24-JUL-2026") == date(2026, 7, 24)
    assert parse_date("31-FEB-2024") is None
    assert parse_date("24-Jul-2026") is None
    assert parse_date("2026-07-24") is None


def test_iter_fasta_keeps_case_and_drops_terminator():
    assert list(iter_fasta(">1\nACgt\nnn\n//\n>2 desc\nMKT\n//\n>3\n//\n")) == [("1", "ACgtnn"), ("2", "MKT"), ("3", "")]


def test_json_report_has_flag_level_and_count(tmp_path, one_set):
    one_set_aa = tmp_path / "00002_JP2026524816_aa.ann"
    one_set_aa.write_text(_ANN.replace("\t\t\tmol_type\tother DNA\n", "").replace("1..20", "1..30"))
    (tmp_path / "00002_JP2026524816_aa.fasta").write_text(">1\nMetLysThrAlaTyrIleAlaLysGlnArg\n//\n")
    task = runner.PatentTask(str(one_set_aa), str(one_set_aa.with_suffix(".fasta")), str(tmp_path), None, date(2026, 11, 23))
    path = runner.validate_set(task)
    out = PatentReporter(out_dir=tmp_path).write_json_report([path], version="test")
    report = json.loads(out.read_text())
    assert report["stats"]["flag"] == 1 and report["validity"] is True
    flags = [(m["file"], m["entry"], m["id"], m["level"]) for m in report["messages"] if m["level"] == "flag"]
    assert flags == [("00002_JP2026524816_aa.ann", "1", "PAT0041", "flag")]
