"""ANN5270 の自動修正で join の他のエキソンを消さないこと（ddbj/ddbj-validator#14）。

エキソンの 1 つが assembly_gap に重なると、修正後の location がその 1 区間だけになっていた。
重なった区間だけを gap の手前まで縮め、ほかの区間と join / complement は残す。
`<` / `>` を付けるのは feature 全体の端の区間だけで、内部の区間が重なるときは自動修正を出さない。
"""
import random

from apps.ddbj.parser import parse_ddbj_submission
from apps.ddbj.rules.annotation import ANN5270

random.seed(0)
_SEQ = "".join(random.choice("acgt") for _ in range(3000))
_SEQ = _SEQ[:1000] + "n" * 100 + _SEQ[1100:]
_FASTA = ">seq1\n" + _SEQ + "\n//\n"


def _fix(location, feature="mRNA"):
    ann = [
        "seq1\tsource\t1..3000\torganism\tEscherichia coli",
        "\t\t\tmol_type\tgenomic DNA",
        "\tassembly_gap\t1001..1100\testimated_length\tunknown",
        "\t\t\tgap_type\twithin scaffold",
        "\t\t\tlinkage_evidence\tpaired-ends",
        f"\t{feature}\t{location}\tproduct\thypothetical protein",
    ]
    records, _errors, _fasta_only = parse_ddbj_submission(_FASTA, "t.ann", ann)
    res = ANN5270().validate(records["seq1"], {})
    assert res, "ANN5270 should warn"
    fixes = [r["new_value"] for r in res if r.get("autofix")]
    return fixes


def test_right_end_of_last_exon_in_gap_keeps_other_exons():
    assert _fix("join(200..400,500..600,900..1050)") == ["join(200..400,500..600,900..>1000)"]


def test_left_end_of_first_exon_in_gap_keeps_other_exons():
    assert _fix("join(1050..1200,1500..1700,2000..2100)") == ["join(<1101..1200,1500..1700,2000..2100)"]


def test_complement_join_is_kept():
    assert _fix("complement(join(1050..1200,1500..1700))") == ["complement(join(<1101..1200,1500..1700))"]
    assert _fix("complement(join(200..400,900..1050))", feature="CDS") == ["complement(join(200..400,900..>1000))"]


def test_inner_edge_in_gap_is_not_autofixed():
    # 内部のエキソンの端や、端のエキソンでもイントロン側の端が gap にかかる場合は警告だけ
    assert _fix("join(200..400,800..1050,1500..1700)") == []
    assert _fix("join(200..400,800..900,1050..1700)") == []


def test_existing_partial_marks_are_kept():
    assert _fix("join(<1..400,500..600,900..1050)") == ["join(<1..400,500..600,900..>1000)"]


def test_single_interval_unchanged_behavior():
    assert _fix("1050..1700") == ["<1101..1700"]
    assert _fix("complement(800..1050)") == ["complement(800..>1000)"]
