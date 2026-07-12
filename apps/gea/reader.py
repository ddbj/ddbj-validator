"""IDF / SDRF（MAGE-TAB TSV）のパーサ。共通実体は common/magetab に委譲。

戻り値は (GeaSubmission, pre_errors)。整形不正（読込失敗）は pre_errors に積む。
"""
from common.magetab import reader as base
from apps.gea.model import Idf, GeaSubmission


def _known_idf_fields():
    try:
        from apps.gea.defs import load_definitions
        return set(load_definitions().get("idf", {}).get("fields", []))
    except Exception:
        return set()


def parse(idf_path=None, sdrf_path=None, account=None):
    return base.parse(
        idf_path, sdrf_path,
        submission_cls=GeaSubmission, idf_cls=Idf,
        known_fields=_known_idf_fields(),
        idf_err_id="GEA_ERR0001", sdrf_err_id="GEA_ERR0001",
        account=account,
    )
