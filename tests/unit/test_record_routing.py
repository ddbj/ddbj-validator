"""DDBJ Record を「どの DB として検証するか」の決め方と、担当外の扱いを固定する。

DDBJ Record は 1 ドキュメントに projects と samples（と DRA の experiments / runs / analyses）を
同居させられる。登録は DB ごとに行い、BioProject として登録するときに読まれるのは projects、
BioSample として登録するときは samples、DRA は submission / experiments / runs / analyses
だけなので、reader は自分の担当だけを読む（2026-08-28 の方針決定）。
CLI はサブコマンドが担当を決めるが、web api はロールが `ddbj_record` の 1 つしか無いので
`record_db` で指定してもらい、無ければ top-level から推測する。

**担当外を読まないことは、担当外について黙ることではない。** 読まなかったことは
レポートに出るし、担当外のスキーマ違反も（validity は動かさずに）報告される。
ここのテストはそのどちらもスキーマパッケージ無しで通るように書いてある（Record のテストは
`ddbj-record` が入っていない環境では skip するが、ここは入っていなくても通る）。

実行: リポジトリルートで `.venv/bin/python -m pytest -m record tests/unit`
"""
import json

import pytest

from apps.bioproject import cli as bp_cli
from apps.bioproject import record_reader as bp_reader
from apps.biosample import cli as bs_cli
from apps.biosample import record_reader as bs_reader
from apps.biosample import reporter as bs_reporter
from apps.dra import cli as dra_cli
from apps.dra import record_reader as dra_reader
from apps.webapi import runner

# DDBJ Record 入力のテスト。既定では走らない（`pytest -m record`。README「DDBJ Record のテスト」）。
pytestmark = pytest.mark.record

_PROJECTS = [{"title": "A project title long enough", "project_type": "primary"}]
_SAMPLES = [{"alias": "S1", "package": "Microbe.1.0", "attributes": []}]
_EXPERIMENTS = [{"alias": "E1", "title": "An experiment"}]


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
    ({"experiments": _EXPERIMENTS}, "dra"),
    ({"runs": [{"alias": "R1"}]}, "dra"),
    ({"analyses": [{"alias": "A1"}], "submission": {"alias": "s"}}, "dra"),
])
def test_sniffs_db_from_top_level(tmp_path, record, expected):
    args = runner._plan_record(_write(tmp_path, record), {})
    assert args[0] == expected


@pytest.mark.parametrize("record", [
    {"projects": _PROJECTS, "samples": _SAMPLES},
    # SRA の STUDY から来た projects を持つ DRA の record。
    {"projects": _PROJECTS, "experiments": _EXPERIMENTS},
])
def test_refuses_to_guess_when_both_present(tmp_path, record):
    path = _write(tmp_path, record)
    # 「推測できない」であって「どれも無い」ではない。match を "record_db" にすると
    # 両方の ValueError が通ってしまい、どちらが出たか固定できない。
    with pytest.raises(ValueError, match="同居する DDBJ Record"):
        runner._plan_record(path, {})


@pytest.mark.parametrize("record", [
    {}, {"samples": []}, {"projects": []},
    # submission は他の DB の record にもあるので、それだけでは DRA と推測しない。
    {"submission": {"alias": "s"}},
])
def test_rejects_record_with_neither(tmp_path, record):
    with pytest.raises(ValueError, match="のどれもありません"):
        runner._plan_record(_write(tmp_path, record), {})


@pytest.mark.parametrize("db", ["bioproject", "biosample", "dra"])
def test_record_db_decides_even_when_both_present(tmp_path, db):
    path = _write(tmp_path, {"projects": _PROJECTS, "samples": _SAMPLES, "experiments": _EXPERIMENTS})
    assert runner._plan_record(path, {"record_db": db})[0] == db


def test_record_db_skips_the_parse_entirely(tmp_path):
    """指定があれば中身を読まない。10 万 sample の record を振り分けのためだけに
    web プロセスへ載せない、が `record_db` を足した理由の半分。"""
    assert runner._plan_record(tmp_path / "does-not-exist.json",
                               {"record_db": "biosample"})[0] == "biosample"


@pytest.mark.parametrize("db", ["gea", "project", "bio project"])
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


def test_submission_id_is_checked_against_the_sniffed_db_too(tmp_path):
    """`record_db` を省いたときは受付時に比べられないので、推測したあとで比べる。DRA では
    submission id から account も導くので、PSUB を渡すと別の account で権限系ルールが動く。"""
    path = _write(tmp_path, {"experiments": _EXPERIMENTS})
    with pytest.raises(ValueError, match="record_db は dra"):
        runner._plan_record(path, {"submission_id": "PSUB000001"})


def test_dra_xml_forwards_submission_id(tmp_path):
    saved = {"dra_submission": tmp_path / "sub.xml"}
    assert runner.plan(saved, {"submission_id": "amr_ddbj-0104"}) == \
        ["dra", "--sub", str(saved["dra_submission"]), "-s", "amr_ddbj-0104"]


@pytest.mark.parametrize("db, submission_id, bad", [
    ("bioproject", "SSUB000001", True),
    ("biosample",  "PSUB000001", True),
    ("bioproject", "PSUB000001", False),
    ("biosample",  "SSUB000001", False),
    # 体系の分からない id には何も言わない（正しい入力を拒む側へ倒れない）。
    ("bioproject", "PRJDB0001",  False),
    ("bioproject", None,         False),
    (None,         "SSUB000001", False),
    # DRA の id（account 名＋連番）に接頭辞は無い。PSUB / SSUB なら取り違え。
    ("dra",        "amr_ddbj-0104", False),
    ("dra",        "PSUB000001", True),
    ("dra",        "SSUB000001", True),
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


@pytest.mark.parametrize("ensure_ascii, reported", [(False, True), (True, False)])
def test_bioproject_non_ascii_is_what_the_file_writes_literally(tmp_path, ensure_ascii, reported):
    """BP_R0060 は XML では文字参照 (`&#x201c;`) を対象外にする。JSON の `\\u201c` はそれに当たるので、
    record でも素で書かれた非 ASCII だけを報告する。"""
    from apps.bioproject.rules.value import BP_R0060

    title = "A project title \u201clong\u201d enough"
    path  = tmp_path / "record.json"
    path.write_text(json.dumps({"projects": [{**_PROJECTS[0], "title": title}]}, ensure_ascii=ensure_ascii), encoding="utf-8")

    submission, _ = bp_reader.parse_record(str(path))

    assert bool(BP_R0060().validate(submission, None)) is reported


def test_biosample_reader_ignores_project(tmp_path):
    path = _write(tmp_path, {"projects": _PROJECTS, "samples": _SAMPLES})
    submission, _ = bs_reader.parse_record(str(path))
    assert [r.sample_name for r in submission.records] == ["S1"]


def test_dra_reader_ignores_projects_and_samples(tmp_path):
    path = _write(tmp_path, {"projects": _PROJECTS, "samples": _SAMPLES,
                             "submission": {"alias": "s"}, "experiments": _EXPERIMENTS})
    submission, _ = dra_reader.parse_record(str(path))
    assert [e.alias for e in submission.experiments] == ["E1"]


@pytest.mark.parametrize("reader, record, rule_id", [
    (bp_reader, {"projects": _PROJECTS, "samples": _SAMPLES}, "BP_R0002"),
    (bs_reader, {"projects": _PROJECTS, "samples": _SAMPLES}, "BS_R0098"),
    (dra_reader, {"projects": _PROJECTS, "samples": _SAMPLES,
                  "submission": {"alias": "s"}, "experiments": _EXPERIMENTS}, "DRA_R0002"),
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
    (dra_cli, {"projects": _PROJECTS, "samples": _SAMPLES}),
    # BioProject の record（submission も持つ）を DRA として渡した。submission だけでは数えない。
    (dra_cli, {"submission": {"alias": "PSUB000001"}, "projects": _PROJECTS}),
    (dra_cli, {"experiments": [], "runs": []}),
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
    (dra_cli, {"experiments": [], "bogus": 1}),
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


def test_dra_demotes_schema_violations_in_projects_samples_and_their_relations():
    """DRA は projects も samples も読まない。それらを source にする relation（SRA の
    STUDY_LINKS などから来る）も同じ。experiment を source にする relation の違反は DRA の側。"""
    record = {"relations": [{"source": {"type": "project"}}, {"source": {"type": "experiment"}}]}
    errors = [*_PYDANTIC_ERR,
              {"loc": ("relations", 0, "bogus"), "msg": "Extra inputs are not permitted"},
              {"loc": ("relations", 1, "bogus"), "msg": "Extra inputs are not permitted"},
              {"loc": ("experiments", 0, "bogus"), "msg": "Extra inputs are not permitted"}]
    out = dra_reader._scoped_schema_errors(errors, record)
    mine = [e for e in out if e["level"] == "error"]
    assert [e["message"].split("(")[-1] for e in mine] == [
        "relations.1.bogus: Extra inputs are not permitted)",
        "experiments.0.bogus: Extra inputs are not permitted)",
    ]
    assert [(e["level"], e["target"]) for e in out if e not in mine] == [("warning", "#out_of_scope")]


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
