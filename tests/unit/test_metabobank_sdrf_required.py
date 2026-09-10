"""MB_SR0009（必須列の値の欠落）の対象範囲テスト。

MB_SR0004 が列の「存在」を見るのに対し、MB_SR0009 は同じ `required_columns_error` の
「値」を見る。両者で対象集合がずれると、列はあるのに全行空という状態が誰にも拾われない。
submission type ごとの除外（MSI の Extract Name）と、Protocol REF を MB_SR0033 に
委ねている境界をここで固定する。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit/test_metabobank_sdrf_required.py`
"""
import pytest

from apps.metabobank.context import ValidationContext
from apps.metabobank.model import Idf, MbSubmission as Submission
from apps.metabobank.rules import sdrf as S
from common.magetab.model import Sdrf

CTX = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)

_COLS = ["Source Name", "Sample Name", "Extract Name", "Assay Name",
         "Characteristics[organism]", "Characteristics[taxonomy_id]", "Protocol REF"]
_FILLED = {"Source Name": "s1", "Sample Name": "sm1", "Extract Name": "ex1",
           "Assay Name": "as1", "Characteristics[organism]": "Homo sapiens",
           "Characteristics[taxonomy_id]": "9606", "Protocol REF": "P1"}


def _sub(submission_type="LC-MS", overrides=None, extra_cols=(), rows=1):
    """必須列が全部埋まった最小 SDRF を作り、overrides で個別の値を差し替える。"""
    ov = overrides or {}
    header = list(_COLS) + list(extra_cols)
    body = []
    for _ in range(rows):
        body.append([ov.get(c, _FILLED.get(c, "v")) for c in header])
    idf = Idf(fields={"Comment[Submission type]": [submission_type]},
              field_order=["Comment[Submission type]"])
    return Submission(idf=idf, sdrf=Sdrf(header=header, rows=body))


def _msgs(sub):
    return [r["message"] for r in S.MB_SR0009().validate(sub, CTX)]


def test_all_filled_is_silent():
    assert _msgs(_sub()) == []


@pytest.mark.parametrize("col", ["Source Name", "Sample Name", "Extract Name", "Assay Name",
                                 "Characteristics[organism]", "Characteristics[taxonomy_id]"])
def test_empty_value_in_a_required_column_is_an_error(col):
    """必須列の値が空ならエラー（列の存在だけでなく値も見る）。"""
    msgs = _msgs(_sub(overrides={col: ""}))
    assert len(msgs) == 1 and col in msgs[0]


@pytest.mark.parametrize("col", ["Source Name", "Sample Name", "Extract Name", "Assay Name"])
def test_null_value_in_a_required_column_is_an_error(col):
    """null value（missing 等）も値なし扱い。"""
    msgs = _msgs(_sub(overrides={col: "missing"}))
    assert len(msgs) == 1 and col in msgs[0]


def test_extract_name_is_excluded_for_msi():
    """MSI は抽出工程が無く Extract Name 列自体が無いので対象外（MB_SR0004 と同じ除外）。"""
    assert _msgs(_sub(submission_type="MSI", overrides={"Extract Name": ""})) == []


def test_extract_name_is_checked_for_non_msi():
    """MSI 以外では Extract Name の値を見る。"""
    msgs = _msgs(_sub(submission_type="FIA-MS", overrides={"Extract Name": ""}))
    assert len(msgs) == 1 and "Extract Name" in msgs[0]


def test_protocol_ref_is_left_to_sr0033():
    """Protocol REF の値欠落は MB_SR0033 の担当。MB_SR0009 では二重報告しない。"""
    sub = _sub(overrides={"Protocol REF": ""})
    assert _msgs(sub) == []
    assert [r["rule_id"] for r in S.MB_SR0033().validate(sub, CTX)] == ["MB_SR0033"]


def test_missing_column_is_left_to_sr0004():
    """列そのものが無い場合は MB_SR0004 の担当（MB_SR0009 は黙る）。"""
    sub = _sub()
    i = sub.sdrf.header.index("Sample Name")
    sub.sdrf.header.pop(i)
    for row in sub.sdrf.rows:
        row.pop(i)
    assert _msgs(sub) == []
    assert len(S.MB_SR0004().validate(sub, CTX)) == 1


def test_duplicated_column_needs_all_copies_empty():
    """同名列が複数あるときは、その行の同名列が全部空のときだけ欠落とみなす。

    実データでは Raw Data File / Processed Data File が 1 行に複数列あるのが普通で、
    片方だけ空を欠落と判定すると大量の誤検知になる。
    """
    sub = _sub(extra_cols=["Sample Name"])          # Sample Name を 2 列にする
    sub.sdrf.rows[0][-1] = ""                        # 2 列目だけ空
    assert _msgs(sub) == []
    for row in sub.sdrf.rows:                        # 両方空にすると発火
        row[sub.sdrf.header.index("Sample Name")] = ""
    msgs = _msgs(sub)
    assert len(msgs) == 1 and "Sample Name" in msgs[0]


def test_one_finding_per_column_not_per_row():
    """同じ列で複数行が空でも、報告は列ごとに 1 件（最初の該当行）に留める。"""
    sub = _sub(overrides={"Sample Name": ""}, rows=5)
    msgs = _msgs(sub)
    assert len(msgs) == 1 and "row 1" in msgs[0]


# --- required_value_error: 列があるなら値は必須（Raw Data File） -------------

def test_raw_data_file_value_is_required_when_the_column_exists():
    """Raw Data File 列があるのに値が無ければエラー。"""
    sub = _sub(extra_cols=["Raw Data File"], overrides={"Raw Data File": ""})
    msgs = _msgs(sub)
    assert len(msgs) == 1 and "Raw Data File" in msgs[0]


def test_raw_data_file_null_value_is_required_too():
    sub = _sub(extra_cols=["Raw Data File"], overrides={"Raw Data File": "missing"})
    assert len(_msgs(sub)) == 1


def test_absent_raw_data_file_column_is_not_an_sr0009_error():
    """列そのものが無いのは MB_SR0005（推奨列の warning）の担当。

    raw を持たない投稿は Raw Data File 列を書かないのが正規の書き方になる。
    """
    sub = _sub()                                   # Raw Data File 列なし
    assert _msgs(sub) == []
    assert len(S.MB_SR0005().validate(sub, CTX)) == 1


def test_raw_data_file_filled_in_any_duplicate_column_is_ok():
    """Raw Data File が 2 列あり片方でも埋まっていれば無指摘（実データで 70 study の形）。"""
    sub = _sub(extra_cols=["Raw Data File", "Raw Data File"])
    sub.sdrf.rows[0][-1] = ""                      # 2 列目だけ空
    assert _msgs(sub) == []


def test_sr0009_is_internal_ignore():
    """MB_SR0009 は ignore error（管理システムは無視、登録者には表示）。

    raw なしの既存 study は管理システム側では止まらず、新規登録は手動サルベージで対応する。
    """
    from apps.metabobank.rules.base import is_internal_ignore
    assert is_internal_ignore("MB_SR0009")
