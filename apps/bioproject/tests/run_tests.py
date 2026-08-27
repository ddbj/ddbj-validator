#!/usr/bin/env python3
"""BioProject validator E2E（in-process・mock taxonomy）。

apps/bioproject/tests/BP_Rxxxx/ 配下の `BP_Rxxxx_n.pass.xml` / `.fail.xml` を検証し、
そのディレクトリ名のルールが .fail で発火・.pass で非発火かを判定する（biosample harness と同型）。
taxonomy ルールは mock tax_data/taxid_info を注入して決定的に評価する。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from apps.bioproject.context import ValidationContext
from apps.bioproject.validator import Validator
from apps.bioproject import record_reader, xml_reader

GREEN, RED, END = "\033[92m", "\033[91m", "\033[0m"

# 決定的テスト用の mock taxonomy。
MOCK_TAX = {
    "Homo sapiens": {"tax_id": "9606", "rank": "species", "scientific_name": "Homo sapiens",
                     "is_species_or_below": True, "status": "valid", "lineage": "Eukaryota; Metazoa; Homo"},
    "Escherichia coli": {"tax_id": "562", "rank": "species", "scientific_name": "Escherichia coli",
                         "is_species_or_below": True, "status": "valid", "lineage": "Bacteria; Proteobacteria"},
    "Homo": {"tax_id": "9605", "rank": "genus", "scientific_name": "Homo",
             "is_species_or_below": False, "status": "invalid_rank", "lineage": "Eukaryota; Metazoa"},
    "soil metagenome": {"tax_id": "410658", "rank": "species", "scientific_name": "soil metagenome",
                        "is_species_or_below": True, "status": "valid",
                        "lineage": "unclassified sequences; metagenomes; ecological metagenomes"},
}
MOCK_TAXID = {
    "9606": {"scientific_name": "Homo sapiens", "rank": "species", "is_species_or_below": True,
             "lineage": "Eukaryota; Metazoa; Homo", "pl_code": 0},
    "9605": {"scientific_name": "Homo", "rank": "genus", "is_species_or_below": False,
             "lineage": "Eukaryota; Metazoa", "pl_code": 0},
    "562": {"scientific_name": "Escherichia coli", "rank": "species", "is_species_or_below": True,
            "lineage": "Bacteria; Proteobacteria", "pl_code": 0},
}
# DB 依存ルール（BP_R0016/0021/0004）用の決定的 mock。
MOCK_UMBRELLA_OK = {"PRJDB9490"}                          # 妥当な umbrella accession（PSUB012111 相当）
MOCK_BS_LOCUS = {"SAMD01930202": {"OTMK33"}}              # SAMD -> 登録済み locus_tag_prefix
MOCK_PROJECT_NAMES = [                                    # account 登録済み project（title, description, accession, submission_id）
    ("Duplicated project title for the regression test",
     "Duplicated project description that is intentionally over twenty characters long for the test.",
     "PRJDB0001", "PSUB000001"),
]


def _is_record(path):
    return Path(path).suffix.lower() == ".json"


def _fired(fixture):
    ctx = ValidationContext(skip_db=False, skip_ncbi=False, skip_auth=False,
                            tax_data=dict(MOCK_TAX), taxid_info=dict(MOCK_TAXID),
                            umbrella_ok=set(MOCK_UMBRELLA_OK),
                            bs_locus_prefix={k: set(v) for k, v in MOCK_BS_LOCUS.items()},
                            project_names=list(MOCK_PROJECT_NAMES))
    if _is_record(fixture):
        sub, pre = record_reader.parse_record(str(fixture))
    else:
        sub, pre = xml_reader.parse_xml(str(fixture))
    results = list(pre)
    if sub is not None:
        results += Validator(ctx).run(sub)
    return {r["rule_id"] for r in results}


def main(argv):
    targets = [a for a in argv if not a.startswith("-")]
    dirs = sorted(d for d in HERE.iterdir() if d.is_dir() and d.name.startswith("BP_R")
                  and (not targets or d.name in targets))
    matched = mismatched = 0
    for d in dirs:
        rid = d.name
        print(f"Testing: {rid}")
        for fx in sorted(list(d.glob("*.xml")) + list(d.glob("*.json"))):
            parts = fx.name.split(".")
            if len(parts) < 3 or parts[-2] not in ("pass", "fail"):
                continue
            expected = parts[-2]
            fired = rid in _fired(fx)
            ok = (fired if expected == "fail" else not fired)
            if ok:
                matched += 1
                print(f"  [{GREEN}Matched{END}]  {fx.name} ({rid} correctly {'triggered' if expected=='fail' else 'not triggered'})")
            else:
                mismatched += 1
                print(f"  [{RED}MISMATCH{END}] {fx.name}: expected {expected}, fired={fired}")
    print(f"\n  Matched: {matched}   Mismatched: {mismatched}")
    if mismatched:
        print(f"{RED}[FAIL]{END}")
        return 1
    print(f"{GREEN}[SUCCESS] All BioProject rule tests passed.{END}")

    # 全件実行のときだけ、XML と Record の同値性も確かめる。
    if not targets:
        print("\n--- XML / DDBJ Record parity test ---")
        import importlib.util
        path = HERE / "run_record_parity_test.py"
        spec = importlib.util.spec_from_file_location("run_record_parity_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if mod.main() != 0:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
