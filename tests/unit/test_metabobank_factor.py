"""Experimental Factor の任意化（MetaboBank）の挙動テスト。

factor は IDF `Experimental Factor Name` / `Type` と SDRF `Factor Value[...]` の 3 箇所に
またがり、任意化に伴って「書かない」が正規の書き方になった。null value（missing 等）を
書くのは不許可で、担当ルールが側によって違う（IDF Name=MB_IR0007 / Type=MB_IR0023 /
SDRF=MB_CR0001）ため、境界が崩れていないかをここで固定する。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit/test_metabobank_factor.py`
"""
import pytest

from apps.metabobank.context import ValidationContext
from apps.metabobank.rules import cross as C, idf as I, sdrf as S
from apps.metabobank.rules.base import is_internal_ignore
# submission_type プロパティが要るので common の Idf ではなく mb の Idf を使う
from apps.metabobank.model import Idf, MbSubmission as Submission
from common.magetab.model import Sdrf

CTX = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)

# MB_IR0005/0007/0023 は IDF 全体を見るので、factor 以外で発火しない最小の IDF を土台にする。
_BASE_IDF = {
    "MAGE-TAB Version": ["1.1"],
    "Study Title": ["title"],
    "Study Description": ["description"],
    "Experimental Design": ["case control design"],
    "Person Last Name": ["Doe"],
    "Person First Name": ["John"],
    "Person Affiliation": ["NIG"],
    "Person Roles": ["submitter"],
    "Protocol Name": ["P1"],
    "Protocol Type": ["Extraction"],
    "Protocol Description": ["desc"],
    "Comment[Study type]": ["metabolomics"],
    "Comment[Experiment type]": ["untargeted metabolites"],
    "Comment[Submission type]": ["LC-MS"],
}


def _sub(factor_names=None, factor_types=None, factor_values=None):
    """IDF factor / SDRF Factor Value だけを差し替えた最小 submission を作る。"""
    fields = {k: list(v) for k, v in _BASE_IDF.items()}
    if factor_names is not None:
        fields["Experimental Factor Name"] = list(factor_names)
    if factor_types is not None:
        fields["Experimental Factor Type"] = list(factor_types)
    # 任意化後も推奨として残る 3 列は土台に含める（MB_SR0005 の雑音を避ける）
    header = ["Source Name", "Sample Name", "Comment[BioSample]", "Comment[sample_title]",
              "Raw Data File"] + [f"Factor Value[{x}]" for x in (factor_values or [])]
    rows = [["s1", "s1", "SAMD00000001", "t", "f.raw"] + ["v"] * len(factor_values or [])]
    return Submission(idf=Idf(fields=fields, field_order=list(fields)),
                      sdrf=Sdrf(header=header, rows=rows))


def _ids(sub, *rules):
    out = []
    for r in rules:
        out += [x["rule_id"] for x in r.validate(sub, CTX)]
    return out


def _msgs(sub, rule):
    return [x["message"] for x in rule.validate(sub, CTX)]


# --- MB_CR0001: 双方向照合 ------------------------------------------------

def test_no_factor_on_either_side_is_silent():
    """どちらにも factor が無ければ無指摘。任意項目なので「書かない」が正規の書き方。"""
    assert _msgs(_sub(), C.MB_CR0001()) == []


def test_matching_factor_is_silent():
    assert _msgs(_sub(factor_names=["treatment"], factor_values=["treatment"]), C.MB_CR0001()) == []


def test_factor_only_in_sdrf():
    msgs = _msgs(_sub(factor_values=["treatment"]), C.MB_CR0001())
    assert len(msgs) == 1 and "only in SDRF: treatment" in msgs[0]


def test_factor_only_in_idf():
    """IDF に factor name があれば SDRF Factor Value[name] は必須（逆方向。今回追加）。"""
    msgs = _msgs(_sub(factor_names=["treatment"]), C.MB_CR0001())
    assert len(msgs) == 1 and "only in IDF: treatment" in msgs[0]


def test_both_directions_are_reported_separately():
    """両方向の不一致は 1 件にまとめず 2 件に分ける（どちらを直すのかが読めるように）。"""
    msgs = _msgs(_sub(factor_names=["dose"], factor_values=["treatment"]), C.MB_CR0001())
    assert len(msgs) == 2
    assert any("only in SDRF: treatment" in m for m in msgs)
    assert any("only in IDF: dose" in m for m in msgs)


def test_cr0001_is_internal_ignore():
    """MB_CR0001 は ignore error（管理システムは無視、登録者には表示）。"""
    assert is_internal_ignore("MB_CR0001")


# --- null value（missing 等）は不許可 -------------------------------------

def test_null_factor_name_is_error_via_ir0007():
    """IDF Name の null value は MB_IR0007（error / ignore）。書かずに済むので許さない。"""
    sub = _sub(factor_names=["missing"])
    msgs = _msgs(sub, I.MB_IR0007())
    assert len(msgs) == 1 and "Experimental Factor Name" in msgs[0]


def test_null_factor_name_does_not_double_report_in_cr0001():
    """MB_IR0007 が指摘するので MB_CR0001 では二重に出さない（IDF 側は null を除外）。"""
    assert _msgs(_sub(factor_names=["missing"]), C.MB_CR0001()) == []


def test_null_factor_type_is_warned_via_ir0023():
    """Type は必須でも not_null でもないので、汎用の任意項目 null チェックが受ける。"""
    msgs = _msgs(_sub(factor_types=["missing"]), I.MB_IR0023())
    assert len(msgs) == 1 and "Experimental Factor Type" in msgs[0]


def test_null_in_sdrf_factor_value_column_is_reported():
    """SDRF 側の Factor Value[<null value>] は除外しないので only in SDRF として出る。"""
    msgs = _msgs(_sub(factor_values=["missing"]), C.MB_CR0001())
    assert len(msgs) == 1 and "only in SDRF: missing" in msgs[0]


def test_absent_factor_is_not_a_missing_mandatory_field():
    """factor を書かない IDF は MB_IR0005/0007/0023 のいずれも発火しない（任意項目）。"""
    assert _ids(_sub(), I.MB_IR0005(), I.MB_IR0007(), I.MB_IR0023()) == []


def test_empty_valued_factor_is_not_a_missing_mandatory_field():
    """項目行はあるが値が無い形（実データ 15 study の形）も無指摘であること。"""
    sub = _sub(factor_names=[], factor_types=[])
    assert _ids(sub, I.MB_IR0005(), I.MB_IR0007(), I.MB_IR0023()) == []


# --- SDRF 推奨列の任意化 ---------------------------------------------------

def test_factor_value_column_is_not_a_recommended_column():
    """Factor Value / Processed Data File / Metabolite Assignment File は無くても警告しない。"""
    assert _msgs(_sub(), S.MB_SR0005()) == []


def test_raw_data_file_is_still_recommended():
    """Raw Data File は推奨列として残す（任意化の対象外）。"""
    sub = _sub()
    sub.sdrf.header = [h for h in sub.sdrf.header if h != "Raw Data File"]
    msgs = _msgs(sub, S.MB_SR0005())
    assert len(msgs) == 1 and "Raw Data File" in msgs[0]


# --- 削除したルールが残っていないこと --------------------------------------

def test_ir0035_is_removed():
    """MB_IR0035（name/type 一致チェック）は Type 無検証化に伴い削除済み。"""
    from apps.metabobank.validator import Validator
    assert not hasattr(I, "MB_IR0035")
    ids = {r.rule_id for r in Validator(CTX).active_rules}
    assert "MB_IR0035" not in ids


# --- autofix: 非推奨 null → missing → 空（二段） ----------------------------

def _write_and_read(tmp_path, idf_lines):
    """_write_fixed に IDF を通し、fixed/ の該当行を返す。"""
    from apps.metabobank.cli import _write_fixed
    src = tmp_path / "MTBKS_x.idf.txt"
    src.write_text("\n".join(idf_lines) + "\n", encoding="utf-8")
    fields, order = {}, []
    for ln in idf_lines:
        cells = ln.split("\t")
        fields[cells[0]] = [c for c in cells[1:]]
        order.append(cells[0])
    sub = Submission(idf=Idf(fields=fields, field_order=order, raw_path=str(src)))
    _write_fixed(sub, str(tmp_path))
    out = (tmp_path / "fixed" / "MTBKS_x.idf.txt").read_text(encoding="utf-8")
    return out.rstrip("\n").split("\n")


def test_autofix_empties_null_factor_name(tmp_path):
    """accepted null（missing 等）はそのまま消す。値を書かない形が正規。"""
    got = _write_and_read(tmp_path, ["Experimental Factor Name\tmissing"])
    assert got == ["Experimental Factor Name"]


def test_autofix_two_stage_not_recommended_null_becomes_empty(tmp_path):
    """一段目で NA -> missing、二段目で missing -> 空。除外項目を持たない二段構成。

    一段目だけだと autofix が MB_IR0007（null value は不許可）を自ら作り出してしまう。
    """
    got = _write_and_read(tmp_path, ["Experimental Factor Name\tNA",
                                     "Experimental Factor Type\tUnknown"])
    assert got == ["Experimental Factor Name", "Experimental Factor Type"]


def test_autofix_keeps_real_factor_value(tmp_path):
    """実 factor 名は触らない。"""
    got = _write_and_read(tmp_path, ["Experimental Factor Name\ttreatment\tdose"])
    assert got == ["Experimental Factor Name\ttreatment\tdose"]


def test_autofix_does_not_copy_name_into_type(tmp_path):
    """MB_IR0035 の autofix（Type <- Name）を削除したので Type は補完されない。

    ルールだけ消して cli の autofix を残すと fixed/ の Type が Name で上書きされ続け、
    「Type に一律 Name と同じ値が入っている」状態を validator 自身が再生産してしまう。
    """
    got = _write_and_read(tmp_path, ["Experimental Factor Name\ttreatment",
                                     "Experimental Factor Type\tdose"])
    assert got == ["Experimental Factor Name\ttreatment", "Experimental Factor Type\tdose"]


def test_autofix_null_in_other_field_stays_missing(tmp_path):
    """二段目は autofix_null_to_empty の項目だけ。他項目は従来どおり missing のまま。"""
    got = _write_and_read(tmp_path, ["Comment[Sample Description]\tNA"])
    assert got == ["Comment[Sample Description]\tmissing"]


# --- MB_IR0018: Chromatography Temperature の任意化 -------------------------

_CHROMA_PARAMS = "Chromatography instrument;Autosampler model;Column model;Column type;Guard column"


def _proto_sub(submission_type, chroma_params):
    """Chromatography プロトコルだけを持つ IDF（MB_IR0018 の判定に必要な最小形）。"""
    fields = {
        "Comment[Submission type]": [submission_type],
        "Protocol Name": ["P1"],
        "Protocol Type": ["Chromatography"],
        "Protocol Parameters": [chroma_params],
    }
    return Submission(idf=Idf(fields=fields, field_order=list(fields)),
                      sdrf=Sdrf(header=["Source Name"], rows=[["s1"]]))


def _chroma_missing(submission_type, chroma_params):
    """MB_IR0018 が Chromatography について報告した不足パラメータ名。"""
    out = []
    for r in I.MB_IR0018().validate(_proto_sub(submission_type, chroma_params), CTX):
        if "Chromatography:" not in r["message"]:
            continue
        out += [x.strip() for x in r["message"].rsplit("Chromatography:", 1)[1].rstrip(")").split(",")]
    return out


@pytest.mark.parametrize("st", ["LC-MS", "GC-MS", "LC-DAD-MS", "GC-FID-MS"])
def test_chromatography_temperature_is_optional(st):
    """Chromatography: Temperature は必須ではない（記載負荷が高いため）。

    公開 114 study で MB_IR0018 の発火 92 件は submission type を問わず全部この
    Temperature が原因だった（他パラメータの欠落は 1 件も無し）。

    submission type ごとに他の必須パラメータ（Detector / Signal range 等）が違うので、
    「不足なし」ではなく「不足に Temperature が挙がらない」ことを見る。
    """
    assert "Temperature" not in _chroma_missing(st, _CHROMA_PARAMS)


def test_nmr_sample_temperature_is_optional():
    """NMR sample: Temperature も任意（別プロトコルだが方針を揃える）。"""
    fields = {
        "Comment[Submission type]": ["NMR"],
        "Protocol Name": ["P1"],
        "Protocol Type": ["NMR sample"],
        "Protocol Parameters": ["NMR tube type;Solvent;Sample pH"],
    }
    sub = Submission(idf=Idf(fields=fields, field_order=list(fields)),
                     sdrf=Sdrf(header=["Source Name"], rows=[["s1"]]))
    msgs = [r["message"] for r in I.MB_IR0018().validate(sub, CTX)]
    assert not any("NMR sample:" in m for m in msgs), msgs


def test_ir0018_does_not_require_optional_chromatography_parameters():
    """Chromatography の parameter は全部任意なので、空でも MB_IR0018 は出ない。

    公式テンプレでは Parameter Value 列 159 個中 157 個が BLUE(optional)。
    以前は出力仕様のキーを必須として読んでいたため、任意列の未記入がエラーになっていた。
    """
    assert _chroma_missing("LC-MS", "") == []


def test_ir0018_detects_the_mandatory_msi_parameters():
    """MB_IR0018 が現に検出するのは MSI の ORANGE(mandatory) 2 列だけ。"""
    fields = {
        "Comment[Submission type]": ["MSI"],
        "Protocol Name": ["P1"],
        "Protocol Type": ["Data processing"],
        "Protocol Parameters": ["Data processing software"],   # version が無い
    }
    sub = Submission(idf=Idf(fields=fields, field_order=list(fields)),
                     sdrf=Sdrf(header=["Source Name"], rows=[["s1"]]))
    msgs = [r["message"] for r in I.MB_IR0018().validate(sub, CTX)]
    assert len(msgs) == 1 and "Data processing software version" in msgs[0]
    assert "Data processing software," not in msgs[0]   # 宣言済みの方は挙げない


# --- MB_SR0047: Factor Value 列があるのに値が無い ---------------------------

def _fv_sub(rows_of_values):
    """Factor Value[treatment] 列を持つ SDRF（値は行ごとに指定）。"""
    fields = {"Comment[Submission type]": ["LC-MS"],
              "Experimental Factor Name": ["treatment"]}
    header = ["Source Name", "Factor Value[treatment]"]
    rows = [[f"s{i + 1}", v] for i, v in enumerate(rows_of_values)]
    return Submission(idf=Idf(fields=fields, field_order=list(fields)),
                      sdrf=Sdrf(header=header, rows=rows))


def test_sr0047_fires_when_all_rows_empty():
    """列はあるが全行空 → 「値が無い」エラー。"""
    msgs = _msgs(_fv_sub(["", ""]), S.MB_SR0047())
    assert len(msgs) == 1 and "Factor Value[treatment]" in msgs[0]


def test_sr0047_fires_for_single_row():
    """MB_SR0017 は 2 行未満だと判定しないが、値が無いことは 1 行でも問題。"""
    assert len(_msgs(_fv_sub([""]), S.MB_SR0047())) == 1


def test_sr0047_treats_null_value_as_no_value():
    """null value（missing 等）しか無い列も「値が無い」扱い。"""
    assert len(_msgs(_fv_sub(["missing", "missing"]), S.MB_SR0047())) == 1


def test_sr0047_silent_when_any_row_has_a_value():
    """一部の行が空なのは正常（QC/blank 等で factor が適用されない行がある）。

    公開 114 study では 83 列が「一部の行だけ空」だった。ここをエラーにすると
    大量の誤検知になるため、全行に値が無い場合だけを対象にする。
    """
    assert _msgs(_fv_sub(["treated", ""]), S.MB_SR0047()) == []


def test_sr0047_silent_when_no_factor_value_column():
    """Factor Value 列そのものが無ければ無指摘（任意列）。"""
    assert _msgs(_sub(), S.MB_SR0047()) == []


def test_sr0017_does_not_report_constant_for_a_valueless_column():
    """値が無い列を MB_SR0017 が「全行で一定」と誤診しないこと（MB_SR0047 に委譲）。"""
    assert _msgs(_fv_sub(["", ""]), S.MB_SR0017()) == []


def test_sr0017_still_reports_genuine_constant_value():
    """非空の値が全行で同じなら、従来どおり MB_SR0017 が指摘する。"""
    msgs = _msgs(_fv_sub(["treated", "treated"]), S.MB_SR0017())
    assert len(msgs) == 1 and "Factor Value[treatment]" in msgs[0]


def test_sr0047_is_internal_ignore():
    """MB_SR0047 は ignore error（管理システムは無視、登録者には表示）。

    MB_SR0017 も ignore なので、値が無い列の診断先が MB_SR0017 から MB_SR0047 に
    移っても管理システム側の扱いは変わらない。
    """
    assert is_internal_ignore("MB_SR0047")
