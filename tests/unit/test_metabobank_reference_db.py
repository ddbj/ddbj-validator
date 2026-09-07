"""MB_IR0040 / MB_IR0041（参照オブジェクトのアカウント整合）のユニットテスト。

これらは requires_rdb ＋ requires_auth のため E2E ハーネス（-l 実行）では常にスキップされる。
DB / API を張らずに挙動を固定するため、citable 集合を注入したコンテキストで直接検証する。

判定材料は「引用できる（citable）ID の集合」で、record-api が使えれば
`?scope=citable`（permitted 込み・umbrella 除外）、無ければ内部 DB（所有 ∪ DRA permit）。
**集合が None のときは判定できないのでスキップする**（部分的な情報で誤検知を出さない）。

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
    """account が引用できない PRJDB は error になる。"""
    res = MB_IR0040().validate(_sub(bioprojects=["PRJDB0001", "PRJDB0002"]),
                               _ctx(account_bioprojects={"PRJDB0001"}))
    assert [r["rule_id"] for r in res] == ["MB_IR0040"]
    assert "PRJDB0002" in res[0]["message"]
    assert res[0]["level"] == "error" and res[0]["target"] == "IDF"


def test_ir0040_passes_when_owned():
    """引用できるなら発火しない。"""
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
    """判定材料が無い（None）ときに全参照を error にしてしまわないこと。

    DB / API の失敗、および一覧が上限で切れた場合がこれに当たる。"""
    assert MB_IR0040().validate(_sub(bioprojects=["PRJDB0002"]), _ctx(account_bioprojects=None)) == []


# --- MB_IR0041（BioSample）------------------------------------------------

def test_ir0041_flags_biosample_outside_account():
    """account が引用できない SAMD は error になる。参照は SDRF 側にある。"""
    res = MB_IR0041().validate(_sub(biosamples=["SAMD00000001", "SAMD00000002"]),
                               _ctx(account_biosamples={"SAMD00000001"}))
    assert [r["rule_id"] for r in res] == ["MB_IR0041"]
    assert "SAMD00000002" in res[0]["message"]
    assert res[0]["level"] == "error" and res[0]["target"] == "SDRF"


def test_ir0041_passes_when_owned():
    """引用できるなら発火しない。"""
    assert MB_IR0041().validate(_sub(biosamples=["SAMD00000001"]),
                                _ctx(account_biosamples={"SAMD00000001"})) == []


def test_ir0041_ignores_non_samd():
    """SAMD 以外（SAMN 等）は対象外。"""
    assert MB_IR0041().validate(_sub(biosamples=["SAMN00000001"]), _ctx(account_biosamples=set())) == []


def test_ir0041_skips_when_set_unavailable():
    """判定材料が無い（None）ときはスキップ。"""
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


# --- record-api クライアント（common/record_api）-------------------------

class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


@pytest.fixture
def api(monkeypatch):
    from common import record_api
    monkeypatch.setenv(record_api.BASE_URL_ENV, "https://record.example/")
    return record_api


def test_api_disabled_without_env(monkeypatch):
    from common import record_api
    monkeypatch.delenv(record_api.BASE_URL_ENV, raising=False)
    assert record_api.enabled() is False
    assert record_api.fetch_citable("acct", "bioproject") is None


def test_api_returns_citable_ids(api, monkeypatch):
    payload = {"truncated": False, "results": [{"id": "PRJDB1"}, {"id": "prjdb2"}]}
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp(payload))
    assert api.fetch_citable("acct", "bioproject") == {"PRJDB1", "PRJDB2"}


def test_api_uses_citable_scope(api, monkeypatch):
    """scope=citable で問い合わせること（permitted 込み・umbrella 除外は API 側の仕事）。"""
    seen = {}

    def fake_get(url, params=None, timeout=None):
        seen["url"], seen["params"] = url, params
        return _Resp({"truncated": False, "results": []})

    monkeypatch.setattr(api.requests, "get", fake_get)
    api.fetch_citable("acct", "biosample")
    assert seen["url"] == "https://record.example/api/account/acct/biosample"
    assert seen["params"]["scope"] == "citable"


def test_api_truncated_is_none(api, monkeypatch):
    """一覧が上限で切れたら None。部分的な一覧で「引用不可」と言うと誤検知になる
    （実例: account `ngdc` は SAMD 846,545 件）。"""
    payload = {"truncated": True, "results": [{"id": "SAMD00000001"}],
               "warnings": ["The result was truncated at 1 items (total 846545)."]}
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp(payload))
    assert api.fetch_citable("acct", "biosample") is None


def test_api_failure_is_none(api, monkeypatch):
    """API が落ちても validator は止めず、そのルールだけスキップする。"""
    def boom(*a, **k):
        raise ConnectionError("refused")
    monkeypatch.setattr(api.requests, "get", boom)
    assert api.fetch_citable("acct", "bioproject") is None


def test_api_unexpected_shape_is_none(api, monkeypatch):
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp({"results": "?"}))
    assert api.fetch_citable("acct", "bioproject") is None
