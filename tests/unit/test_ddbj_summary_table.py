"""--summary-table（reports/validation_report_table.txt / .tsv）（2026-11-10）。"""
import json

from apps.ddbj.reporter import ValidationReporter


def _jsonl(path, file, entries, results):
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({"type": "result", "data": {"file": file, **r}}) + "\n")
        f.write(json.dumps({"type": "file_meta", "data": {"file": file, "entries": entries}}) + "\n")
    return str(path)


def _per_entry(rule, n, level="INFO", feature_type="source", qualifier="ff_definition"):
    return [{"rule": rule, "level": level, "entry": f"e{i}", "feature_type": feature_type,
             "qualifier": qualifier, "line_number": i, "message": "The 'ff_definition' qualifier exists."}
            for i in range(n)]


_DBLINK = {"rule": "ANN0470", "level": "WARNING", "entry": "COMMON", "feature_type": "DBLINK",
           "message": "Missing SRA Run accession."}


def test_files_differing_only_in_entry_count_share_a_pattern(tmp_path):
    paths = [
        _jsonl(tmp_path / "a.jsonl", "a.ann", 3, [_DBLINK] + _per_entry("ANN2670", 3)),
        _jsonl(tmp_path / "b.jsonl", "b.ann", 5, [_DBLINK] + _per_entry("ANN2670", 5)),
        # c は一部の entry だけ → 別 pattern
        _jsonl(tmp_path / "c.jsonl", "c.ann", 5, [_DBLINK] + _per_entry("ANN2670", 2)),
        # d は何も出ない
        _jsonl(tmp_path / "d.jsonl", "d.ann", 1, []),
    ]
    rep = ValidationReporter(out_dir=tmp_path)
    rep.write_table_report(paths, header_info="Version: x\n", set_str="4 file sets")
    txt = (tmp_path / "reports" / "validation_report_table.txt").read_text(encoding="utf-8")

    # rule id ごと: WARNING が INFO より先、Files は出たファイル数 / 全ファイル数
    by_rule = txt.split("## Summary by rule id")[1].split("## Files by pattern")[0]
    assert by_rule.index("ANN0470") < by_rule.index("ANN2670")
    assert "| 3/4   | 3     | Missing SRA Run accession." in by_rule
    assert "| 3/4   | 10    | The 'ff_definition' qualifier exists." in by_rule

    pats = txt.split("## Files by pattern")[1]
    assert "Pattern 1 (2 files, 3-5 entries): ANN0470 1, ANN2670 all entries\n  a, b\n" in pats
    assert "ANN2670 2 (2/5 entries)\n  c\n" in pats
    assert "(1 file, 1 entry): no messages\n  d\n" in pats


def test_tsv_is_a_file_by_rule_matrix(tmp_path):
    paths = [_jsonl(tmp_path / "a.jsonl", "a.ann", 3, [_DBLINK] + _per_entry("ANN2670", 3))]
    rep = ValidationReporter(out_dir=tmp_path)
    rep.write_table_report(paths)
    rows = [l.split("\t") for l in (tmp_path / "reports" / "validation_report_table.tsv").read_text().splitlines()]
    assert rows[0][:6] == ["#", "File", "Entries", "Pattern", "ANN0470 (WARNING, DBLINK)",
                           "ANN2670 (INFO, source:ff_definition)"]
    assert rows[1][:6] == ["1", "a", "3", "1", "1", "3"]
    # 末尾は level ごとの件数（FATAL, ERROR, WARNING, INFO, AUTO-CLEANUP）
    assert rows[1][-5:] == ["0", "0", "1", "3", "0"]
