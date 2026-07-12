#!/usr/bin/env python3
"""MetaboBank validator E2E（in-process・実データ回帰）。

apps/metabobank/tests/data/ の実例 3 studies（-l ローカル）を検証し、発火 rule_id 集合が
期待集合（EXPECTED）と一致するかを判定する。ルール改修時の退行検知用。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from apps.metabobank.context import ValidationContext
from apps.metabobank.validator import Validator
from apps.metabobank import reader

GREEN, RED, END = "\033[92m", "\033[91m", "\033[0m"
DATA = HERE / "data"

# -l（DB 非依存）での期待発火 rule_id（ignore 含む）。conf 由来の既知発火。
EXPECTED = {
    "MTBKS210": {"MB_IR0037"},
    "MTBKS230": {"MB_IR0018", "MB_IR0037", "MB_SR0005", "MB_SR0046"},
    "MTBKS240": {"MB_IR0018", "MB_IR0037"},
}


def _fired(study):
    sub, pre = reader.parse(str(DATA / f"{study}.idf.txt"), str(DATA / f"{study}.sdrf.txt"))
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    results = list(pre) + Validator(ctx).run(sub)
    return {r["rule_id"] for r in results}


def main(argv):
    matched = mismatched = 0
    for study, expected in EXPECTED.items():
        fired = _fired(study)
        ok = fired == expected
        if ok:
            matched += 1
            print(f"  [{GREEN}Matched{END}]  {study}: {sorted(fired)}")
        else:
            mismatched += 1
            print(f"  [{RED}MISMATCH{END}] {study}: fired={sorted(fired)} expected={sorted(expected)}"
                  f" (+{sorted(fired - expected)} / -{sorted(expected - fired)})")
    print(f"\n  Matched: {matched}   Mismatched: {mismatched}")
    if mismatched:
        print(f"{RED}[FAIL]{END}"); return 1
    print(f"{GREEN}[SUCCESS] All MetaboBank tests passed.{END}"); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
