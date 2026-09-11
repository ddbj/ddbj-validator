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


# --- MB_SR0006 / MB_SR0007: ユーザ定義列の切り分け -------------------------
#
# 登録者が名前を決めてよいのは sdrf.user_defined_column_kinds の 5 種
# （Characteristics / Parameter Value / Comment / Unit / Factor Value）だけ。
# 既定列（submission type ごとの sdrf.column_order ＋ 必須/推奨列）との差分を
# MB_SR0006（warning）、それ以外の列名と無名 `Kind[]` を MB_SR0007（error/ignore）で受ける。

def _udc_sub(extra_cols):
    """LC-MS の最小 SDRF に列を足した submission を作る。"""
    header = ["Source Name", "Sample Name", "Characteristics[organism]",
              "Characteristics[taxonomy_id]"] + list(extra_cols)
    rows = [["s1", "s1", "Homo sapiens", "9606"] + ["v"] * len(extra_cols)]
    idf = Idf(fields={"Comment[Submission type]": ["LC-MS"]},
              field_order=["Comment[Submission type]"])
    return Submission(idf=idf, sdrf=Sdrf(header=header, rows=rows))


def test_default_columns_are_not_user_defined():
    """必須列だけの SDRF では MB_SR0006 / MB_SR0007 とも発火しない。"""
    sub = _udc_sub([])
    assert S.MB_SR0006().validate(sub, CTX) == []
    assert S.MB_SR0007().validate(sub, CTX) == []


def test_allowed_kind_beyond_default_is_sr0006():
    """許容種別で既定列に無い列は MB_SR0006（warning）。"""
    sub = _udc_sub(["Unit[my unit]", "Comment[my note]"])
    msgs = [r["message"] for r in S.MB_SR0006().validate(sub, CTX)]
    assert len(msgs) == 1
    assert "Unit[my unit]" in msgs[0] and "Comment[my note]" in msgs[0]
    assert S.MB_SR0007().validate(sub, CTX) == []


def test_characteristics_are_excluded_from_sr0006_warning():
    """Characteristics は MB_SR0006 の warning 対象外。

    登録者が自由に足すのが普通で全投稿で warning が出て煩く、内容の妥当性は
    BioSample 突合（MB_SR0021/0022/0023）が別途見ているため
    （sdrf.user_defined_warning_exclude_kinds）。
    """
    sub = _udc_sub(["Characteristics[tissue]", "Characteristics[sex]"])
    assert S.MB_SR0006().validate(sub, CTX) == []
    assert S.MB_SR0007().validate(sub, CTX) == []


def test_unnamed_characteristics_is_still_sr0007():
    """warning 対象外でも、名前の無い `Characteristics[]` は MB_SR0007 で拾う。"""
    sub = _udc_sub(["Characteristics[]"])
    msgs = [r["message"] for r in S.MB_SR0007().validate(sub, CTX)]
    assert len(msgs) == 1 and "Characteristics[]" in msgs[0]


def test_parameter_value_and_factor_value_are_allowed_kinds():
    """Parameter Value / Factor Value も許容種別（MB_SR0007 ではなく MB_SR0006）。"""
    sub = _udc_sub(["Parameter Value[my param]", "Factor Value[dose]"])
    assert S.MB_SR0007().validate(sub, CTX) == []
    msgs = [r["message"] for r in S.MB_SR0006().validate(sub, CTX)]
    assert len(msgs) == 1
    assert "Parameter Value[my param]" in msgs[0] and "Factor Value[dose]" in msgs[0]


def test_unknown_column_name_is_sr0007():
    """許容種別でもない列名は MB_SR0007（error / internal ignore）。"""
    sub = _udc_sub(["My Column", "Foo[bar]"])
    msgs = [r["message"] for r in S.MB_SR0007().validate(sub, CTX)]
    assert len(msgs) == 1
    assert "My Column" in msgs[0] and "Foo[bar]" in msgs[0]


def test_unnamed_bracket_column_is_sr0007():
    """名前の無い `Kind[]` は MB_SR0007。既定列の `Characteristics[]` は種別プレースホルダ
    であって列名ではないので、既定列集合には数えない。"""
    sub = _udc_sub(["Characteristics[]"])
    msgs = [r["message"] for r in S.MB_SR0007().validate(sub, CTX)]
    assert len(msgs) == 1 and "Characteristics[]" in msgs[0]


def test_sr0007_is_internal_ignore():
    from apps.metabobank.rules.base import is_internal_ignore
    assert is_internal_ignore("MB_SR0007")


# --- MB_SR0004 / MB_SR0009: 推奨列 3 つの必須化 ----------------------------
#
# Raw Data File / Comment[sample_title] / Comment[BioSample] を required_columns_error に
# 移したので、列の存在は MB_SR0004、値の空欄は MB_SR0009 が見る。
# raw が無い投稿は列を消すのではなく null value（CV term）を書く運用に合わせた変更。

_NEW_REQUIRED = ["Raw Data File", "Comment[sample_title]", "Comment[BioSample]"]


def _sub_with_new_required(overrides=None, drop=()):
    ov = dict(overrides or {})
    header = [c for c in list(_COLS) + _NEW_REQUIRED if c not in drop]
    filled = dict(_FILLED, **{"Raw Data File": "f.raw", "Comment[sample_title]": "t",
                              "Comment[BioSample]": "SAMD00000001"})
    rows = [[ov.get(c, filled.get(c, "v")) for c in header]]
    idf = Idf(fields={"Comment[Submission type]": ["LC-MS"]},
              field_order=["Comment[Submission type]"])
    return Submission(idf=idf, sdrf=Sdrf(header=header, rows=rows))


@pytest.mark.parametrize("col", _NEW_REQUIRED)
def test_new_required_column_missing_is_sr0004(col):
    sub = _sub_with_new_required(drop=(col,))
    msgs = [r["message"] for r in S.MB_SR0004().validate(sub, CTX)]
    assert len(msgs) == 1 and col in msgs[0]


@pytest.mark.parametrize("col", _NEW_REQUIRED)
def test_new_required_column_empty_value_is_sr0009(col):
    """列はあるが値が空 → MB_SR0009（波及を承諾済み）。"""
    sub = _sub_with_new_required(overrides={col: ""})
    msgs = _msgs(sub)
    assert len(msgs) == 1 and col in msgs[0]


def test_raw_data_file_null_value_is_still_sr0009():
    """raw が無い場合に書く null value（CV term）も MB_SR0009 の対象（値なし扱い）。"""
    sub = _sub_with_new_required(overrides={"Raw Data File": "not applicable"})
    msgs = _msgs(sub)
    assert len(msgs) == 1 and "Raw Data File" in msgs[0]


def test_sr0009_reports_each_required_column_once():
    """required_value_error を空にしたので Raw Data File が二重報告されないこと。"""
    sub = _sub_with_new_required(overrides={"Raw Data File": ""})
    assert len([m for m in _msgs(sub) if "Raw Data File" in m]) == 1


# --- MB_SR0026: 骨格列の相対順序 -------------------------------------------

def _order_sub(header):
    idf = Idf(fields={"Comment[Submission type]": ["LC-MS"]},
              field_order=["Comment[Submission type]"])
    return Submission(idf=idf, sdrf=Sdrf(header=header, rows=[["v"] * len(header)]))


def test_skeleton_order_ok():
    sub = _order_sub(["Source Name", "Characteristics[organism]", "Sample Name",
                      "Extract Name", "Assay Name", "Raw Data File",
                      "Processed Data File", "Metabolite Assignment File"])
    assert S.MB_SR0026().validate(sub, CTX) == []


def test_skeleton_order_violation_is_reported():
    """Assay Name が Extract Name より前にあれば error。"""
    sub = _order_sub(["Source Name", "Sample Name", "Assay Name", "Extract Name",
                      "Raw Data File"])
    msgs = [r["message"] for r in S.MB_SR0026().validate(sub, CTX)]
    assert len(msgs) == 1
    assert "Extract Name" in msgs[0] and "Assay Name" in msgs[0]


def test_missing_skeleton_columns_are_skipped():
    """存在しない骨格列は飛ばす（MSI の Extract Name / 任意のデータファイル列）。列の有無は MB_SR0004 の担当。"""
    sub = _order_sub(["Source Name", "Sample Name", "Assay Name", "Raw Data File"])
    assert S.MB_SR0026().validate(sub, CTX) == []


def test_non_skeleton_columns_do_not_affect_order():
    """Protocol REF / Unit[...] のような重複許容列の位置は見ない（誤検知を避けるため）。"""
    sub = _order_sub(["Source Name", "Protocol REF", "Sample Name", "Protocol REF",
                      "Extract Name", "Unit[temperature]", "Assay Name",
                      "Unit[temperature]", "Raw Data File"])
    assert S.MB_SR0026().validate(sub, CTX) == []
