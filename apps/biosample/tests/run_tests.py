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
    # package_vs_organism 用
    "Mus musculus": {"tax_id": "10090", "rank": "species", "scientific_name": "Mus musculus",
                     "is_species_or_below": True, "status": "valid", "pl_code": 0,
                     "lineage": "Eukaryota; Metazoa; Chordata; Mammalia; Mus"},
    "Dengue virus": {"tax_id": "12637", "rank": "species", "scientific_name": "Dengue virus",
                     "is_species_or_below": True, "status": "valid", "pl_code": 0,
                     "lineage": "Viruses; Riboviria; Orthornavirae"},
    "Saccharomyces cerevisiae": {"tax_id": "4932", "rank": "species", "scientific_name": "Saccharomyces cerevisiae",
                                 "is_species_or_below": True, "status": "valid", "pl_code": 0,
                                 "lineage": "Eukaryota; Fungi; Ascomycota"},
    "soil metagenome": {"tax_id": "410658", "rank": "species", "scientific_name": "soil metagenome",
                        "is_species_or_below": True, "status": "valid", "pl_code": 0,
                        "lineage": "unclassified sequences; metagenomes; ecological metagenomes"},
    "Euglena gracilis": {"tax_id": "3039", "rank": "species", "scientific_name": "Euglena gracilis",
                         "is_species_or_below": True, "status": "valid", "pl_code": 11,
                         "lineage": "Eukaryota; Discoba; Euglenozoa"},  # 非 Viridiplantae だが plastid 保持
}


# 決定的テストのための mock account 状態（DB に依存しない。D 群 R0006/0129/0070/0095 用）。
# fixture はこの mock を前提に pass/fail を設計する。
MOCK_ACCOUNT = "test_account"
MOCK_AUTH_PROJECTS = {"PRJDB00001", "PRJDB00099", "PSUB000001", "PSUB999999"}
MOCK_AUTH_SAMDS = {"SAMD00000001"}
MOCK_BP_META = {
    "PRJDB00001": {"submission_id": "PSUB000001", "project_type": "primary", "status_id": 5500},
    "PRJDB00099": {"submission_id": "PSUB000099", "project_type": "umbrella", "status_id": 5500},
}
MOCK_PSUB_TO_PRJD = {
    "PSUB000001": {"accession": "PRJDB12345", "status_id": 5500},
}


def _fired_rules(fixture_path):
    """fixture を検証し、発火したルール ID 集合を返す。
    taxonomy ルールも有効化（skip_ncbi=False）し、mock taxonomy を注入して決定的に評価する。
    account 依存ルール（D 群）も skip_auth=False ＋ mock account 状態で決定的に評価する。
    """
    ctx = ValidationContext(
        skip_db=False, skip_ncbi=False, skip_auth=False,
        account=MOCK_ACCOUNT, tax_data=dict(MOCK_TAX),
        authorized_projects=set(MOCK_AUTH_PROJECTS), authorized_samds=set(MOCK_AUTH_SAMDS),
        bp_meta=dict(MOCK_BP_META), psub_to_prjd=dict(MOCK_PSUB_TO_PRJD),
    )
    submission, results, _xml_src = _validate(fixture_path, ctx)
    return {r["rule_id"] for r in results}


def _validate(fixture_path, ctx):
    """fixture を検証し (submission, results, xml_source_path) を返す。
    TSV は XML へ変換した一時ファイルのパスを xml_source として返す（autofix 適用に使う）。"""
    path = Path(fixture_path)
    if path.suffix.lower() in (".txt", ".tsv"):
        import tempfile
        xml_text = tsv_to_xml.tsv_to_xml(str(path))
        sub_id, _ = tsv_to_xml.parse_filename(str(path))
        tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
        tmp.write(xml_text or ""); tmp.close()
        xml_src = tmp.name
        submission, pre = xml_reader.parse_xml(xml_src, submission_id=sub_id)
    else:
        xml_src = str(path)
        submission, pre = xml_reader.parse_xml(xml_src)
    results = list(pre)
    if submission is not None:
        results += Validator(ctx).run(submission)
    return submission, results, xml_src


def _check_autofix(fixture_path, golden_path):
    """fixture を検証→autofix 全自動適用し、生成 XML を golden とバイト突合。
    戻り値: (ok, error_message)。"""
    import tempfile
    from apps.biosample import autofix
    ctx = ValidationContext(
        skip_db=False, skip_ncbi=False, skip_auth=False,
        account=MOCK_ACCOUNT, tax_data=dict(MOCK_TAX),
        authorized_projects=set(MOCK_AUTH_PROJECTS), authorized_samds=set(MOCK_AUTH_SAMDS),
        bp_meta=dict(MOCK_BP_META), psub_to_prjd=dict(MOCK_PSUB_TO_PRJD),
    )
    submission, results, xml_src = _validate(fixture_path, ctx)
    if submission is None:
        return False, "parse failed"
    with tempfile.TemporaryDirectory() as td:
        name = "out.xml"
        n = autofix.apply_autofix(xml_src, results, td, name)
        if n == 0:
            return False, "no autofix applied (expected fixed output)"
        got = (Path(td) / "fixed" / name).read_bytes()
    want = golden_path.read_bytes()
    if got == want:
        return True, ""
    return False, f"fixed output differs from golden (got {len(got)}B, want {len(want)}B)"


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

        # autofix ゴールデン検証: <dir>/expected/<name> があれば、その入力に autofix を適用して突合。
        exp_dir = d / "expected"
        if exp_dir.is_dir():
            for fx in sorted(list(d.glob("*.xml")) + list(d.glob("*.txt"))):
                golden = exp_dir / (Path(fx.name).stem + ".xml" if fx.suffix != ".xml" else fx.name)
                if not golden.exists():
                    continue
                ap, af_err = _check_autofix(fx, golden)
                if ap:
                    print(f"  [{GREEN}Autofix{END}] {fx.name} matches expected/{golden.name}")
                    passed += 1
                else:
                    print(f"  [{RED}MISMATCH{END}] autofix {fx.name}: {af_err}")
                    mismatched += 1
                    errors.append(f"{d.name}/autofix:{fx.name}")

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
