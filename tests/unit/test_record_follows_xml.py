"""XML の元の要素を直接見るようになったルールが、DDBJ Record でも同じ範囲を見ること。

`dev` で「モデルではなく元の XML を走査する」形に変わったルールがある（非 ASCII の
BS_R0058 / BP_R0060 / DRA_R0050、全値を整える BP_R0059）。Record では、XML の文書に当たる
部分（BioProject なら submission と projects）を同じ関数で走査し、record の中の位置
（`projects.0.title`）で報告する。

実行: リポジトリルートで `.venv/bin/python -m pytest -m record tests/unit`
"""
import json

import pytest

from apps.bioproject import record_reader as bp_reader
from apps.bioproject.rules.content import BP_R0043
from apps.bioproject.rules.value import BP_R0060
from apps.biosample import record_reader as bs_reader
from apps.biosample.rules.value_ascii import BS_R0058
from apps.dra import record_reader as dra_reader
from apps.dra.rules.content import DRA_R0050
from apps.webapi import runner

# DDBJ Record 入力のテスト。既定では走らない（`pytest -m record`。README「DDBJ Record のテスト」）。
pytestmark = pytest.mark.record


def _write(tmp_path, record, ensure_ascii=False):
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record, ensure_ascii=ensure_ascii), encoding="utf-8")
    return str(path)


_SUBMITTERS = [{"first_name": "Hanako", "last_name": "三島", "email": "test1@ddbj.nig.ac.jp"}]


def test_bioproject_non_ascii_reaches_what_the_model_does_not_carry(tmp_path):
    """BP_R0060 は submission の連絡先も見る（XML の Submission/Description/Organization に当たる）。"""
    path = _write(tmp_path, {"submission": {"submitters": _SUBMITTERS},
                             "projects": [{"title": "A project title long enough", "project_type": "primary"}]})

    submission, _ = bp_reader.parse_record(path)

    assert [r["target"] for r in BP_R0060().validate(submission, None)] == ["submission.submitters.0.last_name"]


def test_bioproject_values_are_cleaned_before_the_model_is_built(tmp_path):
    """BP_R0059: XML と同じく、モデルを組む前に値をきれいにし、record の中の位置で報告する。
    XML の属性値に当たる識別子（accession など）は囲みクオートを外さない。"""
    path = _write(tmp_path, {"projects": [{"title": '"A  project title long enough"',
                                           "project_type": "primary",
                                           "organism": {"name": "Homo  sapiens", "taxonomy_id": '"9606"'}}]})

    submission, errors = bp_reader.parse_record(path)

    assert submission.records[0].title == "A project title long enough"
    assert submission.records[0].organism_name == "Homo sapiens"
    assert submission.records[0].tax_id == '"9606"'
    assert sorted(e["target"] for e in errors if e["rule_id"] == "BP_R0059") == ["projects.0.organism.name", "projects.0.title"]


def test_bioproject_grants_are_read(tmp_path):
    """BP_R0043: agency も title も無い grant。"""
    path = _write(tmp_path, {"projects": [{"title": "A project title long enough", "project_type": "primary",
                                           "grants": [{"id": "G1"}, {"id": "G2", "agency": "JSPS"}]}]})

    submission, _ = bp_reader.parse_record(path)

    assert [r["message"] for r in BP_R0043().validate(submission, None)] == \
        [f"{BP_R0043.description} (GrantId: G1)"]


@pytest.mark.parametrize("ensure_ascii, reported", [(False, True), (True, False)])
def test_biosample_non_ascii_on_the_submitter_is_reported_once(tmp_path, ensure_ascii, reported):
    """BS_R0058: XML では各 BioSample の Owner にある連絡先が、Record では sample の外の
    submission にある。1 回だけ、その位置で。`\\u` で書かれたものは文字参照と同じく対象外。"""
    samples = [{"alias": f"S{i}", "package": "Microbe.1.0", "attributes": []} for i in (1, 2)]
    path    = _write(tmp_path, {"submission": {"submitters": _SUBMITTERS}, "samples": samples}, ensure_ascii)

    submission, _ = bs_reader.parse_record(path)

    targets = [r["target"] for r in BS_R0058().validate(submission, None)]

    assert targets == (["submission.submitters.0.last_name"] if reported else [])


def test_biosample_non_ascii_in_a_sample_is_named_where_it_is(tmp_path):
    """XML の要素パスに当たるものは、record の中の位置。属性は属性として 1 回だけ。"""
    sample = {"alias": "S1", "package": "Microbe.1.0", "comments": ["鳥"],
              "attributes": [{"name": "strain", "value": "鳥"}]}
    path   = _write(tmp_path, {"samples": [sample]})

    submission, _ = bs_reader.parse_record(path)

    assert [r["target"] for r in BS_R0058().validate(submission, None)] == ["strain"]


def test_dra_non_ascii_is_named_where_it_is(tmp_path):
    """DRA_R0050: DRA として読む部分の全体を、record の中の位置で。"""
    path = _write(tmp_path, {"submission": {"alias": "sub1"},
                             "experiments": [{"alias": "E1", "title": "An “experiment”"}]})

    submission, _ = dra_reader.parse_record(path)

    assert [r["target"] for r in DRA_R0050().validate(submission, None)] == ["experiments.0.title"]


def test_web_api_passes_the_biosample_profile_for_a_record(tmp_path):
    """XML と同じく次期 BioSample の検証にする。profile は BioSample の CLI にしか無い。"""
    path = tmp_path / "record.json"

    assert runner._plan_record(path, {"record_db": "biosample", "profile": "next"})[-2:] == ["--profile", "next"]
    assert "--profile" not in runner._plan_record(path, {"record_db": "bioproject", "profile": "next"})
