"""Run accession のある行の `none` は `GEA_SR0003`（raw なしの warning）の対象外になること。

sequencing の raw は DRA にあり Run accession で参照する。登録者が `Raw Data File` に手で `none` と
書くことがあるが、その行は「raw が無い」行ではない（2026-11-28、ddbj-apps からの依頼。
ddbj-apps の `specs/raw-data-exemption.md` 決定 9）。ddbj-apps は `none` の行がある submission の採番を
キュレータの承認まで止めるが Run accession のある行は数えないので、warning も同じ判定にする。

ここでは「Run accession のある行だけが外れる」ことと、
**Run accession の無い行（空・null 値・Experiment だけ）は従来どおり warning のまま**であることを固定する。
"""
from apps.gea.context import ValidationContext
from apps.gea.model import GeaSubmission
from apps.gea.rules.sdrf import GEA_SR0003
from common.magetab.model import Sdrf


def _lines(header, rows):
    """SDRF を作って GEA_SR0003 を回し、warning の出た行番号（1 始まり）を返す。"""
    sdrf = Sdrf()
    sdrf.header, sdrf.rows = header, rows
    sub = GeaSubmission()
    sub.sdrf = sdrf
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    return [r["line"] for r in GEA_SR0003().validate(sub, ctx)]


def test_none_with_run_accession_in_the_same_row_is_not_warned():
    """依頼書の確認例そのもの: DRR あり → 出ない／Run 列が空 → 出る／DRX だけ → 出る。"""
    rows = [["s1", "DRR000001", "none"],
            ["s2", "", "none"],
            ["s3", "DRX000001", "none"]]
    assert _lines(["Source Name", "Comment[SRA_RUN]", "Raw Data File"], rows) == [2, 3]


def test_old_column_name_dra_run_counts_too():
    """旧 GEA の列名 `Comment[DRA Run]` でも同じ扱い。"""
    rows = [["DRR000001", "none"], ["", "none"]]
    assert _lines(["Comment[DRA Run]", "Raw Data File"], rows) == [2]


def test_err_and_srr_are_run_accessions():
    """DDBJ 以外の Run（ERR / SRR）も Run accession。"""
    rows = [["ERR000001", "none"], ["SRR000001", "none"]]
    assert _lines(["Comment[SRA_RUN]", "Raw Data File"], rows) == []


def test_any_one_of_several_run_columns_is_enough():
    """Run 列が複数あるとき、どれか 1 つに書いてあればその行は対象外（同名の重複・新旧の併存）。"""
    header = ["Comment[SRA_RUN]", "Comment[SRA_RUN]", "Comment[DRA Run]", "Raw Data File"]
    rows = [["", "DRR000001", "", "none"],
            ["", "", "DRR000002", "none"],
            ["", "", "", "none"]]
    assert _lines(header, rows) == [3]


def test_run_accession_anywhere_in_the_cell_counts():
    """セルの中のどこかに Run accession があればよい（search）。複数値や前後の文字があっても可。"""
    rows = [["DRR000001,DRR000002", "none"], [" DRR000003 ", "None"]]
    assert _lines(["Comment[SRA_RUN]", "Raw Data File"], rows) == []


def test_null_value_or_non_run_text_is_still_warned():
    """`missing` などの null 値や、Run の形でない文字列は Run accession ではない。"""
    rows = [["missing", "none"], ["not applicable", "none"], ["DRR", "none"], ["XDRR000001", "none"]]
    assert _lines(["Comment[SRA_RUN]", "Raw Data File"], rows) == [1, 2, 3, 4]


def test_run_accession_in_another_row_does_not_count():
    """行単位で見る。ほかの行に Run accession があっても、その行の `none` は warning のまま。"""
    rows = [["DRR000001", "DRR000001.fastq"], ["", "none"]]
    assert _lines(["Comment[SRA_RUN]", "Raw Data File"], rows) == [2]


def test_without_run_column_every_none_is_warned_as_before():
    """Run 列が無い SDRF（microarray など）は今までどおり全部の `none` に warning。"""
    rows = [["s1", "none"], ["s2", "NONE"], ["s3", "a.cel"], ["s4", ""]]
    assert _lines(["Source Name", "Raw Data File"], rows) == [1, 2]


def test_short_row_is_handled():
    """ヘッダーより短い行（Run 列のセルが無い）でも落ちず、Run なしとして warning。"""
    header = ["Raw Data File", "Comment[SRA_RUN]"]
    assert _lines(header, [["none"], ["none", "DRR000001"]]) == [1]
