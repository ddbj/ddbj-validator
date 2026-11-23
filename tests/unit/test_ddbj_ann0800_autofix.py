"""ANN0800（Assembly Method の版の書式）の自動修正。

ツール名と版を `_` や `-` でつないだ値（`Flye_v2.9.6`）で、区切り文字がツール名の側に残り
`Flye_ v. 2.9.6` になっていた（ddbj/ddbj-validator#16）。
"""
from apps.ddbj.autofix.format import propose_format_errors
from apps.ddbj.parser import parse_ddbj_submission

_FASTA = ">seq1\n" + "ATGC" * 10 + "\n//\n"


def _suggest(method):
    ann = [
        "COMMON\tST_COMMENT\t\ttagset_id\tGenome-Assembly-Data",
        f"\t\t\tAssembly Method\t{method}",
        "seq1\tsource\t1..40\torganism\tEscherichia coli",
        "\t\t\tmol_type\tgenomic DNA",
    ]
    records, _errors, _fasta_only = parse_ddbj_submission(_FASTA, "t.ann", ann)
    props = [p for p in propose_format_errors(records, "t.ann") if p.get("rule") == "ANN0800"]
    return props[0]["new_value"] if props else None


def test_underscore_before_v_is_dropped():
    assert _suggest("Flye_v2.9.6-b1802") == "Flye v. 2.9.6-b1802"


def test_hyphen_before_v_is_dropped():
    assert _suggest("SPAdes-v3.15.5") == "SPAdes v. 3.15.5"


def test_hyphen_inside_tool_name_is_kept():
    assert _suggest("Platanus-allee v2.2.2") == "Platanus-allee v. 2.2.2"


def test_space_separated_unchanged_behavior():
    assert _suggest("Flye v2.9") == "Flye v. 2.9"
    assert _suggest("Shovill v.1.4.2") == "Shovill v. 1.4.2"
