"""MB_CR0002 / MB_CR0003 の双方向照合（IDF↔SDRF の過不足なし）のテスト。

ルール表の「IDF の Protocol、及び、SDRF で参照されている Protocol が一致していない」
「IDF の Protocol Parameter、及び、SDRF の Protocol Parameter が一致していない」は
**過不足なし**の意味なので、片側にしか無いものを向きを添えて指摘する。
2026-09-14 に片方向（SDRF→IDF）から双方向へ拡張した際の境界をここで固定する。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit/test_metabobank_cross_protocol.py`
"""
from apps.metabobank.context import ValidationContext
from apps.metabobank.rules import cross as C
from apps.metabobank.rules.base import is_internal_ignore
from apps.metabobank.model import Idf, MbSubmission as Submission
from common.magetab.model import Sdrf

CTX = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)


def _sub(protocols, params=None, refs=None, param_cols=None):
    """Protocol Name / Protocol Parameters と SDRF 側の参照・列だけを持つ最小 submission。

    protocols   IDF Protocol Name の値（列並列）
    params      IDF Protocol Parameters の値（`;` 区切り。protocols と同じ並び）
    refs        SDRF の Protocol REF 列に入れる値（列 1 本につき 1 値）
    param_cols  SDRF の `Parameter Value[...]` 列名に使うパラメータ名
    """
    fields = {"Protocol Name": list(protocols)}
    if params is not None:
        fields["Protocol Parameters"] = list(params)
    header = ["Source Name"] + ["Protocol REF"] * len(refs or []) \
        + [f"Parameter Value[{x}]" for x in (param_cols or [])]
    rows = [["s1"] + list(refs or []) + ["v"] * len(param_cols or [])]
    return Submission(idf=Idf(fields=fields, field_order=list(fields)),
                      sdrf=Sdrf(header=header, rows=rows))


def _msgs(sub, rule):
    return [x["message"] for x in rule.validate(sub, CTX)]


def _sides(sub, rule):
    """各 finding が載せた向き（sdrf_only / idf_only）と値の一覧。"""
    return [(("sdrf_only" if "sdrf_only" in x else "idf_only"),
             x.get("sdrf_only") or x.get("idf_only")) for x in rule.validate(sub, CTX)]


# --- MB_CR0002: Protocol Name ↔ Protocol REF ------------------------------

def test_cr0002_silent_when_both_sides_match():
    sub = _sub(["Extraction", "Mass spectrometry"], refs=["Extraction", "Mass spectrometry"])
    assert _msgs(sub, C.MB_CR0002()) == []


def test_cr0002_reports_sdrf_only():
    """SDRF が参照しているのに IDF に定義が無い（従来からの方向）。"""
    sub = _sub(["Extraction"], refs=["Extraction", "Mass spectrometry"])
    assert _sides(sub, C.MB_CR0002()) == [("sdrf_only", "Mass spectrometry")]
    assert "only in SDRF: Mass spectrometry" in _msgs(sub, C.MB_CR0002())[0]


def test_cr0002_reports_idf_only():
    """IDF で定義したのに SDRF がどの行からも参照していない（双方向化で追加）。"""
    sub = _sub(["Extraction", "Metabolite identification"], refs=["Extraction"])
    assert _sides(sub, C.MB_CR0002()) == [("idf_only", "Metabolite identification")]
    assert "only in IDF: Metabolite identification" in _msgs(sub, C.MB_CR0002())[0]


def test_cr0002_reports_both_directions_separately():
    """両方向にズレがあれば 2 件に分ける（どちらを直すかが 1 件では分からないため）。"""
    sub = _sub(["Extraction"], refs=["Mass spectrometry"])
    assert _sides(sub, C.MB_CR0002()) == [("sdrf_only", "Mass spectrometry"),
                                          ("idf_only", "Extraction")]


def test_cr0002_ignores_empty_protocol_ref_cells():
    """空セルは参照なし。値の欠落は MB_SR0033 / MB_SR0049 の担当なのでここでは向きに数えない。

    ただし列全体が空なら IDF 側の protocol が未参照になるので only in IDF は出る。
    """
    sub = _sub(["Extraction"], refs=[""])
    assert _sides(sub, C.MB_CR0002()) == [("idf_only", "Extraction")]


def test_cr0002_null_value_is_not_excluded():
    """null value（missing）は除外しない（現状維持）。IDF に無い値として only in SDRF 側に出る。"""
    sub = _sub(["Extraction"], refs=["missing"])
    sides = _sides(sub, C.MB_CR0002())
    assert ("sdrf_only", "missing") in sides
    assert ("idf_only", "Extraction") in sides


def test_cr0002_is_error_and_internal_ignore():
    sub = _sub(["Extraction"], refs=["Mass spectrometry"])
    assert all(x["level"] == "error" for x in C.MB_CR0002().validate(sub, CTX))
    assert is_internal_ignore("MB_CR0002")


# --- MB_CR0003: Protocol Parameters ↔ Parameter Value[...] ----------------

def test_cr0003_silent_when_both_sides_match():
    sub = _sub(["P1"], params=["Instrument;Ion source"],
               param_cols=["Instrument", "Ion source"])
    assert _msgs(sub, C.MB_CR0003()) == []


def test_cr0003_reports_sdrf_only():
    """列はあるが IDF で宣言されていない（従来からの方向）。"""
    sub = _sub(["P1"], params=["Instrument"], param_cols=["Instrument", "Ion source"])
    assert _sides(sub, C.MB_CR0003()) == [("sdrf_only", "Ion source")]


def test_cr0003_reports_idf_only():
    """IDF で宣言したのに SDRF に列が無い（双方向化で追加）。既定列が削られた投稿を拾う。"""
    sub = _sub(["P1"], params=["Instrument;Temperature"], param_cols=["Instrument"])
    assert _sides(sub, C.MB_CR0003()) == [("idf_only", "Temperature")]


def test_cr0003_reports_both_directions_separately():
    sub = _sub(["P1"], params=["Temperature"], param_cols=["Instrument"])
    assert _sides(sub, C.MB_CR0003()) == [("sdrf_only", "Instrument"),
                                          ("idf_only", "Temperature")]


def test_cr0003_collects_parameters_across_protocols():
    """IDF 側は protocol 横断のフラットな名前集合で比較する（どの protocol に属するかは見ない）。"""
    sub = _sub(["P1", "P2"], params=["Instrument", "Ion source"],
               param_cols=["Ion source", "Instrument"])
    assert _msgs(sub, C.MB_CR0003()) == []


def test_cr0003_silent_when_neither_side_has_parameters():
    sub = _sub(["P1"], params=[""])
    assert _msgs(sub, C.MB_CR0003()) == []


def test_cr0003_is_error_and_internal_ignore():
    sub = _sub(["P1"], params=["Temperature"], param_cols=["Instrument"])
    assert all(x["level"] == "error" for x in C.MB_CR0003().validate(sub, CTX))
    assert is_internal_ignore("MB_CR0003")
