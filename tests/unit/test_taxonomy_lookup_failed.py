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


def test_bs_r0096_is_internal_ignore():
    """表（docs/biosample/rules.txt）は ignore と書いているのに、コードは true error で
    登録を止めていた。2026-09-26 に表へ合わせた。"""
    from apps.biosample.rules.base import INTERNAL_IGNORE_RULE_IDS
    assert "BS_R0096" in INTERNAL_IGNORE_RULE_IDS


def test_biosample_ignore_set_matches_the_rule_table():
    """コードの internal ignore と rule 表の「Internal ignore」列が食い違わないこと。

    BS_R0096 のような取りこぼしが再発すると、表では「登録を止めない」と書いてあるルールが
    実際には止めてしまう（逆も同じ）。
    """
    from pathlib import Path
    from apps.biosample.validator import Validator
    from apps.biosample.context import ValidationContext
    table = {}
    for line in Path("docs/biosample/rules.txt").read_text().rstrip("\n").split("\n")[1:]:
        c = line.split("\t") + [""] * 12
        table[c[0]] = c[2]
    v = Validator(ValidationContext())
    mismatch = []
    for r in v.active_rules:
        want = table.get(r.rule_id)
        if want is None:
            continue                      # 表に無い rule は別問題（ここでは見ない）
        got = "ignore" if r.rule_id in v.ignore_ids else ""
        if want != got:
            mismatch.append(f"{r.rule_id}: 表={want!r} code={got!r}")
    assert not mismatch, mismatch


# --- DB の文字コードで表せない名前（2026-10-03、SSUB051896）---
# organism / host などに NBSP のような EUC_JP で表せない文字を含む名前が 1 つでもあると、
# IN 句全体のエンコードで例外になり、全 organism が lookup_failed になっていた。
# 正しく書かれた organism まで BS_R0045 の taxonomy_id 提案を失っていた（817 sample）。

class _FakeCursor:
    def __init__(self, rows, seen):
        self.rows, self.seen = rows, seen

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, query, params):
        self.seen.extend(params)
        for p in params:              # 実接続と同じく、送信前のエンコードで失敗させる
            p.encode("euc_jp")

    def fetchall(self):
        return self.rows


class _FakeConn:
    encoding = "EUC_JP"

    def __init__(self, rows):
        self.rows, self.seen = rows, []

    def cursor(self):
        return _FakeCursor(self.rows, self.seen)


_BSUB_ROW = ("Bacillus subtilis", "scientific name", "Bacillus subtilis", "species",
             11, 4, 11, 1423, "Bacteria; Bacillota", "BCT")


def test_unencodable_name_does_not_fail_the_whole_lookup():
    from common.db_taxonomy import fetch_taxonomy_data, lookup_failed_organisms
    conn = _FakeConn([_BSUB_ROW])
    tax = fetch_taxonomy_data(conn, ["Bacillus subtilis", "Homo sapiens"])
    assert tax["Bacillus subtilis"]["tax_id"] == 1423
    assert tax["Bacillus subtilis"]["status"] == "valid"
    # 表せない名前は DB に存在し得ないので not_found（取得失敗ではない）
    assert tax["Homo sapiens"]["status"] == "not_found"
    assert lookup_failed_organisms(tax) == set()
    assert "Homo sapiens".lower() not in conn.seen     # クエリには渡さない


def test_only_unencodable_names_skip_the_query():
    from common.db_taxonomy import fetch_taxonomy_data
    conn = _FakeConn([])
    tax = fetch_taxonomy_data(conn, ["Bacillus subtilis"])
    assert tax == {"Bacillus subtilis": {"status": "not_found", "is_species_or_below": False}}
    assert conn.seen == []


def test_bs_r0045_is_silent_when_the_lookup_failed():
    """取得失敗は BS_R0145 が報告する。BS_R0045 が「Taxonomy に無い」と言い切らないこと。"""
    from apps.biosample.rules.taxonomy import BS_R0045
    rec = _rec(org="Bacillus subtilis", taxid="")
    failed = SimpleNamespace(tax_data=mark_all_lookup_failed(["Bacillus subtilis"]), taxid_info={})
    assert BS_R0045().validate(_sub(rec), failed) == []

    notfound = SimpleNamespace(tax_data={"Bacillus subtilis": {"status": "not_found"}}, taxid_info={})
    res = BS_R0045().validate(_sub(rec), notfound)
    assert len(res) == 1 and "not found in the Taxonomy database" in res[0]["message"]
