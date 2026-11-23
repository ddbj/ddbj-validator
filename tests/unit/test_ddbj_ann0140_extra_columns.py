"""ANN0140（列数の誤り）で 6 列目以降の値を捨てないこと。

行頭のタブが 1 つ多い行（列が右にずれて 6 列）を先頭 5 列で切ると、6 列目の値（product や
note の値）が fixed/ から消えていた（ddbj/ddbj-validator#15）。6 列目以降が空（末尾タブ）の
ときだけ切り、値があるときは行をそのまま残す（ANN0140 は ERROR のまま）。
"""
from apps.ddbj.preprocessor import preprocess_files

_FASTA = ">seq1\n" + "ATGC" * 50 + "\n//\n"
_HEAD = [
    "seq1\tsource\t1..200\torganism\tEscherichia coli",
    "\t\t\tmol_type\tgenomic DNA",
]


def _run(tmp_path, extra_line):
    ann = tmp_path / "t.ann"
    ann.write_text("\n".join(_HEAD + [extra_line]) + "\n")
    fasta = tmp_path / "t.fasta"
    fasta.write_text(_FASTA)
    lines, _, warns = preprocess_files(str(ann), str(fasta))
    codes = [w.get("rule") or w.get("code") for w in warns]
    return lines, codes, warns


def test_shifted_row_keeps_its_value(tmp_path):
    lines, codes, _ = _run(tmp_path, "\t\tmisc_feature\t100..150\tnote\tshifted row")
    assert any("shifted row" in l for l in lines)
    assert "ANN0140" in codes


def test_trailing_empty_columns_are_still_trimmed(tmp_path):
    lines, codes, _ = _run(tmp_path, "\t\t\tnote\tsome value\t\t")
    assert "\t\t\tnote\tsome value" in lines
    assert "ANN0140" in codes
