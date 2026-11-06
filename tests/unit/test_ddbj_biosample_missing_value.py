"""ANN1130: BioSample 側の属性が missing 値（"missing: human-identifiable" 等）のときの突合（2026-11-06）。

NSUB004134 / SAMD02115205 で、BioSample の collection_date が 'missing: human-identifiable' なのに
「BioSample attribute is empty (BioSample: '')」と出ていた。missing 値は ann へ書き写さない（autofix しない）が、
値の突合は行う。missing 値は term ごとに値が無い理由が違うので、完全一致のときだけ一致とし、
別の missing 値・実際の値・空はすべて warning にする。
"""
from types import SimpleNamespace

import pytest

from apps.ddbj.autofix.external_db import propose_qualifiers_updates

_SAMD = "SAMD00000001"


def _records(collection_date):
    dblink = SimpleNamespace(type="DBLINK", qualifiers={"biosample": [_SAMD]}, line_number=1)
    quals = {"organism": ["Escherichia coli"]}
    if collection_date is not None:
        quals["collection_date"] = [collection_date]
    source = SimpleNamespace(type="source", line_number=5, qualifiers=quals)
    rec = SimpleNamespace(id="seq1", features=[dblink, source],
                          features_by_type={"DBLINK": [dblink], "source": [source]})
    return {"seq1": rec}


def _date_warnings(ann_val, bs_val):
    bs = {_SAMD: {"collection_date": bs_val}}
    props, warns, _skips = propose_qualifiers_updates(_records(ann_val), bs, "t.ann")
    # missing 値は ann へ書き写さないので autofix 提案は出ない
    assert [p for p in props if p["qualifier"] == "collection_date"] == []
    return [w["message"] for w in warns if w["qualifier"] == "collection_date"]


def test_same_missing_value_on_both_sides_is_not_reported():
    assert _date_warnings("missing: human-identifiable", "missing: human-identifiable") == []


@pytest.mark.parametrize("ann_val", [
    "2025-12-05",                  # 実際の値
    "missing: control sample",     # 理由の違う missing 値
    "missing",                     # term の無い missing
    "not collected",               # 別の base term
    "",                            # 空
])
def test_anything_but_the_same_missing_value_is_reported(ann_val):
    assert _date_warnings(ann_val, "missing: human-identifiable") == [
        "The 'collection_date' qualifier value does not match the BioSample attribute value. "
        f"(ann: '{ann_val}', BioSample: 'missing: human-identifiable')"]


def test_absent_qualifier_against_biosample_missing_value_is_reported():
    assert _date_warnings(None, "missing: human-identifiable") == [
        "The 'collection_date' qualifier is missing but the BioSample attribute has a value. "
        "(ann: '', BioSample: 'missing: human-identifiable')"]


def test_ann_missing_value_against_empty_biosample_is_reported():
    assert _date_warnings("missing: human-identifiable", "") == [
        "The 'collection_date' qualifier has a value but the BioSample attribute is empty. "
        "(ann: 'missing: human-identifiable', BioSample: '')"]
