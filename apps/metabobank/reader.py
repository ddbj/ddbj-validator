"""IDF / SDRF（MAGE-TAB TSV）のパーサ。共通実体は common/magetab に委譲。

戻り値は (MbSubmission, pre_errors)。整形不正（読込失敗）は pre_errors に積む。
"""
from common.magetab import reader as base
from apps.metabobank.model import Idf, MbSubmission
from common.magetab.charnorm import apply_to_submission as _apply_charnorm


#: 旧い IDF フィールド名 → 今の名前（2026-09-18 に GEA と揃えて Title Case に）
RENAMED_IDF_FIELDS = {
    "Comment[MetaboBank accession]": "Comment[MetaboBank Accession]",
    "Comment[Submission type]": "Comment[Submission Type]",
    "Comment[Experiment type]": "Comment[Experiment Type]",
    "Comment[Study type]": "Comment[Study Type]",
    "Comment[Related study]": "Comment[Related Study]",
}


def _known_idf_fields():
    try:
        from apps.metabobank.defs import load_definitions
        return set(load_definitions().get("idf", {}).get("fields", []))
    except Exception:
        return set()


def parse(idf_path=None, sdrf_path=None, account=None):
    sub, pre = base.parse(
        idf_path, sdrf_path,
        submission_cls=MbSubmission, idf_cls=Idf,
        known_fields=_known_idf_fields() | set(RENAMED_IDF_FIELDS),
        idf_err_id="MB_IR0001", sdrf_err_id="MB_SR0001",
        account=account,
    )
    base.rename_idf_fields(sub.idf, RENAMED_IDF_FIELDS)
    _apply_charnorm(sub)
    return sub, pre


def wrong_db_reason(sub):
    """IDF が MetaboBank 以外（GEA）の MAGE-TAB に見えれば理由文字列を返す（abort 用）。"""
    return base.check_flavor(sub.idf, "metabobank")
