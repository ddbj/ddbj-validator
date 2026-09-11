"""Experimental Factor の任意化（MetaboBank）の挙動テスト。

factor は IDF `Experimental Factor Name` / `Type` と SDRF `Factor Value[...]` の 3 箇所に
またがり、任意化に伴って「書かない」が正規の書き方になった。null value（missing 等）を
書くのは不許可で、担当ルールが側によって違う（IDF Name=MB_IR0007 / Type=MB_IR0023 /
SDRF=MB_CR0001）ため、境界が崩れていないかをここで固定する。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit/test_metabobank_factor.py`
"""
import copy

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
    # MB_IR0005 の必須項目に Comment[BioProject] を追加したので土台に含める
    "Comment[BioProject]": ["PRJDB00000"],
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


def test_null_in_sdrf_factor_value_column_is_not_reported_by_cr0001():
    """SDRF 側の Factor Value[<null value>] は MB_CR0001 では出さない（name マッチ限定）。

    IDF 側の null を MB_IR0007 に委譲しているのと対称に、SDRF 側の null も
    MB_SR0047（値の欠落）へ委譲する。MB_CR0001 は実名どうしの一致だけを見る。
    """
    assert _msgs(_sub(factor_values=["missing"]), C.MB_CR0001()) == []


def test_null_named_factor_value_is_caught_by_sr0047():
    """null 名の Factor Value 列は **値が入っていても** MB_SR0047 が受ける。

    列名が null value なら factor として成立していないため。MB_CR0001 を name マッチ
    限定にした際、この判定を MB_SR0047 へ委譲した。
    """
    msgs = _msgs(_sub(factor_values=["missing"]), S.MB_SR0047())
    assert len(msgs) == 1 and "Factor Value[missing]" in msgs[0]


def test_null_named_factor_value_without_values_is_also_caught_by_sr0047():
    """値も無い場合も同じ 1 件（二重に出さない）。"""
    sub = _sub(factor_values=["missing"])
    sub.sdrf.rows = [row[:-1] + [""] for row in sub.sdrf.rows]
    msgs = _msgs(sub, S.MB_SR0047())
    assert len(msgs) == 1 and "Factor Value[missing]" in msgs[0]


def test_real_named_factor_value_with_values_is_silent_in_sr0047():
    """実名かつ値があれば MB_SR0047 は無指摘（null 名判定が過剰にならないこと）。"""
    assert _msgs(_sub(factor_values=["treatment"]), S.MB_SR0047()) == []


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


# --- MB_IR0018: 必須 protocol parameter は現在 0 件 ---------------------------
#
# 公式 Excel テンプレで ORANGE(mandatory) だった Parameter Value 列は MSI の
# Data processing software / version の 2 個だけで、それも他 10 テンプレと揃えて
# BLUE(optional) にした。結果 idf.protocol_parameters_required が空になり無発火。
# ただし将来また必須パラメータが出てくる可能性があるので deprecated にはせず、
# 登録も internal ignore も残す（definitions に足すだけで効く状態を保つ）。


def _proto_sub(submission_type, protocol_type, protocol_parameters):
    """プロトコル 1 つだけを持つ IDF（MB_IR0018 の判定に必要な最小形）。"""
    fields = {
        "Comment[Submission type]": [submission_type],
        "Protocol Name": ["P1"],
        "Protocol Type": [protocol_type],
        "Protocol Parameters": [protocol_parameters],
    }
    return Submission(idf=Idf(fields=fields, field_order=list(fields)),
                      sdrf=Sdrf(header=["Source Name"], rows=[["s1"]]))


def test_ir0018_stays_registered_and_ignored():
    """無発火でも deprecated にしない（必須パラメータが増えたら定義だけで効くように）。"""
    from apps.metabobank.context import ValidationContext
    from apps.metabobank.validator import Validator
    from apps.metabobank.rules.base import is_internal_ignore
    assert getattr(I.MB_IR0018, "deprecated", False) is False
    assert "MB_IR0018" in {r.rule_id for r in Validator(ValidationContext()).active_rules}
    assert is_internal_ignore("MB_IR0018")


def test_msi_data_processing_parameters_are_no_longer_required():
    """旧来 MB_IR0018 が唯一検出していた MSI の 2 パラメータ欠落も、もう出ない。"""
    assert I.MB_IR0018().validate(_proto_sub("MSI", "Data processing", ""), CTX) == []
    assert I.MB_IR0018().validate(
        _proto_sub("MSI", "Data processing", "Data processing software"), CTX) == []


def test_chromatography_parameters_are_not_required():
    """Chromatography の parameter は全部任意（Temperature を含む）。

    以前は出力仕様のキー（required_protocol_parameters）をそのまま必須として読んでいたため、
    公開 114 study の 81%（92 件）で Temperature の未記入を誤ってエラーにしていた。
    """
    assert I.MB_IR0018().validate(_proto_sub("LC-MS", "Chromatography", ""), CTX) == []


def test_ir0018_fires_when_a_required_parameter_is_defined():
    """定義を足せば効くこと（空定義でルールが壊れていないことの担保）。"""
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    ctx.definitions = copy.deepcopy(ctx.definitions)
    ctx.definitions["idf"]["protocol_parameters_required"] = {
        "MSI": {"Data processing": ["Data processing software"]}}
    msgs = [r["message"]
            for r in I.MB_IR0018().validate(_proto_sub("MSI", "Data processing", ""), ctx)]
    assert len(msgs) == 1 and "Data processing software" in msgs[0]


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


# --- 名前の無い Factor Value[] ---------------------------------------------

def _unnamed_sub(idf_name=None, values=("a", "b")):
    """`Factor Value[]`（[] の中身が空）を持つ SDRF。"""
    fields = {"Comment[Submission type]": ["LC-MS"]}
    if idf_name:
        fields["Experimental Factor Name"] = [idf_name]
    return Submission(idf=Idf(fields=fields, field_order=list(fields)),
                      sdrf=Sdrf(header=["Source Name", "Factor Value[]"],
                                rows=[["s1", v] for v in values]))


def test_unnamed_factor_value_column_is_reported_by_sr0007():
    """`Factor Value[]`（空名）は MB_SR0007（不正なユーザ定義列）が指摘する。

    以前は MB_CR0001 が `only in SDRF: (unnamed)` として拾っていたが、CR0001 を
    name マッチ限定にしたため、名前が無いこと自体は MB_SR0007 の担当に移した。
    sdrf.fields の `Factor Value\\[.*\\]` には当たるので MB_SR0006 では拾えない
    （＝誰も指摘しない状態にならないことをここで固定する）。
    """
    msgs = _msgs(_unnamed_sub(), S.MB_SR0007())
    assert len(msgs) == 1 and "Factor Value[]" in msgs[0]


def test_unnamed_factor_value_is_not_reported_by_cr0001():
    """空名は MB_CR0001 の照合集合に入れない（IDF 側に実名があっても片側分だけ出る）。"""
    msgs = _msgs(_unnamed_sub(idf_name="treatment"), C.MB_CR0001())
    assert len(msgs) == 1 and "only in IDF: treatment" in msgs[0]


def test_unnamed_factor_value_without_values_is_also_caught_by_sr0047():
    """空名かつ全行空なら MB_SR0047 も拾う（列名は Factor Value[] のまま出す）。"""
    msgs = _msgs(_unnamed_sub(values=("", "")), S.MB_SR0047())
    assert len(msgs) == 1 and "Factor Value[]" in msgs[0]


def test_unnamed_factor_value_with_constant_value_is_caught_by_sr0017():
    """空名でも値が全行一定なら MB_SR0017 の対象になる（抽出漏れが無いこと）。"""
    msgs = _msgs(_unnamed_sub(values=("a", "a")), S.MB_SR0017())
    assert len(msgs) == 1 and "Factor Value[]" in msgs[0]


# --- MB_IR0023: 任意項目の null を autofix 提案として報告する -----------------
#
# 暗黙に fixed/ を書き換えるだけでは登録者が次回も同じ書き方をするため、
# 「何をどう直したか」を message と annotation（Suggested value）に出す（bs の BS_R0001 と同じ）。

def _idf_only(fields):
    """IDF だけの最小 submission（_BASE_IDF に fields を上書き）。"""
    f = {k: list(v) for k, v in _BASE_IDF.items()}
    f.update({k: list(v) for k, v in fields.items()})
    return Submission(idf=Idf(fields=f, field_order=list(f)))


def _ir0023(sub):
    return I.MB_IR0023().validate(sub, CTX)


def test_ir0023_null_to_empty_field_is_autofix():
    """autofix_null_to_empty の項目（Experimental Factor Type）は値を消す提案になる。"""
    res = _ir0023(_idf_only({"Experimental Factor Type": ["missing"]}))
    assert len(res) == 1
    assert res[0]["autofix"] is True and res[0]["new_value"] == ""
    assert "value removed" in res[0]["message"]


def test_ir0023_not_recommended_null_becomes_missing():
    """非推奨 null（NA 等）は missing への補正提案。対象は任意項目のみ。"""
    res = _ir0023(_idf_only({"Comment[Related study]": ["NA"]}))
    assert len(res) == 1
    assert res[0]["new_value"] == "missing" and "Suggested: 'missing'" in res[0]["message"]


def test_ir0023_normalizes_accepted_null_spelling():
    """推奨 null の表記揺れ（Not Applicable）も正規表記へ揃える（bs の (a) 相当）。"""
    res = _ir0023(_idf_only({"Comment[Related study]": ["Not Applicable"]}))
    assert len(res) == 1
    assert res[0]["new_value"] == "not applicable"


def test_ir0023_already_canonical_null_is_warning_without_autofix():
    """既に正規表記の null は直すものが無いので warning のみ（autofix は付けない）。"""
    res = _ir0023(_idf_only({"Comment[Related study]": ["missing"]}))
    assert len(res) == 1 and not res[0].get("autofix")


def test_ir0023_skips_mandatory_fields():
    """必須項目の null は MB_IR0007（error）の担当なので MB_IR0023 は触らない。"""
    assert _ir0023(_idf_only({"Study Title": ["missing"]})) == []


def test_ir0023_ignores_real_values():
    assert _ir0023(_idf_only({"Comment[Related study]": ["MTBKS123"]})) == []


def test_write_fixed_matches_ir0023_proposal(tmp_path):
    """fixed/ の値が MB_IR0023 の提案（new_value）と一致すること（判定を共用しているため）。"""
    got = _write_and_read(tmp_path, ["Comment[Related study]\tNot Applicable"])
    assert got == ["Comment[Related study]\tnot applicable"]


# --- MB_IR0038 / MB_CR0004: 再解析元 study の参照表記 -----------------------
#
# Comment[Related study] は `DB:ID` 形式で書く。MetaboBank の study accession は同じ DB なので
# `MetaboBank:` prefix を付けても付けなくてもよい（特別扱い）。DB 名の CV 化は未実施で、
# キュレータが入れる項目なのでチェックは緩く warning 止まり。

def _related(*values):
    return _idf_only({"Comment[Related study]": list(values)})


@pytest.mark.parametrize("v", [
    "MTBKS123",             # bare の MetaboBank accession
    "MetaboBank:MTBKS123",  # prefix 付きでも同じ
    "GEO:GSE12345",         # 他 DB は DB:ID
    "doi:10.1093/x",        # ID 側に記号が入っても可
    "MTBKS123:label",       # 緩い判定なので DB:ID として通る
])
def test_ir0038_accepts_valid_related_study(v):
    assert I.MB_IR0038().validate(_related(v), CTX) == []


@pytest.mark.parametrize("v", [
    "E-GEAD-123",   # `:` が無く MTBKS でもない
    "MTBKSabc",     # MTBKS＋数字でない
    "mtbks1",       # MetaboBank accession は case-sensitive（`:` も無いので DB:ID でもない）
    "free text",
    "foo:",         # ID 側が空
    ":bar",         # DB 側が空
])
def test_ir0038_warns_on_invalid_related_study(v):
    msgs = [r["message"] for r in I.MB_IR0038().validate(_related(v), CTX)]
    assert len(msgs) == 1 and "DB:ID" in msgs[0]


@pytest.mark.parametrize("v", ["mtbks1", "MetaboBank:mtbks1", "metabobank:MTBKS1"])
def test_metabobank_accession_is_case_sensitive(v):
    """MetaboBank accession の特別扱いは case-sensitive。

    `MetaboBank:MTBKS1` / `MTBKS1` の表記でのみ accession として扱う。表記揺れは
    accession に正規化しないので、MB_CR0004 の突合でも一致扱いにならない。
    （`:` を含む形は DB:ID として MB_IR0038 は通る。DB 名を CV 化したら弾けるようになる）
    """
    from apps.metabobank.rules.base import mtbks_accession
    assert mtbks_accession(v) is None


def test_ir0038_skips_empty_and_null():
    """空値は任意項目なので素通し。null value は MB_IR0023 の担当。"""
    assert I.MB_IR0038().validate(_related(""), CTX) == []
    assert I.MB_IR0038().validate(_related("missing"), CTX) == []


def test_ir0038_reports_each_value():
    res = I.MB_IR0038().validate(_related("MTBKS1", "bad one", "also bad"), CTX)
    assert len(res) == 2


def test_cr0004_matches_prefixed_metabobank_accession():
    """IDF 側が `MetaboBank:MTBKS123` でも SDRF 側の `MTBKS123:...` と一致扱いになること。

    prefix の有無で不一致と判定されると、正しい書き方をしたのに warning が出てしまう。
    """
    fields = {k: list(v) for k, v in _BASE_IDF.items()}
    fields["Comment[Related study]"] = ["MetaboBank:MTBKS123"]
    sub = Submission(idf=Idf(fields=fields, field_order=list(fields)),
                     sdrf=Sdrf(header=["Source Name", "Comment[Reanalysis of]"],
                               rows=[["s1", "MTBKS123:label"]]))
    assert C.MB_CR0004().validate(sub, CTX) == []


def test_cr0004_still_reports_a_real_mismatch():
    fields = {k: list(v) for k, v in _BASE_IDF.items()}
    fields["Comment[Related study]"] = ["MetaboBank:MTBKS123"]
    sub = Submission(idf=Idf(fields=fields, field_order=list(fields)),
                     sdrf=Sdrf(header=["Source Name", "Comment[Reanalysis of]"],
                               rows=[["s1", "MTBKS999:label"]]))
    msgs = [r["message"] for r in C.MB_CR0004().validate(sub, CTX)]
    assert len(msgs) == 1 and "MTBKS999" in msgs[0]
