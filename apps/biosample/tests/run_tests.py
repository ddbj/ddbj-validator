#!/usr/bin/env python3
"""BioSample validator 専用 E2E ハーネス（ddbj とは完全分離）。

- 対象: apps/biosample/tests/<BS_Rxxxx>/ 配下の fixture（*.xml / *.txt(TSV)）。
- 命名: `BS_Rxxxx_n.pass.xml` / `BS_Rxxxx_n.fail.xml`（.txt も可）。
  ディレクトリ名のルール ID を「対象ルール」とし、
    pass → 対象ルールが発火しないこと、fail → 対象ルールが発火すること、を検証。
- 実行は in-process（パイプライン直呼び）。既定は local モード（DB 非依存ルールの検証）。
ミスマッチが 1 件でもあれば終了コード 1。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.biosample.context import ValidationContext
from apps.biosample import xml_reader, tsv_to_xml
from apps.biosample.validator import Validator

GREEN = "\033[92m"; RED = "\033[91m"; END = "\033[0m"

# 決定的テストのための mock taxonomy（DB/NCBI に依存しない）。
# fixture が使う organism を網羅すること。
MOCK_TAX = {
    "Arabidopsis thaliana": {"tax_id": "3702", "rank": "species", "scientific_name": "Arabidopsis thaliana",
                              "is_species_or_below": True, "status": "valid", "lineage": "Eukaryota; Viridiplantae"},
    "Escherichia coli": {"tax_id": "562", "rank": "species", "scientific_name": "Escherichia coli",
                          "is_species_or_below": True, "status": "valid", "lineage": "Bacteria; Proteobacteria"},
    "Homo sapiens": {"tax_id": "9606", "rank": "species", "scientific_name": "Homo sapiens",
                     "is_species_or_below": True, "status": "valid", "lineage": "Eukaryota; Metazoa; Homo"},
    "Homo": {"tax_id": "9605", "rank": "genus", "scientific_name": "Homo",
             "is_species_or_below": False, "status": "invalid_rank", "lineage": "Eukaryota; Metazoa"},
}


def _fired_rules(fixture_path):
    """fixture を検証し、発火したルール ID 集合を返す。
    taxonomy ルールも有効化（skip_ncbi=False）し、mock taxonomy を注入して決定的に評価する。
    """
    ctx = ValidationContext(skip_db=False, skip_ncbi=False, skip_auth=True, tax_data=dict(MOCK_TAX))
    path = Path(fixture_path)
    if path.suffix.lower() in (".txt", ".tsv"):
        import tempfile
        xml_text = tsv_to_xml.tsv_to_xml(str(path))
        sub_id, _ = tsv_to_xml.parse_filename(str(path))
        tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
        tmp.write(xml_text or ""); tmp.close()
        submission, pre = xml_reader.parse_xml(tmp.name, submission_id=sub_id)
    else:
        submission, pre = xml_reader.parse_xml(str(path))
    fired = {r["rule_id"] for r in pre}
    if submission is not None:
        fired |= {r["rule_id"] for r in Validator(ctx).run(submission)}
    return fired


def main(target=None):
    test_dirs = sorted(d for d in HERE.iterdir()
                       if d.is_dir() and d.name.startswith("BS_R")
                       and (target is None or d.name == target))
    passed = mismatched = 0
    errors = []
    print(f"\n=== BioSample Validator E2E ({'all' if not target else target}) ===")
    for d in test_dirs:
        rule_id = d.name
        print(f"Testing: {d.name}")
        for fx in sorted(list(d.glob("*.xml")) + list(d.glob("*.txt"))):
            parts = fx.name.split(".")
            if len(parts) < 3 or parts[-2] not in ("pass", "fail"):
                continue
            expected = parts[-2]
            fired = _fired_rules(fx)
            triggered = rule_id in fired
            ok = (triggered if expected == "fail" else not triggered)
            if ok:
                print(f"  [{GREEN}Matched{END}]  {fx.name} ({rule_id} correctly {'triggered' if expected=='fail' else 'not triggered'})")
                passed += 1
            else:
                print(f"  [{RED}MISMATCH{END}] {fx.name}: expected {expected}, fired={sorted(fired)}")
                mismatched += 1
                errors.append(f"{d.name}/{fx.name}")

    print("\n" + "=" * 60)
    print(f"  Matched: {passed}   Mismatched: {RED if mismatched else GREEN}{mismatched}{END}")
    for e in errors:
        print(f"    - {e}")
    print("=" * 60)
    if mismatched:
        print(f"{RED}[ABORT] BioSample tests failed.{END}")
        return 1
    print(f"{GREEN}[SUCCESS] All BioSample tests passed.{END}")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(main(arg))
