"""全 app 共通の auto cleanup（common/cleanup.py、2026-10-03）。

NBSP を含む organism / host が 1 つあるだけで Taxonomy DB（EUC_JP）への問い合わせが丸ごと失敗し、
SSUB051896 の 817 sample で BS_R0045 の taxonomy_id 提案が消えた件を受けて、
空白系の文字・前後の空白・連続空白を **読み込み直後・外部参照の取得前**に強制的にきれいにする。
"""
from pathlib import Path

from common.cleanup import clean_value, normalize_space_like

NBSP = " "
IDEO = "　"
ZWSP = "​"
BOM = "﻿"


# --- common/cleanup ---

def test_clean_value_space_like_and_collapse():
    assert clean_value(f"Bacillus{NBSP}subtilis") == "Bacillus subtilis"
    assert clean_value(f"Bacillus{IDEO} subtilis ") == "Bacillus subtilis"
    assert clean_value(f"{BOM}Homo sapiens") == "Homo sapiens"
    assert clean_value(f"Bacil{ZWSP}lus") == "Bacillus"          # ゼロ幅空白は削除（単語を割らない）
    assert clean_value('  "quoted  value" ') == "quoted value"
    assert clean_value("ok") == "ok"
    assert clean_value(None) is None and clean_value("") == ""


def test_clean_value_options():
    assert clean_value('"x"', unquote=False) == '"x"'
    assert clean_value("a  b \r\n  c\t\td", keep_newlines=True) == "a b\nc d"
    assert normalize_space_like(f"a{NBSP}{NBSP}b") == "a  b"   # 畳み込みはしない


# --- biosample ---

def _bs_xml(tmp_path, organism, host=None):
    host_attr = f'<Attribute attribute_name="host">{host}</Attribute>' if host else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<BioSampleSet><BioSample access="public">
<Ids><Id namespace="BioSample" is_primary="1">SAMD00000001</Id></Ids>
<Description><SampleName>S1</SampleName><Title>S1  title</Title>
<Organism taxonomy_id=""><OrganismName>{organism}</OrganismName></Organism></Description>
<Models><Model>Microbe</Model></Models>
<Attributes><Attribute attribute_name="sample_name">S1</Attribute>
<Attribute attribute_name="strain">K{NBSP}12</Attribute>{host_attr}</Attributes>
</BioSample></BioSampleSet>
"""
    p = tmp_path / "SSUB000001.xml"
    p.write_text(xml, encoding="utf-8")
    return p


def test_bs_cleanup_covers_organism_title_and_attributes(tmp_path):
    from apps.biosample import xml_reader
    from apps.biosample.context import ValidationContext
    from apps.biosample.validator import autocleanup
    sub, _ = xml_reader.parse_xml(str(_bs_xml(tmp_path, f"Bacillus{NBSP}subtilis")))
    res = autocleanup(sub, ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True))
    rec = sub.records[0]
    assert rec.organism == "Bacillus subtilis"
    assert rec.attr("strain") == "K 12"
    assert rec.title == "S1 title" and rec.attr("sample_title") == "S1 title"
    org = [r for r in res if r.get("kind") == "organism"]
    assert len(org) == 1 and org[0]["rule_id"] == "BS_R0013" and org[0]["new_value"] == "Bacillus subtilis"
    # 2 回目は置換・報告を繰り返さない（Validator.pre_run は同じ結果を返す）
    assert autocleanup(sub, None) is res


def test_bs_cleanup_runs_before_taxonomy_fetch(tmp_path, monkeypatch):
    """cli は Taxonomy を引く前に cleanup する。きれいにした organism / host で引くこと。"""
    from apps.biosample import cli
    seen = {}

    def fake_fetch_taxonomy(context, organisms, taxids=None):
        seen["organisms"] = list(organisms)

    monkeypatch.setattr(cli, "_fetch_taxonomy", fake_fetch_taxonomy)
    monkeypatch.setattr(cli, "_fetch_registered_prefixes", lambda context, submission=None: None)
    xml = _bs_xml(tmp_path, f"Bacillus{NBSP}subtilis", host=f"Homo  sapiens{IDEO}")
    args = cli._build_parser().parse_args(["-x", str(xml), "-d", "-o", str(tmp_path / "out")])
    cli.run(args)
    assert seen["organisms"] == ["Bacillus subtilis", "Homo sapiens"]
    fixed = (tmp_path / "out" / "fixed" / "SSUB000001.xml").read_text(encoding="utf-8")
    assert "<OrganismName>Bacillus subtilis</OrganismName>" in fixed
    assert NBSP not in fixed and IDEO not in fixed


# --- bioproject ---

_BP = Path("apps/bioproject/tests/BP_R0043/BP_R0043_1.pass.xml")


def _bp(tmp_path, old, new):
    p = tmp_path / "bp.xml"
    p.write_text(_BP.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return p


def test_bp_cleanup_before_model_and_rules(tmp_path):
    from apps.bioproject import xml_reader
    from apps.bioproject.context import ValidationContext
    from apps.bioproject.validator import Validator
    p = _bp(tmp_path, "<Title>Clean Project Title</Title>",
            f"<Title>Clean{NBSP}Project   Title for cleanup</Title>")
    sub, pre = xml_reader.parse_xml(str(p))
    assert sub.records[0].title == "Clean Project Title for cleanup"
    r59 = [r for r in pre if r["rule_id"] == "BP_R0059"]
    assert len(r59) == 1 and r59[0]["new_value"] == "Clean Project Title for cleanup"
    assert r59[0]["sample"] == "PRJDB0001"
    # NBSP は消えているので BP_R0060（非 ASCII）は出ない。Grant など全要素が対象
    res = Validator(ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)).run(sub)
    assert not [r for r in res if r["rule_id"] in ("BP_R0060", "BP_R0059")]
    assert sub.records[0].grants[0].agency == "Japan Society for the Promotion of Science"


def test_bp_cleanup_covers_every_element_and_skips_indentation(tmp_path):
    from apps.bioproject import xml_reader
    p = _bp(tmp_path, "Japan Society for the Promotion of Science",
            f"Japan  Society{NBSP}for the Promotion of Science")
    sub, pre = xml_reader.parse_xml(str(p))
    assert sub.records[0].grants[0].agency == "Japan Society for the Promotion of Science"
    assert [r["target"] for r in pre if r["rule_id"] == "BP_R0059"] == [
        "PackageSet/Package/Project/Project/ProjectDescr/Grant/Agency"]
    # 整形インデント（前後の ASCII 空白だけ）は報告しない
    p2 = _bp(tmp_path, "<Title>Clean Project Title</Title>", "<Title>\n   Clean Project Title\n</Title>")
    sub2, pre2 = xml_reader.parse_xml(str(p2))
    assert sub2.records[0].title == "Clean Project Title"
    assert not [r for r in pre2 if r["rule_id"] == "BP_R0059"]


# --- gea / metabobank（MAGE-TAB charnorm） ---

def _magetab_sub(idf_values, rows):
    from types import SimpleNamespace
    idf = SimpleNamespace(field_order=list(idf_values), fields={k: [v] for k, v in idf_values.items()})
    header = ["Source Name", "Characteristics[organism]"]
    sdrf = SimpleNamespace(header=header, rows=rows,
                           col_indices=lambda name: [i for i, h in enumerate(header) if h == name])
    return SimpleNamespace(idf=idf, sdrf=sdrf)


def test_magetab_whitespace_cleanup():
    from common.magetab.charnorm import apply_to_submission
    sub = _magetab_sub({"Investigation Title": "  My  study ",
                        "Protocol Description": "line1  \n  line2"},
                       [[" S1 ", f"Homo{NBSP}sapiens"]])
    fixes = apply_to_submission(sub)
    assert sub.idf.fields["Investigation Title"] == ["My study"]
    assert sub.idf.fields["Protocol Description"] == ["line1\nline2"]      # 改行は残す
    assert sub.sdrf.rows == [["S1", "Homo sapiens"]]
    ws = {(f["target"], f["where"]) for f in fixes if f["whitespace"]}
    assert ws == {("IDF", "Investigation Title"), ("IDF", "Protocol Description"), ("SDRF", "Source Name")}
    # NBSP は従来どおり mapped（文字の正規化）として報告。空白 cleanup としては二重に出さない
    nb = [f for f in fixes if f["where"] == "Characteristics[organism]"][0]
    assert nb["mapped"] == {NBSP} and not nb["whitespace"]


def test_gea_and_mb_rules_report_whitespace_cleanup():
    from apps.gea.rules.idf import GEA_G0017
    from apps.gea.rules.sdrf import GEA_SR0016
    from apps.metabobank.rules.idf import MB_IR0024
    from apps.metabobank.rules.sdrf import MB_SR0030
    from common.magetab.charnorm import apply_to_submission
    for idf_rule, sdrf_rule in ((GEA_G0017(), GEA_SR0016()), (MB_IR0024(), MB_SR0030())):
        sub = _magetab_sub({"Investigation Title": "My  study"}, [["S1 ", "Homo sapiens"]])
        apply_to_submission(sub)
        out = idf_rule.validate(sub, None) + sdrf_rule.validate(sub, None)
        msgs = [r["message"] for r in out if r["level"] == "warning"]
        assert len(msgs) == 2 and all("whitespace was removed" in m for m in msgs), msgs


# --- ddbj ---

def test_ddbj_preprocessor_replaces_space_like_before_non_ascii_check(tmp_path):
    from apps.ddbj.preprocessor import preprocess_files
    ann = tmp_path / "a.ann"
    fasta = tmp_path / "a.fasta"
    ann.write_text(f"seq1\tsource\t1..10\torganism\tMus{NBSP}musculus\n"
                   f"\t\t\tstrain\tB6{IDEO}{IDEO}J\n", encoding="utf-8")
    fasta.write_text(">seq1\nacgtacgtac\n//\n", encoding="utf-8")
    lines, _, warns = preprocess_files(str(ann), str(fasta))
    assert lines == ["seq1\tsource\t1..10\torganism\tMus musculus", "\t\t\tstrain\tB6 J"]
    rules = [w["rule"] for w in warns]
    assert "ANN0040" not in rules
    assert any(w["rule"] == "ANN0170" and "Space-like" in w["message"] for w in warns)
