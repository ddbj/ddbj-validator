"""結果 JSON の annotation 骨格テスト（MetaboBank）。

BS と同じ骨格にするため、JSON では `message` を rule の固定文にし、括弧書きの個別情報は
`annotation` 配列へ移す（同じ文で束ねられるようにするため）。内部 dict の `message` は
1 行形式のまま残し、reporter が JSON を組むときに `desc`→message / `message`→detail と写す。

ここで固定するのは 3 点:
  1. 全 rule が annotation パターン表に載っていること（載っていないと annotation が空になる）
  2. パターンごとの annotation の並びとキー名
  3. message / detail / reference の写し方

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit/test_metabobank_annotation.py`
"""
import inspect

import pytest

from apps.metabobank import reporter as R
from apps.metabobank.context import ValidationContext
from apps.metabobank.rules import base as B
from apps.metabobank.rules import biosample as RB, cross as RC, idf as RI, reference_db as RR, sdrf as RS
from apps.metabobank.rules.base import MbRule
from apps.metabobank.validator import Validator

CTX = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)


def _defined_rule_ids():
    out = set()
    for mod in (RI, RS, RC, RB, RR):
        for o in vars(mod).values():
            if inspect.isclass(o) and issubclass(o, MbRule) and getattr(o, "rule_id", "MB_RXXXX") != "MB_RXXXX":
                out.add(o.rule_id)
    return out


# --- パターン表の網羅 -------------------------------------------------------

def test_every_rule_has_an_annotation_pattern():
    """全 rule がパターン表に載っていること。

    漏れると annotation が黙って空になり、登録システムの新描画で個別情報が出ない。
    """
    missing = sorted(_defined_rule_ids() - set(B.ANNOTATION_PATTERNS))
    assert not missing, f"パターン表に無い rule: {missing}"


def test_pattern_table_has_no_unknown_rule():
    """存在しない rule_id が表に残っていないこと（削除済み rule の残骸検出）。"""
    unknown = sorted(set(B.ANNOTATION_PATTERNS) - _defined_rule_ids())
    assert not unknown, f"コードに無い rule: {unknown}"


def test_registered_rules_are_all_in_the_table():
    ids = {r.rule_id for r in Validator(CTX).active_rules}
    assert not ids - set(B.ANNOTATION_PATTERNS)


def test_every_pattern_name_has_a_builder():
    assert set(B.ANNOTATION_PATTERNS.values()) <= set(R._BUILDERS)


def test_unknown_rule_falls_back_to_general():
    assert B.annotation_pattern("MB_XX9999") == "general"


# --- パターンごとの annotation ---------------------------------------------

def test_sdrf_cell_annotation_order_and_keys():
    r = {"rule_id": "MB_SR0046", "line": 3, "assay": "as1",
         "column": "Parameter Value[Scan polarity]", "value": "both"}
    assert R.annotation(r) == [
        {"key": "Line", "value": "3"},
        {"key": "Assay Name", "value": "as1"},
        {"key": "Column", "value": "Parameter Value[Scan polarity]"},
        {"key": "Value", "value": "both"},
    ]


def test_sdrf_cell_falls_back_to_source_name():
    """Assay Name 列が無い SDRF では Source Name を出す。"""
    r = {"rule_id": "MB_SR0046", "line": 1, "assay": "", "source_name": "s1",
         "column": "c", "value": "v"}
    assert R.annotation(r)[1] == {"key": "Source Name", "value": "s1"}


def test_sdrf_cell_biosample_mismatch_adds_biosample_columns():
    """MB_SR0023 は BioSample / BioSample value と Suggested value を足す。"""
    r = {"rule_id": "MB_SR0023", "line": 2, "assay": "as1",
         "column": "Characteristics[strain]", "value": "K12",
         "samd": "SAMD00000001", "bs_value": "K-12",
         "autofix": True, "new_value": "K-12", "target_key": "Value"}
    anno = R.annotation(r)
    assert {"key": "BioSample", "value": "SAMD00000001"} in anno
    assert {"key": "BioSample value", "value": "K-12"} in anno
    assert anno[-1] == {"key": "Suggested value", "suggested_value": ["K-12"],
                        "target_key": "Value", "is_auto_annotation": True}


def test_sdrf_column_annotation():
    r = {"rule_id": "MB_SR0017", "column": "Factor Value[dose]", "rows": 12}
    assert R.annotation(r) == [{"key": "Column", "value": "Factor Value[dose]"},
                               {"key": "Rows", "value": "12"}]


def test_idf_field_annotation():
    r = {"rule_id": "MB_IR0013", "field": "Public Release Date", "value": "2026/01/01"}
    assert R.annotation(r) == [{"key": "Field", "value": "Public Release Date"},
                               {"key": "Value", "value": "2026/01/01"}]


def test_idf_protocol_annotation():
    r = {"rule_id": "MB_IR0018", "protocol_type": "Data processing",
         "param": "Data processing software"}
    assert R.annotation(r) == [{"key": "Protocol Type", "value": "Data processing"},
                               {"key": "Parameter", "value": "Data processing software"}]


def test_idf_sdrf_annotation_shows_which_side():
    assert R.annotation({"rule_id": "MB_CR0001", "sdrf_only": "dose"}) == \
        [{"key": "SDRF", "value": "dose"}]
    assert R.annotation({"rule_id": "MB_CR0001", "idf_only": "treatment"}) == \
        [{"key": "IDF", "value": "treatment"}]


def test_general_pattern_has_no_annotation():
    assert R.annotation({"rule_id": "MB_IR0037"}) == []


# --- JSON への写し方 --------------------------------------------------------

def test_json_extra_maps_desc_to_message_and_keeps_detail():
    r = {"rule_id": "MB_IR0013", "desc": "Invalid date format. Use YYYY-MM-DD.",
         "message": "Invalid date format. Use YYYY-MM-DD. (Public Release Date: '2026/01/01')",
         "field": "Public Release Date", "value": "2026/01/01"}
    e = R._json_extra(r)
    assert e["message"] == "Invalid date format. Use YYYY-MM-DD."
    assert e["detail"] == r["message"]
    assert e["reference"] == "https://www.ddbj.nig.ac.jp/metabobank/validation-e.html#MB_IR0013"
    assert e["annotation"]


def test_json_extra_omits_detail_when_identical_to_message():
    """括弧書きが無い rule（MB_IR0037 等）は detail を付けない。"""
    r = {"rule_id": "MB_IR0037", "desc": "Email address is required for the submitter.",
         "message": "Email address is required for the submitter."}
    e = R._json_extra(r)
    assert "detail" not in e and e["message"] == r["desc"]


# --- rule が desc を必ず載せること ------------------------------------------

def test_result_always_carries_desc():
    """MbRule.result は rule の固定文を desc に載せる（JSON の message の出所）。"""
    class _Dummy(MbRule):
        rule_id = "MB_IR0003"; level = "error"; target = "IDF"
        description = "Field names are duplicated."
    assert _Dummy().result()["desc"] == "Field names are duplicated."
    assert _Dummy().result(message="x (y)")["desc"] == "Field names are duplicated."


@pytest.mark.parametrize("mod", [RI, RS, RC])
def test_no_rule_overrides_desc_with_a_variable_text(mod):
    """desc は固定文であること（result に desc= を渡して上書きしている rule が無いか）。

    MB_SR0021 は summary 集約用に desc= を明示しているが、値は self.description と同じ。
    """
    src = inspect.getsource(mod)
    for line in src.split("\n"):
        if "desc=" in line and "self.description" not in line:
            pytest.fail(f"desc を固定文以外で渡している: {line.strip()}")
