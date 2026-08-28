"""DDBJ Record を「どの DB として検証するか」の決め方と、担当外の扱いを固定する。

DDBJ Record は 1 ドキュメントに project と samples を同居させられる。登録は DB ごとに
行い、BioProject として登録するときに読まれるのは project、BioSample として登録する
ときは samples だけなので、reader は自分の担当だけを読む（2026-08-28 の方針決定）。
CLI はサブコマンドが担当を決めるが、web api はロールが `ddbj_record` の 1 つしか無いので
`record_db` で指定してもらい、無ければ top-level から推測する。

**担当外を読まないことは、担当外について黙ることではない。** 読まなかったことは
レポートに出るし、担当外のスキーマ違反も（validity は動かさずに）報告される。
ここのテストはそのどちらもスキーマパッケージ無しで通るように書いてある。
`[record]` extra が入っていない環境（`deploy/Containerfile.web` は `.[web]` しか
入れない）で黙って skip すると、この commit の主張が誰にも確かめられなくなる。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit`
"""
import json

import pytest

from apps.bioproject import record_reader as bp_reader
from apps.biosample import record_reader as bs_reader
from apps.biosample import reporter as bs_reporter
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
    # `{"project": {}}` は「project 無し」ではない。truthy で見ると reader（空の project を
    # 読む）と web api（断る）で答えが割れる。
    ({"project": {}}, "bioproject"),
])
def test_sniffs_db_from_top_level(tmp_path, record, expected):
    args = runner._plan_record(_write(tmp_path, record), {})
    assert args[0] == expected


def test_refuses_to_guess_when_both_present(tmp_path):
    path = _write(tmp_path, {"project": _PROJECT, "samples": _SAMPLES})
    # 「推測できない」であって「project も samples も無い」ではない。match を
    # "record_db" にすると両方の ValueError が通ってしまい、どちらが出たか固定できない。
    with pytest.raises(ValueError, match="同居する DDBJ Record"):
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
def test_rejects_unknown_record_db(db):
    with pytest.raises(ValueError, match="record_db に指定できるのは"):
        runner.normalise_record_db(db)


@pytest.mark.parametrize("value, expected", [
    ("BIOPROJECT ", "bioproject"), (" BioProject", "bioproject"),
    ("", None), (None, None), ("   ", None),
])
def test_record_db_is_normalised(value, expected):
    """大文字・前後空白は正規化して受ける。空は「未指定」として推測に落とす。"""
    assert runner.normalise_record_db(value) == expected


def test_plan_routes_the_ddbj_record_role(tmp_path):
    """private な _plan_record ではなく plan() 経由。role -> validator の対応が
    切れても _plan_record のテストは緑のままなので、入口から 1 本通しておく。"""
    path = _write(tmp_path, {"samples": _SAMPLES})
    assert runner.plan({"ddbj_record": path},
                       {"record_db": "biosample", "submission_id": "SSUB000001"}) == \
        ["biosample", "-r", str(path), "-s", "SSUB000001"]


@pytest.mark.parametrize("db, submission_id, bad", [
    ("bioproject", "SSUB000001", True),
    ("biosample",  "PSUB000001", True),
    ("bioproject", "PSUB000001", False),
    ("biosample",  "SSUB000001", False),
    # 体系の分からない id には何も言わない（正しい入力を拒む側へ倒れない）。
    ("bioproject", "PRJDB0001",  False),
    ("bioproject", None,         False),
    (None,         "SSUB000001", False),
])
def test_submission_id_prefix_must_match_record_db(db, submission_id, bad):
    """同じ record を DB ごとに 2 回投げるので、片方の id を付けたままにする間違いが
    起きる。BP_R0004 / BS_R0091 の自己除外が黙って効かなくなる。"""
    assert bool(runner.submission_id_mismatch(db, submission_id)) is bad


# --- reader は自分の担当だけを読む ---------------------------------------

def test_bioproject_reader_ignores_samples(tmp_path):
    path = _write(tmp_path, {"project": _PROJECT, "samples": _SAMPLES})
    submission, _ = bp_reader.parse_record(str(path))
    assert [r.title for r in submission.records] == [_PROJECT["title"]]


def test_biosample_reader_ignores_project(tmp_path):
    path = _write(tmp_path, {"project": _PROJECT, "samples": _SAMPLES})
    submission, _ = bs_reader.parse_record(str(path))
    assert [r.sample_name for r in submission.records] == ["S1"]


@pytest.mark.parametrize("reader, record, rule_id", [
    (bp_reader, {"project": _PROJECT, "samples": _SAMPLES}, "BP_R0002"),
    (bs_reader, {"project": _PROJECT, "samples": _SAMPLES}, "BS_R0098"),
])
def test_skipped_half_is_reported_not_just_logged(tmp_path, reader, record, rule_id):
    """stderr は validation.log にしか残らず、それを取れる API が無い（`get_file` の
    filetype は `^[a-z][a-z_]*$`）。レポートに出さないと、web の呼び出し側からは
    「指摘ゼロの綺麗なレポート」と区別が付かない。"""
    _, errors = reader.parse_record(str(_write(tmp_path, record)))
    skipped = [e for e in errors if e["target"] == "#not_validated"]
    assert [(e["rule_id"], e["level"]) for e in skipped] == [(rule_id, "info")]


def test_biosample_skip_notice_has_its_own_wording():
    """BS はレポートの message を reporter が公式文言で差し替えるので、reader の
    message は表示に出ない。target ごとの文言が引けることまで確かめる。"""
    message = bs_reporter._message({"rule_id": "BS_R0098", "input_format": "record",
                                    "target": "#not_validated", "message": "ignored"})
    assert "not validated here" in message
    assert message != bs_reporter._message({"rule_id": "BS_R0098", "input_format": "record",
                                            "target": "#file_format", "message": "ignored"})


def test_no_skip_notice_when_the_other_half_is_absent(tmp_path):
    _, errors = bp_reader.parse_record(str(_write(tmp_path, {"project": _PROJECT})))
    assert [e for e in errors if e["target"] == "#not_validated"] == []


# --- 担当外のスキーマ違反は validity を動かさない -------------------------

_PYDANTIC_ERR = [
    {"loc": ("project", "title"), "msg": "Input should be a valid string"},
    {"loc": ("samples", 0, "attributes"), "msg": "Input should be a valid list"},
]


def test_bioproject_demotes_schema_violations_in_samples():
    """v3 モデルは extra='forbid' なので、samples 側の独自キー 1 つで document 全体が
    invalid になる。error にすると BioProject の curator が直せない瑕疵で
    BioProject の validity が false になる。"""
    out = {(e["level"], e["target"]) for e in bp_reader._scoped_schema_errors(_PYDANTIC_ERR)}
    assert out == {("error", "#file_format"), ("warning", "#out_of_scope")}


def test_biosample_demotes_schema_violations_in_project():
    out = {(e["level"], e["target"]) for e in bs_reader._scoped_schema_errors(_PYDANTIC_ERR)}
    assert out == {("error", "#file_format"), ("warning", "#out_of_scope")}


def test_cap_is_applied_per_half():
    """pydantic はモデルのフィールド順に返し project は samples より先。まとめて 20 件で
    切ると、project 側の瑕疵 20 件で samples 側の本当の違反が 1 件も出ない。"""
    errors = ([{"loc": ("project", f"k{i}"), "msg": "Extra inputs are not permitted"}
               for i in range(bp_reader._SCHEMA_ERR_CAP + 5)] +
              [{"loc": ("samples", 0, "attributes"), "msg": "Input should be a valid list"}])
    out = bs_reader._scoped_schema_errors(errors)
    assert any("samples.0.attributes" in json.dumps(e, ensure_ascii=False) for e in out)


def test_truncation_says_it_truncated():
    errors = [{"loc": ("project", f"k{i}"), "msg": "Extra inputs are not permitted"}
              for i in range(bp_reader._SCHEMA_ERR_CAP + 5)]
    assert any("further violation" in json.dumps(e, ensure_ascii=False)
               for e in bp_reader._scoped_schema_errors(errors))


def test_bioproject_folds_the_field_path_into_the_message():
    """BioProject のレポートには注釈列の channel が無いので、message に入れないと
    フィールドのパスがどこにも出ない。`[record]` extra の有無に関係なく固定する。"""
    message = bp_reader._schema_error("samples.0.attributes", "Input should be a valid list")["message"]
    assert message.endswith("(samples.0.attributes: Input should be a valid list)")
