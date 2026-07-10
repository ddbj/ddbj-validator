#!/usr/bin/env python3
"""DRA validator E2E（in-process）。

apps/dra/tests/<RULEID>/ 配下の 1 シナリオ = 1 ディレクトリ。ディレクトリ内の *.xml を
まとめて 1 submission として検証し、`.pass`/`.fail` をディレクトリ名（＝ルール）で判定する。
- ディレクトリ名末尾が `.pass` なら当該ルールが発火しないこと、`.fail` なら発火することを期待。
"""
import sys
import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from apps.dra.context import ValidationContext
from apps.dra.validator import Validator
from apps.dra import xml_reader

GREEN, RED, END = "\033[92m", "\033[91m", "\033[0m"

# DB 依存ルール（R0004/0009/0015/0016）＋ 日付基準（R0006）の決定的 mock。
MOCK_ORG = "NIG Center"
MOCK_BP = {"PRJDB1"}
MOCK_BS = {"SAMD00000001"}
MOCK_RUNS = {"DRR0000001"}
MOCK_OBJ_NAMES = {"DUP_ALIAS"}
MOCK_HOLD_REF = datetime.date(2026, 1, 1)


def _fired(scenario_dir):
    paths = sorted(str(p) for p in scenario_dir.glob("*.xml"))
    ctx = ValidationContext(skip_db=False, skip_ncbi=False, skip_auth=False,
                            account_org_name=MOCK_ORG,
                            account_bioprojects=set(MOCK_BP),
                            account_biosamples=set(MOCK_BS),
                            account_runs=set(MOCK_RUNS),
                            account_object_names=set(MOCK_OBJ_NAMES),
                            hold_ref_date=MOCK_HOLD_REF)
    sub, pre = xml_reader.parse_files(paths)
    results = list(pre) + Validator(ctx).run(sub)
    return {r["rule_id"] for r in results}


def main(argv):
    targets = [a for a in argv if not a.startswith("-")]
    dirs = sorted(d for d in HERE.iterdir() if d.is_dir() and d.name.startswith("DRA_R")
                  and (not targets or any(t in d.name for t in targets)))
    matched = mismatched = 0
    for d in dirs:
        # ディレクトリ名: DRA_R00xx_n.pass / DRA_R00xx_n.fail
        parts = d.name.split(".")
        if parts[-1] not in ("pass", "fail"):
            continue
        rid = parts[0].split("_")[0] + "_" + parts[0].split("_")[1]  # DRA_R00xx
        expected = parts[-1]
        fired = rid in _fired(d)
        ok = (fired if expected == "fail" else not fired)
        status = f"{GREEN}Matched{END}" if ok else f"{RED}MISMATCH{END}"
        print(f"  [{status}] {d.name} ({rid} {'fired' if fired else 'not fired'})")
        matched += ok
        mismatched += (not ok)
    print(f"\n  Matched: {matched}   Mismatched: {mismatched}")
    if mismatched:
        print(f"{RED}[FAIL]{END}"); return 1
    print(f"{GREEN}[SUCCESS] All DRA rule tests passed.{END}"); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
