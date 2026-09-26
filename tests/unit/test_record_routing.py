"""DDBJ Record を「どの DB として検証するか」の決め方と、担当外の扱いを固定する。

DDBJ Record は 1 ドキュメントに projects と samples を同居させられる。登録は DB ごとに
行い、BioProject として登録するときに読まれるのは projects、BioSample として登録する
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

from apps.bioproject import cli as bp_cli
from apps.bioproject import record_reader as bp_reader
from apps.biosample import cli as bs_cli
from apps.biosample import record_reader as bs_reader
from apps.biosample import reporter as bs_reporter
from apps.webapi import runner

_PROJECTS = [{"title": "A project title long enough", "project_type": "primary"}]
_SAMPLES = [{"alias": "S1", "package": "Microbe.1.0", "attributes": []}]


def _write(tmp_path, record):
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


# --- web api の振り分け -------------------------------------------------

@pytest.mark.parametrize("record, expected", [
    ({"projects": _PROJECTS}, "bioproject"),
    ({"samples": _SAMPLES}, "biosample"),
    # list でない projects は「無い」ではない。無いとして断ると、BioProject の reader が
    # 形の違反として報告する機会が無くなる。
    ({"projects": {}}, "bioproject"),
    ({"projects": 0}, "bioproject"),
    ({"samples": ""}, "biosample"),
])
def test_sniffs_db_from_top_level(tmp_path, record, expected):
    args = runner._plan_record(_write(tmp_path, record), {})
    assert args[0] == expected


def test_refuses_to_guess_when_both_present(tmp_path):
    path = _write(tmp_path, {"projects": _PROJECTS, "samples": _SAMPLES})
    # 「推測できない」であって「projects も samples も無い」ではない。match を
    # "record_db" にすると両方の ValueError が通ってしまい、どちらが出たか固定できない。
    with pytest.raises(ValueError, match="同居する DDBJ Record"):
        runner._plan_record(path, {})


@pytest.mark.parametrize("record", [{}, {"samples": []}, {"projects": []}])
def test_rejects_record_with_neither(tmp_path, record):
    with pytest.raises(ValueError, match="projects も samples も"):
        runner._plan_record(_write(tmp_path, record), {})


@pytest.mark.parametrize("db", ["bioproject", "biosample"])
def test_record_db_decides_even_when_both_present(tmp_path, db):
    path = _write(tmp_path, {"projects": _PROJECTS, "samples": _SAMPLES})
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
    path = _write(tmp_path, {"projects": _PROJECTS, "samples": _SAMPLES})
    submission, _ = bp_reader.parse_record(str(path))
    assert [r.title for r in submission.records] == [_PROJECTS[0]["title"]]


def test_bioproject_takes_one_project_like_xml(tmp_path):
    """v3 の projects は list（SRA の study なども載る）だが、BioProject の登録は XML と
    同じく 1 つ。2 つ目以降も黙って捨てずに検証し、そのうえで BP_R0037 で断る。"""
    second = {"title": "Another project title long enough", "project_type": "umbrella"}
    path = _write(tmp_path, {"projects": [*_PROJECTS, second]})
    submission, errors = bp_reader.parse_record(str(path))
    assert [r.title for r in submission.records] == [_PROJECTS[0]["title"], second["title"]]
    assert [e["level"] for e in errors if e["rule_id"] == "BP_R0037"] == ["error"]
    # umbrella は 1 つ目でなくても「評価できなかった」と言う。
    assert [e["sample"] for e in errors if e["rule_id"] == "BP_R0016"] == [second["title"]]


def test_biosample_reader_ignores_project(tmp_path):
    path = _write(tmp_path, {"projects": _PROJECTS, "samples": _SAMPLES})
    submission, _ = bs_reader.parse_record(str(path))
    assert [r.sample_name for r in submission.records] == ["S1"]


@pytest.mark.parametrize("reader, record, rule_id", [
    (bp_reader, {"projects": _PROJECTS, "samples": _SAMPLES}, "BP_R0002"),
    (bs_reader, {"projects": _PROJECTS, "samples": _SAMPLES}, "BS_R0098"),
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


@pytest.mark.parametrize("cli, record", [
    (bp_cli, {"samples": _SAMPLES}),
    (bp_cli, {"projects": [], "samples": _SAMPLES}),
    (bs_cli, {"projects": _PROJECTS}),
    (bs_cli, {"projects": _PROJECTS, "samples": []}),
])
def test_nothing_to_validate_writes_no_report(tmp_path, cli, record):
    """担当が 0 件なら、担当外の info しか無くてもレポートを書かずに落とす。info は
    validity を動かさないので、書くと「検証して問題なし」のレポートになる。"""
    out  = tmp_path / "out"
    args = cli._build_parser().parse_args(["-r", str(_write(tmp_path, record)),
                                           "-l", "-j", "-o", str(out)])
    assert cli.run(args) == 2
    assert not out.exists() or not any(out.iterdir())


@pytest.mark.parametrize("cli, record", [
    (bp_cli, {"projects": [], "bogus": 1}),
    (bs_cli, {"samples": [], "bogus": 1}),
])
def test_nothing_to_validate_but_an_error_still_reports_it(tmp_path, cli, record):
    """担当 0 件でも、形式の違反は実際の指摘なので握りつぶさずレポートに残す。"""
    out  = tmp_path / "out"
    args = cli._build_parser().parse_args(["-r", str(_write(tmp_path, record)),
                                           "-l", "-j", "-o", str(out)])
    assert cli.run(args) == 1
    assert any(out.rglob("*.json"))


def test_no_skip_notice_when_the_other_half_is_absent(tmp_path):
    _, errors = bp_reader.parse_record(str(_write(tmp_path, {"projects": _PROJECTS})))
    assert [e for e in errors if e["target"] == "#not_validated"] == []


# --- 担当外のスキーマ違反は validity を動かさない -------------------------

_PYDANTIC_ERR = [
    {"loc": ("projects", 0, "title"), "msg": "Input should be a valid string"},
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
    """pydantic はモデルのフィールド順に返し projects は samples より先。まとめて 20 件で
    切ると、projects 側の瑕疵 20 件で samples 側の本当の違反が 1 件も出ない。"""
    errors = ([{"loc": ("projects", 0, f"k{i}"), "msg": "Extra inputs are not permitted"}
               for i in range(bp_reader._SCHEMA_ERR_CAP + 5)] +
              [{"loc": ("samples", 0, "attributes"), "msg": "Input should be a valid list"}])
    out = bs_reader._scoped_schema_errors(errors)
    assert any("samples.0.attributes" in json.dumps(e, ensure_ascii=False) for e in out)


def test_truncation_says_it_truncated():
    errors = [{"loc": ("projects", 0, f"k{i}"), "msg": "Extra inputs are not permitted"}
              for i in range(bp_reader._SCHEMA_ERR_CAP + 5)]
    assert any("further violation" in json.dumps(e, ensure_ascii=False)
               for e in bp_reader._scoped_schema_errors(errors))


def test_bioproject_folds_the_field_path_into_the_message():
    """BioProject のレポートには注釈列の channel が無いので、message に入れないと
    フィールドのパスがどこにも出ない。`[record]` extra の有無に関係なく固定する。"""
    message = bp_reader._schema_error("samples.0.attributes", "Input should be a valid list")["message"]
    assert message.endswith("(samples.0.attributes: Input should be a valid list)")
