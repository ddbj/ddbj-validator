"""taxonomy の取得失敗を「Taxonomy に無い」と区別すること（2026-09-26）。

`-n`（NCBI API モード）で API が応答しないと、従来は取得失敗も `status="not_found"` に
なっていたため、
  - organism↔taxonomy_id の不一致が黙って通る（BS_R0004 の fail-open）
  - 実在する organism を「Taxonomy に無い」と誤報告する（ANN1020 / BS_R0045）
の 2 つが起きていた。実際に biosample の `-n` E2E で BS_R0004 の fail fixture が
1 件だけ素通りする事象が出た（2026-09-25）。

`lookup_failed` を付けて区別し、BS_R0145 が「検査できなかった」と報告する。
"""
from types import SimpleNamespace

from common.db_taxonomy import lookup_failed_organisms, mark_all_lookup_failed


def _rec(org="Arabidopsis thaliana", taxid="9606"):
    return SimpleNamespace(sample_id="S1", organism=org, taxonomy_id=taxid, package="Plant")


def _sub(rec=None):
    return SimpleNamespace(records=[rec or _rec()])


def test_lookup_failed_is_separate_from_not_found():
    failed = mark_all_lookup_failed(["A"])
    assert failed["A"]["status"] == "not_found"      # 既存の呼び出し側の挙動は変えない
    assert failed["A"]["lookup_failed"] is True
    assert lookup_failed_organisms(failed) == {"A"}
    # 本当に Taxonomy に無い場合は対象外
    assert lookup_failed_organisms({"A": {"status": "not_found"}}) == set()
    assert lookup_failed_organisms(None) == set()


def test_bs_r0145_reports_only_the_failed_lookup():
    from apps.biosample.rules.taxonomy import BS_R0145
    r = BS_R0145()
    fail = SimpleNamespace(tax_data=mark_all_lookup_failed(["Arabidopsis thaliana"]), taxid_info={})
    res = r.validate(_sub(), fail)
    assert len(res) == 1 and "Arabidopsis thaliana" in res[0]["message"]

    # 「Taxonomy に無い」は BS_R0045 の担当なのでここでは出さない
    notfound = SimpleNamespace(tax_data={"Arabidopsis thaliana": {"status": "not_found"}}, taxid_info={})
    assert r.validate(_sub(), notfound) == []
    assert r.validate(_sub(), SimpleNamespace(tax_data={}, taxid_info={})) == []


def test_bs_r0004_still_works_when_taxonomy_is_available():
    """取得できていれば従来どおり不一致を出す（BS_R0145 の追加で変わらないこと）。"""
    from apps.biosample.rules.taxonomy import BS_R0004
    ok = SimpleNamespace(tax_data={}, taxid_info={"9606": {"scientific_name": "Homo sapiens"}})
    assert len(BS_R0004().validate(_sub(), ok)) == 1


def test_ann1020_does_not_claim_absence_when_the_lookup_failed():
    """ddbj 側。取得失敗時は「Taxonomy に無い」と言い切らない文言にする。"""
    from apps.ddbj.rules.annotation import ANN1020

    class _Feat:
        type = "source"
        qualifiers = {"organism": ["Arabidopsis thaliana"]}
        line_number = 1

    class _Rec:
        id = "seq1"
        features = [_Feat()]
        features_by_type = {"source": [_Feat()]}

    recs = {"seq1": _Rec()}
    failed = SimpleNamespace(tax_data=mark_all_lookup_failed(["Arabidopsis thaliana"]))
    msg = ANN1020().validate_file(recs, failed)[0]["message"]
    assert "lookup failed" in msg and "not found in the Taxonomy database" not in msg

    notfound = SimpleNamespace(tax_data={"Arabidopsis thaliana": {"status": "not_found"}})
    msg2 = ANN1020().validate_file(recs, notfound)[0]["message"]
    assert "not found in the Taxonomy database" in msg2
