"""DDBJ Record を「どの DB として検証するか」の決め方を固定するユニットテスト。

DDBJ Record は 1 ドキュメントに project と samples を同居させられる。登録は DB ごとに
行い、BioProject として登録するときに読まれるのは project、BioSample として登録する
ときは samples だけなので、reader は自分の担当だけを読む（2026-08-28 の方針決定）。
CLI はサブコマンドが担当を決めるが、web api はロールが `ddbj_record` の 1 つしか無いので
`record_db` で指定してもらい、無ければ top-level から推測する。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit`
"""
import json

import pytest

from apps.bioproject import record_reader as bp_reader
from apps.biosample import record_reader as bs_reader
from apps.webapi import runner

_PROJECT = {"title": "A project title long enough", "project_type": "primary"}
_SAMPLES = [{"alias": "S1", "package": "Microbe.1.0", "attributes": []}]


def _write(tmp_path, record):
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


# --- web api の振り分け -------------------------------------------------

@pytest.mark.parametrize("record, expected", [
    ({"project": _PROJECT}, "bioproject"),
    ({"samples": _SAMPLES}, "biosample"),
    # `{"project": {}}` は「project 無し」ではない。bool() で見ると reader（空の project を
    # 読む）と web api（断る）で答えが割れる。
    ({"project": {}}, "bioproject"),
])
def test_sniffs_db_from_top_level(tmp_path, record, expected):
    args = runner._plan_record(_write(tmp_path, record), {})
    assert args[0] == expected


def test_refuses_to_guess_when_both_present(tmp_path):
    path = _write(tmp_path, {"project": _PROJECT, "samples": _SAMPLES})
    with pytest.raises(ValueError, match="record_db"):
        runner._plan_record(path, {})


@pytest.mark.parametrize("record", [{}, {"samples": []}])
def test_rejects_record_with_neither(tmp_path, record):
    with pytest.raises(ValueError, match="project も samples も"):
        runner._plan_record(_write(tmp_path, record), {})


@pytest.mark.parametrize("db", ["bioproject", "biosample"])
def test_record_db_decides_even_when_both_present(tmp_path, db):
    path = _write(tmp_path, {"project": _PROJECT, "samples": _SAMPLES})
    assert runner._plan_record(path, {"record_db": db})[0] == db


def test_record_db_skips_the_parse_entirely(tmp_path):
    """指定があれば中身を読まない。10 万 sample の record を振り分けのためだけに
    web プロセスへ載せない、が `record_db` を足した理由の半分。"""
    assert runner._plan_record(tmp_path / "does-not-exist.json",
                               {"record_db": "biosample"})[0] == "biosample"


@pytest.mark.parametrize("db", ["dra", "project", "bio project"])
def test_rejects_unknown_record_db(tmp_path, db):
    path = _write(tmp_path, {"project": _PROJECT})
    with pytest.raises(ValueError, match="record_db に指定できるのは"):
        runner._plan_record(path, {"record_db": db})


@pytest.mark.parametrize("db", ["BIOPROJECT ", " BioProject", ""])
def test_record_db_is_normalised(tmp_path, db):
    """大文字・前後空白は正規化して受ける。空は「未指定」として推測に落とす。"""
    path = _write(tmp_path, {"project": _PROJECT})
    assert runner._plan_record(path, {"record_db": db})[0] == "bioproject"


def test_submission_id_is_passed_through(tmp_path):
    path = _write(tmp_path, {"samples": _SAMPLES})
    assert runner._plan_record(path, {"record_db": "biosample",
                                      "submission_id": "SSUB000001"})[-2:] == ["-s", "SSUB000001"]


# --- reader は自分の担当だけを読む ---------------------------------------

def test_bioproject_reader_ignores_samples(tmp_path):
    path = _write(tmp_path, {"project": _PROJECT, "samples": _SAMPLES})
    submission, _ = bp_reader.parse_record(str(path))
    assert [r.title for r in submission.records] == [_PROJECT["title"]]


def test_biosample_reader_ignores_project(tmp_path):
    path = _write(tmp_path, {"project": _PROJECT, "samples": _SAMPLES})
    submission, _ = bs_reader.parse_record(str(path))
    assert [r.sample_name for r in submission.records] == ["S1"]


def test_schema_check_covers_the_whole_document(tmp_path):
    """担当外が壊れていても黙って通さない。読まないのと「読めるドキュメントである」の
    確認は別で、後者はドキュメント全体にかかる。"""
    pytest.importorskip("ddbj_record", reason="v3 スキーマ検証は [record] extra が要る")
    path = _write(tmp_path, {"project": _PROJECT, "samples": [{"alias": "S1", "attributes": {}}]})
    _, errors = bp_reader.parse_record(str(path))
    assert [e["rule_id"] for e in errors] == ["BP_R0002"]
    # どこが悪いかは message に畳み込む（BioProject のレポートには注釈列が無い）。
    assert "samples.0.attributes" in errors[0]["message"]
