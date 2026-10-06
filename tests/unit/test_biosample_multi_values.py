"""profile=next で同名多値を許す属性（allow_multiple）は、先頭値だけでなく全値を検査する（2026-10-04）。

対象: locus_tag_prefix / component_organism / culture_collection / metagenome_source /
specimen_voucher / virus_enrich_appr。2 つ目の値だけが誤っているとき、その値が報告されること。
"""
from types import SimpleNamespace

from apps.biosample.context import ValidationContext
from apps.biosample.model import BioSampleRecord
from apps.biosample.rules.account import BS_R0128
from apps.biosample.rules.consistency import BS_R0062
from apps.biosample.rules.controlled import BS_R0138
from apps.biosample.rules.identifier import BS_R0091, BS_R0099, BS_R0102, BS_R0109
from apps.biosample.rules.taxonomy import BS_R0105, BS_R0106, BS_R0115
from apps.biosample.rules.voucher import CultureCollectionValidator, SpecimenVoucherValidator


def _ctx(**kw):
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True, profile="next")
    for k, v in kw.items():
        setattr(ctx, k, v)
    return ctx


def _rec(sample, attrs, **kw):
    return BioSampleRecord(sample_name=sample, attributes=attrs, **kw)


def _sub(*recs, submission_id="SSUB000001"):
    return SimpleNamespace(records=list(recs), submission_id=submission_id)


def _found(results, rule_id=None):
    return [r.get("old_value") for r in results if rule_id is None or r["rule_id"] == rule_id]


def test_culture_collection_checks_every_value():
    rec = _rec("S1", {"culture_collection": ["JCM:1234", "JCM1234", "ZZZNOTREGISTERED:1"]})
    out = CultureCollectionValidator().validate(_sub(rec), _ctx())
    assert _found(out, "BS_R0113") == ["JCM1234"]                 # 2 つ目の形式誤り
    assert _found(out, "BS_R0114") == ["ZZZNOTREGISTERED:1"]      # 3 つ目の未登録機関コード


def test_specimen_voucher_checks_every_value():
    rec = _rec("S1", {"specimen_voucher": ["NSMT:12", "NSMT::12"]})
    out = SpecimenVoucherValidator().validate(_sub(rec), _ctx())
    assert _found(out, "BS_R0116") == ["NSMT::12"]


def test_specimen_voucher_for_bacteria_reports_every_value():
    rec = _rec("S1", {"specimen_voucher": ["A:1", "B:2"]}, organism="Bacillus subtilis")
    ctx = _ctx(tax_data={"Bacillus subtilis": {"status": "valid", "lineage": "cellular organisms; Bacteria; Bacillota"}})
    out = BS_R0115().validate(_sub(rec), ctx)
    assert _found(out) == ["A:1", "B:2"]


def test_voucher_same_institution_uses_every_value():
    # culture_collection の 2 つ目と specimen_voucher が同じ機関コード → R0062
    rec = _rec("S1", {"culture_collection": ["JCM:1", "NBRC:2"], "specimen_voucher": ["NBRC:9"]})
    out = BS_R0062().validate(_sub(rec), _ctx())
    assert len(out) == 1 and "'NBRC'" in out[0]["message"]
    # 同じ属性の多値どうし（JCM:1 と JCM:2）は対象外
    rec2 = _rec("S2", {"culture_collection": ["JCM:1", "JCM:2"]})
    assert BS_R0062().validate(_sub(rec2), _ctx()) == []


def test_locus_tag_prefix_format_checks_every_value():
    rec = _rec("S1", {"locus_tag_prefix": ["ABC", "1BAD"]})
    assert _found(BS_R0099().validate(_sub(rec), _ctx())) == ["1BAD"]


def test_locus_tag_prefix_duplicate_uses_every_value():
    a = _rec("S1", {"locus_tag_prefix": ["ABC", "DUP"]})
    b = _rec("S2", {"locus_tag_prefix": ["DUP"]})
    out = BS_R0102().validate(_sub(a, b), _ctx())
    assert sorted(r["sample"] for r in out) == ["S1", "S2"]
    # 同一サンプル内で同じ値を 2 回書いても重複（報告は 1 件）
    c = _rec("S3", {"locus_tag_prefix": ["XYZ", "XYZ"]})
    assert len(BS_R0102().validate(_sub(c), _ctx())) == 1


def test_locus_tag_prefix_registered_uses_every_value():
    rec = _rec("S1", {"locus_tag_prefix": ["NEWONE", "TAKEN"]})
    ctx = _ctx(registered_locus_tag_prefixes={"TAKEN": ["SSUB999999"]})
    out = BS_R0091().validate(_sub(rec), ctx)
    assert len(out) == 1 and "'TAKEN'" in out[0]["message"]


def test_locus_tag_prefix_presence_rules_see_every_value():
    rec = _rec("S1", {"locus_tag_prefix": ["", "ABC"]}, package="MIGS.ba")
    assert BS_R0109().validate(_sub(rec), _ctx()) == []           # 2 つ目に値があれば「無い」ではない
    out = BS_R0128().validate(_sub(rec), _ctx())                  # bioproject_id 無し
    assert len(out) == 1 and "ABC" in str(out[0])


def test_metagenome_source_and_component_organism_check_every_value():
    ctx = _ctx(tax_data={
        "soil metagenome": {"status": "valid", "scientific_name": "soil metagenome"},
        "escherichia coli": {"status": "fixable", "type": "case correction", "scientific_name": "Escherichia coli"},
    })
    rec = _rec("S1", {"metagenome_source": ["soil metagenome", "not a metagenome"],
                      "component_organism": ["Escherichia coli", "escherichia coli"]})
    assert "not a metagenome" in str(BS_R0106().validate(_sub(rec), ctx))
    assert _found(BS_R0105().validate(_sub(rec), ctx)) == ["escherichia coli"]


def test_virus_enrich_appr_cv_checks_every_value():
    rec = _rec("S1", {"virus_enrich_appr": ["filtration", "magic"]})
    assert _found(BS_R0138().validate(_sub(rec), _ctx())) == ["magic"]


# --- cancel 済み sample の除外（R0091 / R0102、2026-10-04） ---

def test_r0102_ignores_cancelled_samples_in_the_submission():
    a = _rec("S1", {"locus_tag_prefix": ["DUP"]})
    b = _rec("S2", {"locus_tag_prefix": ["DUP"]}, accession="SAMD00000002")
    assert len(BS_R0102().validate(_sub(a, b), _ctx())) == 2
    # S2 が cancel 済み（accession で照合）→ 重複にならない
    assert BS_R0102().validate(_sub(a, b), _ctx(cancelled_samples={"SAMD00000002"})) == []
    # sample_name でも照合する
    assert BS_R0102().validate(_sub(a, b), _ctx(cancelled_samples={"S1"})) == []


def test_r0091_ignores_cancelled_samples_in_the_submission():
    rec = _rec("S1", {"locus_tag_prefix": ["TAKEN"]})
    ctx = _ctx(registered_locus_tag_prefixes={"TAKEN": ["SSUB999999"]})
    assert len(BS_R0091().validate(_sub(rec), ctx)) == 1
    ctx.cancelled_samples = {"S1"}
    assert BS_R0091().validate(_sub(rec), ctx) == []


def test_registered_prefix_sql_excludes_cancelled_status():
    from apps.biosample import db_meta
    calls = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, q, params=None): calls.append((q, params))
        def fetchall(self): return [("SSUB000001", "ABC"), ("SSUB000001", "S1")]

    conn = SimpleNamespace(cursor=lambda: Cur())
    db_meta.fetch_registered_locus_tag_prefixes(conn)
    assert calls[-1][1] == (db_meta.CANCELLED_STATUS_IDS,) and 5700 in db_meta.CANCELLED_STATUS_IDS
    assert db_meta.fetch_cancelled_samples(conn, "SSUB000001") == {"SSUB000001", "ABC", "S1"}
    assert calls[-1][1] == ("SSUB000001", db_meta.CANCELLED_STATUS_IDS)
    assert db_meta.fetch_cancelled_samples(conn, None) == set()


def test_cli_fetches_cancelled_samples_for_the_submission(monkeypatch):
    from apps.biosample import cli, db_meta
    import common.db_manager as dbm
    monkeypatch.setattr(dbm.DatabaseManager, "get_bs_conn", lambda self: object())
    monkeypatch.setattr(db_meta, "fetch_registered_locus_tag_prefixes", lambda c: {"X": {"SSUB1"}})
    monkeypatch.setattr(db_meta, "fetch_cancelled_samples", lambda c, s: {f"{s}:S1"})
    ctx = _ctx()
    cli._fetch_registered_prefixes(ctx, SimpleNamespace(submission_id="SSUB000047"))
    assert ctx.cancelled_samples == {"SSUB000047:S1"}
