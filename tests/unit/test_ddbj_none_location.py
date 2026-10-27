"""location を読めなかった feature（location=None）でルールが例外を出さないこと（2026-10-27）。

NSUB004118 で tRNA の location が `join(complement(..),complement(..))` と書かれていて読めず
（ANN2020 の error）、ANN2610 が `len(None)` で 9 entry 分落ちていた。同じく location の長さや
配列を None チェック無しで使っていた ANN2600 / ANN2620 / ANTICODON_VALIDATOR / ANN5220 /
ANN5230 / ANN5240 もあわせて直した。読めない location は ANN2020 が報告済みなので、
これらのルールはその feature を飛ばす。
"""
import pytest

from apps.ddbj.context import ValidationContext
from apps.ddbj.parser import parse_ddbj_submission
from apps.ddbj.rules.annotation import (
    ANN2600, ANN2610, ANN2620, ANN5220, ANN5230, ANN5240, ANTICODON_VALIDATOR,
)

# NSUB004118 と同じ形の、complement() を join() の中に書いた location
_BAD = "join(complement(10..60),complement(100..150))"
_SEQ = "atg" + "acgt" * 149 + "taa"   # 600 bp


def _ann(bad):
    return [
        "COMMON\tDBLINK\t\tbiosample\tSAMD00000001",
        "seq1\tsource\t1..600\torganism\tEscherichia coli",
        "\t\t\tmol_type\tgenomic DNA",
        f"\trRNA\t{bad}\tproduct\t16S ribosomal RNA",
        f"\ttRNA\t{bad}\tproduct\ttRNA-Met",
        "\t\t\tanticodon\t(pos:20..22,aa:Met,seq:cat)",
        f"\ttmRNA\t{bad}\tproduct\ttmRNA",
        f"\tassembly_gap\t{bad}\testimated_length\tunknown",
        f"\tassembly_gap\t{bad}\testimated_length\tunknown",
        f"\tassembly_gap\t{bad}\testimated_length\t100",
        f"\tassembly_gap\t{bad}\testimated_length\t100",
    ]


@pytest.fixture(scope="module")
def ctx():
    return ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)


def _record(ctx, bad):
    records, errors, _ = parse_ddbj_submission(f">seq1\n{_SEQ}\n//\n", "t.ann", _ann(bad), ddbj_dict=ctx.ddbj_dict)
    return records["seq1"], errors


RULES = [ANN2600, ANN2610, ANN2620, ANTICODON_VALIDATOR, ANN5220, ANN5230, ANN5240]


@pytest.mark.parametrize("bad", [_BAD, "abc", "100..", "complement(join(10..60,100..))"])
@pytest.mark.parametrize("rule_cls", RULES, ids=lambda c: c.__name__)
def test_rules_skip_unparsable_location(ctx, rule_cls, bad):
    record, errors = _record(ctx, bad)
    # 前提: location は読めず None になり、ANN2020 が報告している
    assert all(f.location is None for f in record.features if f.type != "source")
    assert any(e.get("rule") == "ANN2020" for e in errors)
    # 例外を出さず、その feature については何も報告しない
    assert rule_cls().validate(record, ctx) == []


def test_parsable_location_is_still_checked(ctx):
    # 読める location では従来どおり長さを見る（tRNA 10 bp は 50-150 bp の範囲外）
    record, _ = _record(ctx, "1..10")
    res = ANN2610().validate(record, ctx)
    assert [r["rule"] for r in res] == ["ANN2610"]
    assert "10 bp" in res[0]["message"]
