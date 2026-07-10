#!/usr/bin/env python3
"""GEA validator E2E（in-process・実データ回帰）。

apps/gea/tests/data/ の実例（-l ローカル）を検証し、発火 rule_id 集合が
期待集合（EXPECTED）と一致するかを判定する。ルール改修時の退行検知用。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from apps.gea.context import ValidationContext
from apps.gea.validator import Validator
from apps.gea import reader

GREEN, RED, END = "\033[92m", "\033[91m", "\033[0m"
DATA = HERE / "data"

# -l（DB 非依存）での期待発火 rule_id。microarray/sequencing × clean/warning を網羅。
EXPECTED = {
    "E-GEAD-1104": set(),                             # microarray, clean
    "E-GEAD-1114": set(),                             # sequencing, clean
    "E-GEAD-1117": {"GEA_PR0006"},                    # microarray, protocol desc <100
    "E-GEAD-1144": {"GEA_G0009", "GEA_PR0006"},       # sequencing, desc <100 + protocol desc <100
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
    print(f"{GREEN}[SUCCESS] All GEA tests passed.{END}"); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
