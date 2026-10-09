"""DRA の DDBJ Record（v3 JSON）入力の読み方を固定する。

XML と同じ内容なら同じルールが発火すること自体は、シナリオ全件の一致テスト
（apps/dra/tests/run_record_parity_test.py）が見る。ここは v3 にしか無い書き方
（relations、小文字の layout、alias と index による source）の読み方を見る。

実行: リポジトリルートで `.venv/bin/python -m pytest -m record tests/unit`
"""
import json

import pytest

from apps.dra import cli as dra_cli
from apps.dra import record_reader
from apps.dra import reporter

# DDBJ Record 入力のテスト。既定では走らない（`pytest -m record`。README「DDBJ Record のテスト」）。
pytestmark = pytest.mark.record


def _write(tmp_path, record, name="record.json"):
    path = tmp_path / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _read(tmp_path, record):
    return record_reader.parse_record(str(_write(tmp_path, record)))


def _relation(type_, source, target):
    return {"type": type_, "source": source, "target": target}


_SUBMISSION = {"alias": "amr_ddbj-0104_Submission", "hold_date": "2027-01-01"}


@pytest.mark.parametrize("layout, nominal_length, expected", [
    ("paired", 300, ("PAIRED", "300")),
    # スキーマ（pydantic の lax）は数字の文字列も int として受けるので、それも読む。
    ("paired", "300", ("PAIRED", "300")),
    # XML と同じく、insert size は PAIRED のときだけ読む。
    ("single", 300, ("SINGLE", None)),
])
def test_layout_is_read_back_into_the_xml_element_name(tmp_path, layout, nominal_length, expected):
    """v3 は要素名を小文字にした値。ルールは 'PAIRED' と比べる（DRA_R0019 / R0027）。"""
    sub, errors = _read(tmp_path, {"submission": _SUBMISSION, "experiments": [
        {"alias": "E1", "library": {"layout": layout, "nominal_length": nominal_length}}]})
    assert [e for e in errors if e["level"] == "error"] == []
    assert (sub.experiments[0].library_layout, sub.experiments[0].nominal_length) == expected


def test_unknown_layout_is_reported_not_dropped(tmp_path):
    """v3 のスキーマは layout を縛らない（XML では XSD が縛っていた）。黙って外すと
    DRA_R0019 / R0027 が何も言わなくなる。"""
    _, errors = _read(tmp_path, {"submission": _SUBMISSION, "experiments": [
        {"alias": "E1", "library": {"layout": "PAIRED", "nominal_length": 300}}]})
    assert [(e["rule_id"], e["sample"]) for e in errors] == [("DRA_R0002", "E1")]


def test_references_come_from_relations(tmp_path):
    sub, errors = _read(tmp_path, {
        "submission": _SUBMISSION,
        "experiments": [{"alias": "E1"}],
        "runs": [{"accession": "DRR1"}],
        "analyses": [{"accession": "DRZ1"}],
        "relations": [
            _relation("part_of", {"type": "experiment", "alias": "E1"}, {"db": "project", "accession": "PRJDB1"}),
            _relation("part_of", {"type": "experiment", "alias": "E1"}, {"db": "sample", "accession": "SAMD1"}),
            _relation("part_of", {"type": "run", "accession": "DRR1"},
                      {"db": "experiment", "accession": "DRX1", "id": "E1"}),
            _relation("part_of", {"type": "analysis", "accession": "DRZ1"}, {"db": "project", "accession": "PRJDB1"}),
            _relation("derived_from", {"type": "analysis", "accession": "DRZ1"}, {"db": "sample", "accession": "SAMD1"}),
            _relation("derived_from", {"type": "analysis", "accession": "DRZ1"}, {"db": "run", "accession": "DRR1"}),
            # XML と同じく、accession の無い TARGET と、sample / run 以外の TARGET は読まない。
            _relation("derived_from", {"type": "analysis", "accession": "DRZ1"}, {"db": "run", "id": "R1"}),
            _relation("derived_from", {"type": "analysis", "accession": "DRZ1"}, {"db": "experiment", "accession": "DRX1"}),
            # source の無い relation は record 全体が起点。どの object の参照でもない。
            _relation("related_to", None, {"db": "project", "accession": "PRJDB9"}),
            # DRA が読まない種類を source にするものは読まない（解決もしない）。
            _relation("related_to", {"type": "project", "accession": "PRJDB1"}, {"db": "bioproject", "id": "1"}),
        ],
    })
    assert [e for e in errors if e["level"] == "error"] == []
    e, r, a = sub.experiments[0], sub.runs[0], sub.analyses[0]
    assert (e.study_ref, e.sample_ref) == ("PRJDB1", "SAMD1")
    assert (r.experiment_ref, r.experiment_refname) == ("DRX1", "E1")
    assert (a.study_ref, a.sample_refs, a.run_refs) == ("PRJDB1", ["SAMD1"], ["DRR1"])


def test_sample_relation_alone_makes_design_present(tmp_path):
    """DESIGN は v3 に入れ物として無い。SAMPLE_DESCRIPTOR は DESIGN の下なので、sample への
    relation だけでも DESIGN は「ある」。LIBRARY_DESCRIPTOR は無いので DRA_R0002 はそちらを言う。"""
    sub, _ = _read(tmp_path, {"submission": _SUBMISSION, "experiments": [{"alias": "E1"}], "relations": [
        _relation("part_of", {"type": "experiment", "alias": "E1"}, {"db": "sample", "accession": "SAMD1"})]})
    e = sub.experiments[0]
    assert (e.design_present, e.library_descriptor_present, e.platform_present) == (True, False, False)


@pytest.mark.parametrize("source, resolved", [
    ({"type": "run", "alias": "R", "index": 1}, ["-", "DRX1"]),
    # alias は前後の空白を除き、続く空白を 1 つとみなして比べる（#18）。
    ({"type": "run", "alias": " R ", "index": 0}, ["DRX1", "-"]),
])
def test_namesakes_are_told_apart_by_index(tmp_path, source, resolved):
    sub, errors = _read(tmp_path, {"submission": _SUBMISSION, "runs": [{"alias": "R"}, {"alias": "R"}],
                                   "relations": [_relation("part_of", source,
                                                           {"db": "experiment", "accession": "DRX1"})]})
    assert errors == []
    assert [r.experiment_ref or "-" for r in sub.runs] == resolved


def test_lax_integers_are_read_like_the_schema_reads_them(tmp_path):
    """スキーマ（pydantic の lax）は "1" や 1.0 も int として受ける。形の確認がそれより厳しいと、
    スキーマが通す record でルールが 1 つも動かなくなる。"""
    sub, errors = _read(tmp_path, {
        "submission": _SUBMISSION,
        "experiments": [{"alias": "E1", "library": {"layout": "paired", "nominal_length": 300.0}}],
        "runs": [{"alias": "R"}, {"alias": "R"}],
        "relations": [_relation("part_of", {"type": "run", "alias": "R", "index": "1"},
                                {"db": "experiment", "accession": "DRX1"})]})
    assert [e for e in errors if e["level"] == "error"] == []
    assert sub.experiments[0].nominal_length == "300"
    assert [r.experiment_ref for r in sub.runs] == [None, "DRX1"]


@pytest.mark.parametrize("aliases, source", [
    # 正準形は NFC なので、合成済みと分解された "é" は同じ alias。
    (["\u00e9", "e\u0301"], {"alias": "\u00e9", "index": 1}),
    # U+200B も空白として畳む（Python の \s は含まない）。
    (["x\u200by", "x y"], {"alias": "x y", "index": 1}),
    # alias の無いものと空白だけの alias は、正準形ではどちらも alias が無い。
    ([None, " "], {"index": 1}),
])
def test_namesakes_are_counted_on_the_canonical_form(tmp_path, aliases, source):
    """converter（ddbj-repository の DRA::Converter）は正準形で同じ alias を数えて index を書く。
    違う比べ方をすると、converter の書いた index が何も指さなくなる。"""
    runs = [{"alias": a} if a is not None else {"title": "t"} for a in aliases]
    sub, errors = _read(tmp_path, {"submission": _SUBMISSION, "runs": runs, "relations": [
        _relation("part_of", {"type": "run", **source}, {"db": "experiment", "accession": "DRX1"})]})
    assert [e for e in errors if e["level"] == "error"] == []
    assert [r.experiment_ref for r in sub.runs] == [None, "DRX1"]


def test_targeted_loci_count_as_library_descriptor(tmp_path):
    """LIBRARY_DESCRIPTOR/TARGETED_LOCI は library の外（experiments[].targeted_loci）に載る。"""
    sub, _ = _read(tmp_path, {"submission": _SUBMISSION, "experiments": [
        {"alias": "E1", "targeted_loci": [{"name": "16S rRNA"}]}]})
    e = sub.experiments[0]
    assert (e.design_present, e.library_descriptor_present) == (True, True)


@pytest.mark.parametrize("source", [
    {"type": "run", "accession": "DRR9"},
    {"type": "run", "alias": "R"},              # 2 つある alias を index 無しで
    {"type": "run", "alias": "R", "index": 2},  # 無い位置
    {"type": "run", "alias": "Q"},
])
def test_unresolvable_source_is_reported(tmp_path, source):
    _, errors = _read(tmp_path, {"submission": _SUBMISSION, "runs": [{"alias": "R"}, {"alias": "R"}],
                                 "relations": [_relation("part_of", source,
                                                         {"db": "experiment", "accession": "DRX1"})]})
    assert [(e["rule_id"], e["level"]) for e in errors] == [("DRA_R0002", "error")]
    assert "relations.0.source" in errors[0]["message"]


def test_second_single_reference_is_reported_and_the_first_is_read(tmp_path):
    source = {"type": "experiment", "alias": "E1"}
    sub, errors = _read(tmp_path, {"submission": _SUBMISSION, "experiments": [{"alias": "E1"}], "relations": [
        _relation("part_of", source, {"db": "project", "accession": "PRJDB1"}),
        _relation("part_of", source, {"db": "project", "accession": "PRJDB2"})]})
    assert sub.experiments[0].study_ref == "PRJDB1"
    assert [(e["rule_id"], e["sample"]) for e in errors] == [("DRA_R0002", "E1")]


def test_files_are_gathered_across_data_blocks(tmp_path):
    sub, _ = _read(tmp_path, {"submission": _SUBMISSION, "runs": [{"alias": "R1", "data_blocks": [
        {"files": [{"filename": "a.fastq", "filetype": "fastq"}]},
        {"files": [{"filename": "b.fastq", "filetype": "fastq", "checksum_method": "MD5", "checksum": "x"}]},
    ]}]})
    assert [(f.filename, f.checksum) for f in sub.runs[0].files] == [("a.fastq", None), ("b.fastq", "x")]
    assert sub.runs[0].data_block_present


def test_submission_meta(tmp_path):
    sub, _ = _read(tmp_path, {"submission": {
        "accession": "DRA1", "alias": "s", "center_name": "NIG", "hold_date": "2027-01-01",
        "sra": {"lab_name": "Lab", "contacts": [{"name": "Mishima", "inform_on_error": "m@example.org"}]}}})
    m = sub.submission
    assert (m.accession, m.alias, m.center_name, m.lab_name, m.hold_date) == ("DRA1", "s", "NIG", "Lab", "2027-01-01")
    assert m.contacts == [{"name": "Mishima", "inform_on_status": None, "inform_on_error": "m@example.org"}]


def test_role_files_name_the_record(tmp_path):
    """レポートの見出しは役割ごとのファイル名。record ではファイルが 1 つなので、それを載っている役割に置く。"""
    path = _write(tmp_path, {"submission": _SUBMISSION, "experiments": [{"alias": "E1"}]}, name="DRA1.json")
    sub, _ = record_reader.parse_record(str(path))
    assert sub.role_files == {"submission": ["DRA1.json"], "experiment": ["DRA1.json"]}


@pytest.mark.parametrize("record, field", [
    ({"experiments": [{"library": {"nominal_length": 1.5}}]}, "experiments.0.library.nominal_length"),
    ({"experiments": [{"legacy": "x"}]}, "experiments.0.legacy"),
    ({"experiments": [{"library": "paired"}]}, "experiments.0.library"),
    ({"runs": [{"data_blocks": [{"files": [{"filename": 1}]}]}]}, "runs.0.data_blocks.0.files.0.filename"),
    ({"relations": [{"source": {"type": "run", "index": "first"}}]}, "relations.0.source.index"),
    ({"submission": {"sra": {"contacts": {}}}}, "submission.sra.contacts"),
])
def test_shape_is_checked_without_the_schema_package(tmp_path, record, field):
    """スキーマパッケージが無くても、reader が前提にする形は自前で確かめる。落ちると
    終了コード 1（＝「検証は終わった」）と同じ顔をする。"""
    sub, errors = _read(tmp_path, record)
    assert sub is None
    assert [e["rule_id"] for e in errors] == ["DRA_R0002"]
    assert f"({field}:" in errors[0]["message"]


def test_info_gets_its_own_section_in_the_text_report():
    """info は validity にも件数にも入らない注記。warning の節に混ぜると警告に見える。"""
    lines = reporter._detail_body([
        {"rule_id": "DRA_R0010", "level": "error", "sample": "DRX1", "target": "EXPERIMENT/TITLE", "message": "e"},
        {"rule_id": "DRA_R0002", "level": "info", "sample": None, "target": "#not_validated", "message": "i"},
    ])
    assert lines[lines.index("[ INFO ]") + 1].startswith("DRA_R0002:")
    assert "[ WARNING ]" not in lines


def test_cli_refuses_record_and_xml_together(tmp_path):
    xml = tmp_path / "sub.xml"
    xml.write_text('<SUBMISSION alias="s"/>', encoding="utf-8")
    args = dra_cli._build_parser().parse_args(["-r", str(_write(tmp_path, {"submission": _SUBMISSION})),
                                               "--sub", str(xml), "-l", "-j", "-o", str(tmp_path / "out")])
    assert dra_cli.run(args) == 2


@pytest.mark.parametrize("extra, expected", [
    ([], "amr_ddbj-0104"),                      # XML と同じく submission の alias から
    (["-s", "other_account-0001"], "other_account-0001"),
])
def test_cli_submission_id(tmp_path, extra, expected):
    out  = tmp_path / "out"
    record = {"submission": _SUBMISSION, "experiments": [{"alias": "E1"}]}
    args = dra_cli._build_parser().parse_args(["-r", str(_write(tmp_path, record)), "-l", "-o", str(out), *extra])
    dra_cli.run(args)
    assert f"Submission ID: {expected}" in (out / "reports" / "validation_report_details.txt").read_text()


def test_whole_document_is_validated_against_the_v3_schema(tmp_path):
    """`[record]` extra があれば v3 スキーマでドキュメント全体を検証する。"""
    pytest.importorskip("ddbj_record")
    _, errors = _read(tmp_path, {"submission": _SUBMISSION, "experiments": [{"alias": "E1", "bogus": 1}]})
    assert [(e["rule_id"], e["level"]) for e in errors] == [("DRA_R0002", "error")]
    assert "experiments.0.bogus" in errors[0]["message"]
