"""ddbj --scope source（COMMON と source だけを検証、2026-11-04）。

.ann は最後まで読むが、COMMON とエントリ部の source / メタデータ feature の行だけを残す。
捨てる行は空行にして行番号を保つ（レポートの Line と autofix の行指定が通常実行と揃う）。
"""
import argparse

import pytest

from apps.ddbj.cli import _build_parser, _resolve_scope
from apps.ddbj.preprocessor import keep_source_scope_lines, preprocess_files

ANN = [
    "COMMON\tSUBMITTER\t\tab_name\tMishima,H.",
    "\tsource\t1..E\torganism\tMus musculus",
    "seq1\tsource\t1..10\torganism\tMus musculus",
    "\t\t\tmol_type\tgenomic DNA",
    "\tCDS\t1..9\tproduct\tfoo",
    "\t\t\tcodon_start\t1",
    "\tDBLINK\t\tbiosample\tSAMD00000001",
    "seq2\tCDS\t1..9\tproduct\tbar",
    "\tsource\t1..10\torganism\tHomo sapiens",
    "mol_type\tgenomic DNA",
]


def test_keep_source_scope_lines():
    out = keep_source_scope_lines(ANN)
    assert len(out) == len(ANN)
    assert out[:4] == ANN[:4]
    # CDS とその qualifier は空行（行番号は保つ）
    assert out[4] == "" and out[5] == ""
    # エントリ側のメタデータ feature は残す
    assert out[6] == ANN[6]
    # entry の最初の行が CDS のときは、entry 名を次に残す行（source）へ移す
    assert out[7] == ""
    assert out[8] == "seq2\tsource\t1..10\torganism\tHomo sapiens"
    # 列数の足りない行（ANN0140）はそのまま
    assert out[9] == ANN[9]


def test_header_and_comment_lines_kept():
    lines = ["Entry\tFeature\tLocation\tQualifier\tValue", "# note", ""] + ANN[:2]
    assert keep_source_scope_lines(lines) == lines


def test_preprocess_source_only_does_not_read_fasta(tmp_path):
    ann = tmp_path / "a.ann"
    ann.write_text("\n".join(ANN) + "\n", encoding="utf-8")
    lines, fasta, _ = preprocess_files(str(ann), str(tmp_path / "missing.fasta"), source_only=True)
    assert fasta == ""
    assert len(lines) == len(ANN) and lines[4] == ""
    # フェーズ 3（fixed/ の .ann）は全行を読み、FASTA は読まない
    full, fasta, _ = preprocess_files(str(ann), None, read_fasta=False)
    assert fasta == "" and full[4].startswith("\tCDS")


def _scope(argv):
    args = _build_parser().parse_args(argv)
    _resolve_scope(args)
    return args.scope, args.common_only, args.source_only, args.ann_only


def test_resolve_scope():
    assert _scope(["x"]) == ("all", False, False, False)
    assert _scope(["--scope", "source", "x"]) == ("source", False, True, True)
    assert _scope(["--scope", "common", "x"]) == ("common", True, False, True)
    # --common-only は後方互換で --scope common と同じ
    assert _scope(["--common-only", "x"]) == ("common", True, False, True)
    assert _scope(["--common-only", "--scope", "common", "x"]) == ("common", True, False, True)


def test_common_only_conflicts_with_other_scope():
    with pytest.raises(SystemExit):
        _scope(["--common-only", "--scope", "source", "x"])
