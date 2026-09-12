"""MB_SR0049（Protocol REF 列が全行空）と MB_SR0050（Assay Name の重複）のテスト。

どちらも「空セルと null value（missing 等）を同じ『値が無い』として扱う」のが要点。
MB_SR0049 は列単位（行単位は MB_SR0033）、MB_SR0050 は値が無い行を対象外にする
（値が無いことは MB_SR0009 の担当で、空同士を重複と数えると二重報告になる）。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit/test_metabobank_protocol_assay.py`
"""
import pytest

from apps.metabobank.context import ValidationContext
from apps.metabobank.model import Idf, MbSubmission as Submission
from apps.metabobank.rules import sdrf as S
from apps.metabobank.rules.base import is_internal_ignore
from common.magetab.model import Sdrf

CTX = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)

# Protocol REF が 2 本並ぶ最小 SDRF（工程 2 つ）
_HEADER = ["Source Name", "Protocol REF", "Extract Name", "Protocol REF", "Assay Name"]


def _sub(rows):
    idf = Idf(fields={"Comment[Submission type]": ["LC-MS"]},
              field_order=["Comment[Submission type]"])
    return Submission(idf=idf, sdrf=Sdrf(header=list(_HEADER), rows=[list(r) for r in rows]))


def _sr0049(sub):
    return [r["message"] for r in S.MB_SR0049().validate(sub, CTX)]


def _sr0050(sub):
    return [r["message"] for r in S.MB_SR0050().validate(sub, CTX)]


# --- MB_SR0049: Protocol REF 列が全行空 -------------------------------------

def test_all_protocol_ref_columns_filled_is_silent():
    assert _sr0049(_sub([["s1", "P1", "e1", "P2", "a1"],
                         ["s2", "P1", "e2", "P2", "a2"]])) == []


def test_one_column_empty_in_every_row_is_an_error():
    """1 本だけ全行空。行単位の MB_SR0033 では拾えなかったケース。"""
    sub = _sub([["s1", "", "e1", "P2", "a1"],
                ["s2", "", "e2", "P2", "a2"]])
    msgs = _sr0049(sub)
    assert len(msgs) == 1 and "#1 of 2" in msgs[0]
    assert S.MB_SR0033().validate(sub, CTX) == []      # 行単位では無指摘のまま


def test_partially_empty_column_is_not_an_error():
    """部分的な空欄は対象外（行単位の欠落は MB_SR0033 の担当）。"""
    assert _sr0049(_sub([["s1", "P1", "e1", "P2", "a1"],
                         ["s2", "", "e2", "P2", "a2"]])) == []


@pytest.mark.parametrize("null_value", ["missing", "not applicable", "not collected",
                                        "not provided", "restricted access"])
def test_null_value_counts_as_absent(null_value):
    """null value は空と同じ「値が無い」扱い。"""
    msgs = _sr0049(_sub([["s1", null_value, "e1", "P2", "a1"],
                         ["s2", null_value, "e2", "P2", "a2"]]))
    assert len(msgs) == 1 and "#1 of 2" in msgs[0]


def test_mixed_empty_and_null_value_counts_as_absent():
    msgs = _sr0049(_sub([["s1", "", "e1", "P2", "a1"],
                         ["s2", "missing", "e2", "P2", "a2"]]))
    assert len(msgs) == 1


def test_every_empty_column_is_reported():
    msgs = _sr0049(_sub([["s1", "", "e1", "", "a1"],
                         ["s2", "", "e2", "", "a2"]]))
    assert len(msgs) == 2 and "#1 of 2" in msgs[0] and "#2 of 2" in msgs[1]


def test_short_rows_are_treated_as_absent():
    """列数が足りない行（末尾が欠けた SDRF）も値が無い扱い。"""
    assert len(_sr0049(_sub([["s1", "", "e1"], ["s2", "", "e2"]]))) == 2


def test_no_data_row_is_silent():
    """ヘッダだけの SDRF で「全行空」と判定しない。"""
    assert _sr0049(_sub([])) == []


def test_absent_protocol_ref_column_is_left_to_sr0004():
    idf = Idf(fields={"Comment[Submission type]": ["LC-MS"]},
              field_order=["Comment[Submission type]"])
    sub = Submission(idf=idf, sdrf=Sdrf(header=["Source Name", "Assay Name"],
                                        rows=[["s1", "a1"]]))
    assert _sr0049(sub) == []


def test_sr0049_is_error_and_internal_ignore():
    assert S.MB_SR0049.level == "error" and is_internal_ignore("MB_SR0049")


# --- MB_SR0050: Assay Name の重複 -------------------------------------------

def test_unique_assay_names_are_silent():
    assert _sr0050(_sub([["s1", "P1", "e1", "P2", "a1"],
                         ["s2", "P1", "e2", "P2", "a2"]])) == []


def test_duplicated_assay_name_is_an_error():
    msgs = _sr0050(_sub([["s1", "P1", "e1", "P2", "a1"],
                         ["s2", "P1", "e2", "P2", "a1"]]))
    assert len(msgs) == 1 and "'a1'" in msgs[0] and "rows 1, 2" in msgs[0]


def test_one_finding_per_duplicated_value():
    """同じ値が 3 行に現れても 1 件。別の重複値は別件。"""
    msgs = _sr0050(_sub([["s1", "P1", "e1", "P2", "a1"],
                         ["s2", "P1", "e2", "P2", "a1"],
                         ["s3", "P1", "e3", "P2", "a1"],
                         ["s4", "P1", "e4", "P2", "a2"],
                         ["s5", "P1", "e5", "P2", "a2"]]))
    assert len(msgs) == 2 and "rows 1, 2, 3" in msgs[0] and "rows 4, 5" in msgs[1]


def test_surrounding_spaces_are_ignored():
    msgs = _sr0050(_sub([["s1", "P1", "e1", "P2", " a1"],
                         ["s2", "P1", "e2", "P2", "a1 "]]))
    assert len(msgs) == 1


def test_case_difference_is_a_different_name():
    """大文字小文字は区別する（別表記は別の名前として通す）。"""
    assert _sr0050(_sub([["s1", "P1", "e1", "P2", "A1"],
                         ["s2", "P1", "e2", "P2", "a1"]])) == []


def test_empty_assay_names_are_not_duplicates():
    """値が無い行は対象外（MB_SR0009 の担当）。空同士を重複と数えない。"""
    assert _sr0050(_sub([["s1", "P1", "e1", "P2", ""],
                         ["s2", "P1", "e2", "P2", ""]])) == []


@pytest.mark.parametrize("null_value", ["missing", "not applicable", "not collected",
                                        "not provided", "restricted access"])
def test_null_value_assay_names_are_not_duplicates(null_value):
    """null value も「無い」扱い。null 同士を重複と数えない。"""
    assert _sr0050(_sub([["s1", "P1", "e1", "P2", null_value],
                         ["s2", "P1", "e2", "P2", null_value]])) == []


def test_null_value_and_real_name_are_not_duplicates():
    assert _sr0050(_sub([["s1", "P1", "e1", "P2", "missing"],
                         ["s2", "P1", "e2", "P2", "a1"]])) == []


def test_absent_assay_name_column_is_left_to_sr0004():
    idf = Idf(fields={"Comment[Submission type]": ["LC-MS"]},
              field_order=["Comment[Submission type]"])
    sub = Submission(idf=idf, sdrf=Sdrf(header=["Source Name", "Protocol REF"],
                                        rows=[["s1", "P1"], ["s1", "P1"]]))
    assert _sr0050(sub) == []


def test_sr0050_is_error_and_internal_ignore():
    assert S.MB_SR0050.level == "error" and is_internal_ignore("MB_SR0050")
