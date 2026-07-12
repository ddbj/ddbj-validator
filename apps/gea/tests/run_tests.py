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
    # crafted fixture: SRA_RUN ≠ Array Data File（TSV のみ・DB 不要）→ REF0007 error
    "REF0007-craft": {"GEA_REF0007"},
}

# --- DB モード（opt-in / dradev） ---
# DB モードで「DB 依存ルール（requires_rdb/auth）∪ error 級」の発火を検証。
# key が ESUB… は dordb 由来の実 submission、それ以外は DATA/ の crafted fixture（本番登録不可な error 用）。
# ※ 002704/002705/002710 は重複 LIBRARY 列テンプレートで作られており RC0002（重複列）＋
#   LC0001（重複列の空セル）が構造的に発火する（002706 のみ重複なし＝真にクリーン）。
GEA_DB_ACCOUNT = "dradev"
GEA_DB_EXPECTED = {
    "ESUB002709": set(),                              # microarray, external ADF acc ref OK
    "ESUB002708": set(),                              # microarray, ADF file submit OK
    "ESUB002706": set(),                              # sequencing, DRA Run ref ext-permit all OK（重複列なし）
    "ESUB002705": {"GEA_REF0003", "GEA_REF0004", "GEA_LC0001", "GEA_RC0002"},  # partial ＋ 重複列
    "ESUB002704": {"GEA_LC0001", "GEA_RC0002"},       # DRA Run ref OK ＋ 重複列
    # 存在しない SAMD00000000（正規表現通過・未登録）→ REF0002＋BS0002、triple 不一致で REF0008、BS 値不一致で BS0003、重複列で LC0001/RC0002
    "ESUB002710": {"GEA_REF0002", "GEA_REF0008", "GEA_BS0002", "GEA_BS0003", "GEA_LC0001", "GEA_RC0002"},
    # crafted fixture: bogus A-GEAD-999999（自 account 未登録かつ非公開でない）→ REF0005 error
    "REF0005-craft": {"GEA_REF0005"},
}


def _fired(study):
    sub, pre = reader.parse(str(DATA / f"{study}.idf.txt"), str(DATA / f"{study}.sdrf.txt"))
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    results = list(pre) + Validator(ctx).run(sub)
    return {r["rule_id"] for r in results}


def _db_rule_ids():
    """DB 依存（requires_rdb / requires_auth）ルールの rule_id 集合。"""
    return {r.rule_id for r in Validator(ValidationContext()).active_rules
            if getattr(r, "requires_rdb", False) or getattr(r, "requires_auth", False)}


def _db_fired(key, account):
    """key が ESUB… は dordb から取得、それ以外は DATA/<key>.idf.txt/.sdrf.txt（crafted fixture）を DB モード検証。
    「DB 依存ルール ∪ error 級」の発火 rule_id を返す。"""
    import tempfile
    from common.db_manager import DatabaseManager
    from apps.gea import db_meta
    from apps.gea.cli import _fetch_account_refs, _fetch_biosample_attrs
    if key.startswith("ESUB"):
        gc = DatabaseManager().get_gea_conn()
        idf, sdrf = db_meta.fetch_experiment_metadata(gc, key)
        td = Path(tempfile.mkdtemp())
        ip, sp = td / f"{key}.idf.txt", td / f"{key}.sdrf.txt"
        ip.write_text(idf or "", encoding="utf-8")
        sp.write_text(sdrf or "", encoding="utf-8")
    else:
        ip, sp = DATA / f"{key}.idf.txt", DATA / f"{key}.sdrf.txt"
    sub, pre = reader.parse(str(ip), str(sp), account=account)
    ctx = ValidationContext(account=account, skip_db=False, skip_ncbi=False, skip_auth=False)
    _fetch_biosample_attrs(ctx, sub, account)
    _fetch_account_refs(ctx, sub, account)
    results = list(pre) + Validator(ctx).run(sub)
    db_ids = _db_rule_ids()
    return {r["rule_id"] for r in results if r["rule_id"] in db_ids or r.get("level") == "error"}


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
