"""ddbj --common-only（COMMON だけを検証、2026-10-30）。

エントリ部が大きいと時間がかかるので、COMMON だけを読んで検証する。
.ann は最初の COMMON 以外のエントリ行で読むのをやめ、FASTA は読まない（無くてもよい）。
エントリ部が要るルール（requires_entries）は登録しない。
"""
from apps.ddbj.preprocessor import preprocess_files, starts_non_common_entry
from apps.ddbj.file_manager import find_file_pairs
from apps.ddbj.db_metadata import fast_extract_db_keys
from apps.ddbj.context import ValidationContext
from apps.ddbj.validator import Validator

ANN = (
    "Entry\tFeature\tLocation\tQualifier\tValue\n"
    "COMMON\tSUBMITTER\t\tab_name\tMishima,H.\n"
    "\t\t\tcontact\tHanako Mishima\n"
    "# comment\n"
    "\tDBLINK\t\tproject\tPRJDB1\n"
    "\t\t\tbiosample\tSAMD00000001\n"
    "seq1\tsource\t1..10\torganism\tMus musculus\n"
    "\tDBLINK\t\tbiosample\tSAMD00000002\n"
)


def test_starts_non_common_entry():
    assert starts_non_common_entry("seq1\tsource\t1..10\torganism\tMus musculus")
    assert not starts_non_common_entry("COMMON\tSUBMITTER\t\tab_name\tX")
    assert not starts_non_common_entry("\t\t\tcontact\tX")
    assert not starts_non_common_entry("# seq1\tsource")
    assert not starts_non_common_entry("")
    # ヘッダー行は auto-cleanup で消す行なので、エントリの開始とはみなさない
    assert not starts_non_common_entry("Entry\tFeature\tLocation\tQualifier\tValue")


def test_preprocess_common_only_stops_at_first_entry_without_fasta(tmp_path):
    ann = tmp_path / "a.ann"
    ann.write_text(ANN, encoding="utf-8")
    lines, fasta, _ = preprocess_files(str(ann), None, common_only=True)
    assert fasta == ""
    assert len(lines) == 6
    assert not any(line.startswith("seq1") for line in lines)


def test_find_file_pairs_without_fasta(tmp_path):
    (tmp_path / "a.ann").write_text(ANN, encoding="utf-8")
    (tmp_path / "b.ann").write_text(ANN, encoding="utf-8")
    (tmp_path / "b.fasta").write_text(">seq1\nacgtacgtac\n//\n", encoding="utf-8")
    (tmp_path / "c.fasta").write_text(">seq1\nacgtacgtac\n//\n", encoding="utf-8")
    pairs, errors = find_file_pairs(tmp_path, require_fasta=False)
    assert errors == []
    assert sorted((p[0].split("/")[-1], p[1] and p[1].split("/")[-1]) for p in pairs) == [
        ("a.ann", None), ("b.ann", "b.fasta")]
    # 通常は FASTA の無い .ann を従来どおりエラーにする
    _, errors = find_file_pairs(tmp_path)
    assert {e["rule"] for e in errors} == {"ANN0020"}


def test_fast_extract_common_only_skips_entries_and_organisms(tmp_path):
    ann = tmp_path / "a.ann"
    ann.write_text(ANN, encoding="utf-8")
    keys = fast_extract_db_keys(str(ann), None, common_only=True)
    assert keys["samds"] == {"SAMD00000001"}
    assert keys["projects"] == {"PRJDB1"}
    assert keys["organisms"] == set()


def test_requires_entries_rules_not_registered():
    ids = lambda v: {r.rule_id for r in v.active_rules}
    normal = ids(Validator(ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)))
    common = ids(Validator(ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True, common_only=True)))
    dropped = {"ANN0410", "ANN0450", "ANN0470", "ANN1010", "ENTRY_CONSISTENCY_MASTER", "FASTA_FORMAT_MASTER"}
    assert dropped <= normal
    assert not (dropped & common)
    assert {"ANN0230", "ANN0347", "ANN3021"} <= common
