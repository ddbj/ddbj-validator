"""IDF / SDRF（MAGE-TAB TSV）のパーサ。共通実体は common/magetab に委譲。

戻り値は (MbSubmission, pre_errors)。整形不正（読込失敗）は pre_errors に積む。
"""
from common.magetab import reader as base
from apps.metabobank.model import Idf, MbSubmission
from apps.metabobank.charnorm import normalize


def _known_idf_fields():
    try:
        from apps.metabobank.defs import load_definitions
        return set(load_definitions().get("idf", {}).get("fields", []))
    except Exception:
        return set()


def _apply_charnorm(sub):
    """IDF フィールド値・SDRF セルの非 ASCII を強制正規化（in-place）。
    正規化・残存の記録を sub.char_fixes に積む（MB_IR0024 / MB_SR0030 が報告に使う）。"""
    fixes = []
    if sub.idf:
        for name in sub.idf.field_order:
            vals = sub.idf.fields.get(name)
            if not vals:
                continue
            for i, v in enumerate(vals):
                new, mapped, residual = normalize(v)
                if mapped or residual:
                    vals[i] = new
                    fixes.append({"target": "IDF", "where": name, "line": None,
                                  "original": v, "fixed": new,
                                  "mapped": mapped, "residual": residual})
    if sub.sdrf:
        header = sub.sdrf.header
        for r, row in enumerate(sub.sdrf.rows):
            for c, cell in enumerate(row):
                new, mapped, residual = normalize(cell)
                if mapped or residual:
                    row[c] = new
                    col = header[c] if c < len(header) else f"col{c + 1}"
                    fixes.append({"target": "SDRF", "where": col, "line": r + 1,
                                  "original": cell, "fixed": new,
                                  "mapped": mapped, "residual": residual})
    sub.char_fixes = fixes


def parse(idf_path=None, sdrf_path=None, account=None):
    sub, pre = base.parse(
        idf_path, sdrf_path,
        submission_cls=MbSubmission, idf_cls=Idf,
        known_fields=_known_idf_fields(),
        idf_err_id="MB_IR0001", sdrf_err_id="MB_SR0001",
        account=account,
    )
    _apply_charnorm(sub)
    return sub, pre


def wrong_db_reason(sub):
    """IDF が MetaboBank 以外（GEA）の MAGE-TAB に見えれば理由文字列を返す（abort 用）。"""
    return base.check_flavor(sub.idf, "metabobank")
