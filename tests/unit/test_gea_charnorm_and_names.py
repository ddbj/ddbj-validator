"""GEA に追加した 4 ルール（2026-09-26）。MetaboBank の同等ルールと挙動を揃える。

- GEA_G0017 / GEA_SR0016: 非 ASCII。ASCII 化できた文字は warning（autofix 報告）、
  表に無く残った文字（日本語など）は error。MB_IR0024 / MB_SR0030 と同仕様。
- GEA_DF0004: データファイル名に使える文字（MB_SR0036 と同仕様）。
- GEA_AN0010: 同じ Assay Name が複数の DRA Experiment を指していないか。
  MB_SR0050 とは**判定が違う**（GEA は 1 assay が複数行に跨るのが正しいため）。
"""
from apps.gea.model import GeaSubmission, Idf
from apps.gea.rules.base import INTERNAL_IGNORE_RULE_IDS
from common.magetab.model import Sdrf
from common.magetab.charnorm import normalize, apply_to_submission


def _sub(header=None, rows=None, idf_fields=None):
    s = GeaSubmission()
    if idf_fields is not None:
        idf = Idf()
        idf.fields = {k: list(v) for k, v in idf_fields.items()}
        idf.field_order = list(idf_fields)
        s.idf = idf
    if header is not None:
        sd = Sdrf()
        sd.header, sd.rows = header, rows or []
        s.sdrf = sd
    return s


def _ctx(defs=None):
    return type("C", (), {"definitions": defs or {}})()


# ---------------- 正規化そのもの ----------------
def test_normalize_maps_symbols_and_keeps_japanese_as_residual():
    new, mapped, residual = normalize("25°C ± 2 肝臓")
    assert "°" not in new and "±" not in new     # ASCII 化された
    assert mapped == {"°", "±"}
    assert residual == {"肝", "臓"}               # 表に無いので残る＝error 対象
    assert "肝臓" in new                          # 報告のため値は残す


def test_normalize_leaves_ascii_untouched():
    assert normalize("Sample_1.gpr") == ("Sample_1.gpr", set(), set())


# ---------------- GEA_G0017 / GEA_SR0016 ----------------
def test_g0017_splits_warning_and_error():
    from apps.gea.rules.idf import GEA_G0017
    sub = _sub(idf_fields={"Experiment Description": ["25°C の肝臓"]})
    apply_to_submission(sub)
    res = GEA_G0017().validate(sub, _ctx())
    levels = sorted(r["level"] for r in res)
    assert levels == ["error", "warning"]        # ° は warning、日本語は error
    assert "GEA_G0017" in INTERNAL_IGNORE_RULE_IDS


def test_sr0016_reports_cells_and_control_characters():
    from apps.gea.rules.sdrf import GEA_SR0016
    sub = _sub(header=["Characteristics[taxonomy_id]"], rows=[["１００９０"]])
    apply_to_submission(sub)
    res = GEA_SR0016().validate(sub, _ctx())
    assert [r["level"] for r in res] == ["error"]   # 全角数字は ASCII 化表に無い

    # 制御文字は正規化表の対象外だが error にする
    ctrl = _sub(header=["Source Name"], rows=[["a\x01b"]])
    apply_to_submission(ctrl)
    assert any(r["level"] == "error" for r in GEA_SR0016().validate(ctrl, _ctx()))

    ok = _sub(header=["Source Name"], rows=[["Sample_1"]])
    apply_to_submission(ok)
    assert GEA_SR0016().validate(ok, _ctx()) == []


# ---------------- GEA_DF0004 ----------------
def test_df0004_rejects_non_ascii_file_names():
    from apps.gea.rules.sdrf import GEA_DF0004
    defs = {"sdrf": {"cross_column_unique_files": ["Raw Data File"], "legacy_fields": []}}
    r = GEA_DF0004()
    bad = _sub(header=["Raw Data File"], rows=[["日本語ファイル名.gpr"]])
    assert len(r.validate(bad, _ctx(defs))) == 1
    ok = _sub(header=["Raw Data File"], rows=[["Sample_1.gpr"], ["dir/Sample 2.gpr"]])
    assert r.validate(ok, _ctx(defs)) == []
    # raw-less の magic word は対象外
    none = _sub(header=["Raw Data File"], rows=[["none"]])
    assert r.validate(none, _ctx(defs)) == []
    assert "GEA_DF0004" not in INTERNAL_IGNORE_RULE_IDS   # MB_SR0036 と同じく ignore なし


# ---------------- GEA_AN0010 ----------------
def test_an0010_flags_one_assay_name_across_two_experiments():
    from apps.gea.rules.nodes import GEA_AN0010
    r = GEA_AN0010()
    bad = _sub(header=["Assay Name", "Comment[SRA_EXPERIMENT]"],
               rows=[["a1", "DRX0000001"], ["a1", "DRX0000002"]])
    res = r.validate(bad, _ctx())
    assert len(res) == 1 and "a1" in res[0]["message"]
    assert "GEA_AN0010" in INTERNAL_IGNORE_RULE_IDS


def test_an0010_allows_one_assay_spanning_several_rows():
    """GEA では 1 assay が複数行に跨るのが正しい（processed file を 1 行ずつ並べる等）。

    MetaboBank の MB_SR0050 と同じ「行の重複」判定にすると、この正しい形が全部 error になる。
    """
    from apps.gea.rules.nodes import GEA_AN0010
    r = GEA_AN0010()
    same_exp = _sub(header=["Assay Name", "Comment[SRA_EXPERIMENT]", "Processed Data File"],
                    rows=[["a1", "DRX0000001", "barcodes.tsv.gz"],
                          ["a1", "DRX0000001", "features.tsv.gz"],
                          ["a1", "DRX0000001", "matrix.mtx.gz"]])
    assert r.validate(same_exp, _ctx()) == []

    # dual channel の microarray（上流の labeled extract は行ごとに違うが同じ assay）
    dual = _sub(header=["Assay Name", "Labeled Extract Name", "Label"],
                rows=[["a1", "le1", "Cy3"], ["a1", "le2", "Cy5"]])
    assert r.validate(dual, _ctx()) == []

    # DRX 列が無ければ判定しない
    no_exp = _sub(header=["Assay Name"], rows=[["a1"], ["a1"]])
    assert r.validate(no_exp, _ctx()) == []
