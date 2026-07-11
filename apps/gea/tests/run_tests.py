#!/usr/bin/env python3
"""GEA validator E2E。

既定（ローカル）: apps/gea/tests/data/ の実例（-l）で発火 rule_id を検証（DB 非依存・既定ゲート用）。
`--db`（opt-in・要内部 DB＋dradev アカウント）: dordb の dradev テスト submission を DB モードで検証し、
DRA/DB cross（REF）系の発火を検証する。既定集合には含めない（DB のあるマシンで明示実行）。
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

# --- ローカル（既定） ---
EXPECTED = {
    "E-GEAD-1104": set(),                             # microarray, clean
    "E-GEAD-1114": set(),                             # sequencing, clean
    "E-GEAD-1117": {"GEA_PR0006"},                    # microarray, protocol desc <100
    "E-GEAD-1144": {"GEA_G0009", "GEA_PR0006"},       # sequencing, desc <100 + protocol desc <100
}

# --- DB モード（opt-in / dradev） ---
# dradev のテスト submission（ADF / DRA Run ref）。DB モードで REF 系の期待発火を検証。
GEA_DB_ACCOUNT = "dradev"
GEA_DB_EXPECTED = {
    "ESUB002709": set(),                              # microarray, external ADF acc ref OK
    "ESUB002708": set(),                              # microarray, ADF file submit OK
    "ESUB002706": set(),                              # sequencing, DRA Run ref ext-permit all OK
    "ESUB002705": {"GEA_REF0003", "GEA_REF0004"},     # sequencing, DRA Run ref partial
    "ESUB002704": set(),                              # sequencing, DRA Run ref OK
}


def _fired(study):
    sub, pre = reader.parse(str(DATA / f"{study}.idf.txt"), str(DATA / f"{study}.sdrf.txt"))
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    results = list(pre) + Validator(ctx).run(sub)
    return {r["rule_id"] for r in results}


def _db_fired(esub, account):
    """dordb から Experiment の IDF/SDRF を取得し、DB モードで検証して REF 系発火を返す。"""
    import tempfile
    from common.db_manager import DatabaseManager
    from apps.gea import db_meta
    from apps.gea.cli import _fetch_account_refs, _fetch_biosample_attrs
    gc = DatabaseManager().get_gea_conn()
    idf, sdrf = db_meta.fetch_experiment_metadata(gc, esub)
    td = Path(tempfile.mkdtemp())
    ip, sp = td / f"{esub}.idf.txt", td / f"{esub}.sdrf.txt"
    ip.write_text(idf or "", encoding="utf-8")
    sp.write_text(sdrf or "", encoding="utf-8")
    sub, pre = reader.parse(str(ip), str(sp), account=account)
    ctx = ValidationContext(account=account, skip_db=False, skip_ncbi=False, skip_auth=False)
    _fetch_biosample_attrs(ctx, sub, account)
    _fetch_account_refs(ctx, sub, account)
    results = list(pre) + Validator(ctx).run(sub)
    # DRA/DB cross（REF 系）に絞って検証（ADF/DRA Run ref のテスト意図）
    return {r["rule_id"] for r in results if r["rule_id"].startswith("GEA_REF")}


def _run(expected, fired_fn, header, label_fn=None):
    print(header)
    matched = mismatched = 0
    for key, exp in expected.items():
        fired = fired_fn(key)
        if fired == exp:
            matched += 1
            print(f"  [{GREEN}Matched{END}]  {key}: {sorted(fired)}")
        else:
            mismatched += 1
            print(f"  [{RED}MISMATCH{END}] {key}: fired={sorted(fired)} expected={sorted(exp)}"
                  f" (+{sorted(fired - exp)} / -{sorted(exp - fired)})")
    print(f"  Matched: {matched}   Mismatched: {mismatched}\n")
    return mismatched


def main(argv):
    if "--db" in argv:
        try:
            from dotenv import load_dotenv
            load_dotenv(str(ROOT / ".env"))
        except ImportError:
            pass
        mm = _run(GEA_DB_EXPECTED, lambda e: _db_fired(e, GEA_DB_ACCOUNT),
                  "=== GEA DB-mode E2E (opt-in, dradev) ===")
    else:
        mm = _run(EXPECTED, _fired, "=== GEA local E2E ===")
    if mm:
        print(f"{RED}[FAIL]{END}")
        return 1
    print(f"{GREEN}[SUCCESS] All GEA tests passed.{END}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
