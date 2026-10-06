"""DRA_R0041 / R0015 の account BioProject 集合（2026-10-06）。

古い DRA 登録は外部参照許可（ext_permit）に PRJDA / PRJNA で登録されている。
- record-api があれば `?scope=citable`（own ＋ permitted。PRJDA / PRJNA も入る）を使う。
- API が None（未設定 / 失敗 / truncated）なら直 SQL にフォールバックし、
  そちらでも ext_permit の PRJ* をそのまま許可として通す。
"""
from types import SimpleNamespace

from apps.dra import cli, db_meta
from apps.dra.context import ValidationContext
from apps.dra.rules.account import DRA_R0015
from common import record_api


def _try(label, fn):
    return fn()


_DM = SimpleNamespace(get_bp_conn=lambda: None)


def test_uses_record_api_citable_when_enabled(monkeypatch):
    monkeypatch.setenv(record_api.BASE_URL_ENV, "https://record.example/")
    monkeypatch.setattr(record_api, "fetch_citable",
                        lambda account, id_type: {"PRJDA43375", "PRJNA45951"} if id_type == "bioproject" else None)
    monkeypatch.setattr(db_meta, "fetch_account_bioprojects",
                        lambda *a: (_ for _ in ()).throw(AssertionError("SQL は呼ばない")))
    got = cli._fetch_account_bioprojects(_DM, None, "makokuro", {"PRJDA43375"}, _try)
    assert got == {"PRJDA43375", "PRJNA45951"}


def test_falls_back_to_sql_when_api_returns_none(monkeypatch):
    monkeypatch.setenv(record_api.BASE_URL_ENV, "https://record.example/")
    monkeypatch.setattr(record_api, "fetch_citable", lambda *a: None)
    monkeypatch.setattr(db_meta, "fetch_account_bioprojects", lambda *a: {"PRJDB1"})
    assert cli._fetch_account_bioprojects(_DM, None, "acct", {"PRJDB1"}, _try) == {"PRJDB1"}


def test_sql_only_when_api_disabled(monkeypatch):
    monkeypatch.delenv(record_api.BASE_URL_ENV, raising=False)
    monkeypatch.setattr(record_api, "fetch_citable",
                        lambda *a: (_ for _ in ()).throw(AssertionError("API は呼ばない")))
    monkeypatch.setattr(db_meta, "fetch_account_bioprojects", lambda *a: {"PRJDB2"})
    assert cli._fetch_account_bioprojects(_DM, None, "acct", set(), _try) == {"PRJDB2"}


def test_sql_permit_passes_prjda_and_prjna():
    # bp_conn 無し: PSUB の PRJDB 変換はできないが、PRJ* の許可はそのまま通る
    got = db_meta._psub_to_prjdb(None, {"PRJDA43375", "prjna45951", "PRJDB9", "PSUB000001"})
    assert got == {"PRJDA43375", "PRJNA45951", "PRJDB9"}


def test_r0015_passes_permitted_prjda():
    ctx = ValidationContext(account="makokuro", skip_db=False, skip_ncbi=True, skip_auth=False)
    ctx.account_bioprojects = {"PRJDA43375"}
    ana = SimpleNamespace(study_ref="PRJDA43375", label="makokuro-0006_Analysis_0001")
    sub = SimpleNamespace(analyses=[ana])
    assert DRA_R0015().validate(sub, ctx) == []
    ana.study_ref = "PRJDA99999"
    assert len(DRA_R0015().validate(sub, ctx)) == 1
