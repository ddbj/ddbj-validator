"""MB_IR0040 / MB_IR0041（参照オブジェクトのアカウント整合）のユニットテスト。

これらは requires_rdb ＋ requires_auth のため E2E ハーネス（-l 実行）では常にスキップされる。
DB を張らずに挙動を固定するため、account 集合を注入したコンテキストで直接検証する。
実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import pytest

from apps.metabobank.context import ValidationContext
from apps.metabobank.rules.reference_db import MB_IR0040, MB_IR0041
from apps.metabobank.validator import Validator
from common.magetab.model import Idf, Sdrf, Submission


def _sub(bioprojects=(), biosamples=()):
    """IDF Comment[BioProject] と SDRF Comment[BioSample] だけを持つ最小の Submission。"""
    idf = Idf()
    idf.fields = {"Comment[BioProject]": list(bioprojects)}
    idf.field_order = ["Comment[BioProject]"]
    sdrf = Sdrf(header=["Comment[BioSample]"], rows=[[s] for s in biosamples])
    return Submission(idf=idf, sdrf=sdrf)


def _ctx(**kw):
    return ValidationContext(skip_db=False, skip_ncbi=True, skip_auth=False, **kw)


# --- MB_IR0040（BioProject）------------------------------------------------

def test_ir0040_flags_bioproject_outside_account():
    """account が所有しない PRJDB は error になる。"""
    res = MB_IR0040().validate(_sub(bioprojects=["PRJDB0001", "PRJDB0002"]),
                               _ctx(account_bioprojects={"PRJDB0001"}))
    assert [r["rule_id"] for r in res] == ["MB_IR0040"]
    assert "PRJDB0002" in res[0]["message"]
    assert res[0]["level"] == "error" and res[0]["target"] == "IDF"


def test_ir0040_passes_when_owned():
    """account 所有なら発火しない。"""
    assert MB_IR0040().validate(_sub(bioprojects=["PRJDB0001"]),
                                _ctx(account_bioprojects={"PRJDB0001"})) == []


def test_ir0040_case_insensitive():
    """大小文字を無視して比較する。"""
    assert MB_IR0040().validate(_sub(bioprojects=["prjdb0001"]),
                                _ctx(account_bioprojects={"PRJDB0001"})) == []


def test_ir0040_checks_psub_too():
    """PSUB（BioProject 投稿 ID）も検査対象。"""
    res = MB_IR0040().validate(_sub(bioprojects=["PSUB000123"]), _ctx(account_bioprojects=set()))
    assert len(res) == 1 and "PSUB000123" in res[0]["message"]


def test_ir0040_ignores_non_ddbj_accessions():
    """他機関の BioProject（PRJNA/PRJEB）は DDBJ アカウントの所有判定対象外。"""
    assert MB_IR0040().validate(_sub(bioprojects=["PRJNA12345"]), _ctx(account_bioprojects=set())) == []


def test_ir0040_skips_when_set_unavailable():
    """DB 取得に失敗（None）した場合に全参照を error にしてしまわないこと。"""
    assert MB_IR0040().validate(_sub(bioprojects=["PRJDB0002"]), _ctx(account_bioprojects=None)) == []


# --- MB_IR0041（BioSample）------------------------------------------------

def test_ir0041_flags_biosample_outside_account():
    """account が所有しない SAMD は error になる。参照は SDRF 側にある。"""
    res = MB_IR0041().validate(_sub(biosamples=["SAMD00000001", "SAMD00000002"]),
                               _ctx(account_biosamples={"SAMD00000001"}))
    assert [r["rule_id"] for r in res] == ["MB_IR0041"]
    assert "SAMD00000002" in res[0]["message"]
    assert res[0]["level"] == "error" and res[0]["target"] == "SDRF"


def test_ir0041_passes_when_owned():
    """account 所有なら発火しない。"""
    assert MB_IR0041().validate(_sub(biosamples=["SAMD00000001"]),
                                _ctx(account_biosamples={"SAMD00000001"})) == []


def test_ir0041_ignores_non_samd():
    """SAMD 以外（SAMN 等）は対象外。"""
    assert MB_IR0041().validate(_sub(biosamples=["SAMN00000001"]), _ctx(account_biosamples=set())) == []


def test_ir0041_skips_when_set_unavailable():
    """DB 取得に失敗（None）した場合はスキップ。"""
    assert MB_IR0041().validate(_sub(biosamples=["SAMD00000002"]), _ctx(account_biosamples=None)) == []


def test_ir0041_aggregates_duplicate_rows():
    """同じ SAMD が複数行にあっても 1 件に集約される。"""
    res = MB_IR0041().validate(_sub(biosamples=["SAMD00000002"] * 5), _ctx(account_biosamples=set()))
    assert len(res) == 1


# --- モード別スキップ -------------------------------------------------------

@pytest.mark.parametrize("kw, registered", [
    ({}, True),                                                        # 全モード: 登録される
    ({"skip_db": True, "skip_ncbi": True, "skip_auth": True}, False),  # -l: 除外
    ({"skip_auth": True}, False),                                      # account 未指定: 除外
    ({"skip_db": True}, False),                                        # DB 無し: 除外
])
def test_mode_gating(kw, registered):
    """requires_rdb / requires_auth によるモード別の登録・除外。"""
    ids = {r.rule_id for r in Validator(ValidationContext(**kw)).active_rules}
    assert ("MB_IR0040" in ids) is registered
    assert ("MB_IR0041" in ids) is registered
