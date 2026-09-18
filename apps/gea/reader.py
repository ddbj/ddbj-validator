"""IDF / SDRF（MAGE-TAB TSV）のパーサ。共通実体は common/magetab に委譲。

戻り値は (GeaSubmission, pre_errors)。整形不正（読込失敗）は pre_errors に積む。
"""
from common.magetab import reader as base
from apps.gea.model import Idf, GeaSubmission


#: 旧い IDF フィールド名 → 今の名前（2026-09-18 に MetaboBank と揃えた）。登録済みの IDF は旧名のままなので読むときに直す
RENAMED_IDF_FIELDS = {
    "Comment[GEAAccession]": "Comment[GEA Accession]",
    "Comment[AEExperimentType]": "Comment[Experiment Type]",
    "Comment[Related study]": "Comment[Related Study]",
    "Comment[Public Release Date]": "Public Release Date",
}


def _known_idf_fields():
    try:
        from apps.gea.defs import load_definitions
        idf = load_definitions().get("idf", {})
        # legacy_fields = 旧い submission にだけあるフィールド（新規では書かないが読めるようにする）
        return set(idf.get("fields", [])) | set(idf.get("legacy_fields", []))
    except Exception:
        return set()


def parse(idf_path=None, sdrf_path=None, account=None):
    sub, pre = base.parse(
        idf_path, sdrf_path,
        submission_cls=GeaSubmission, idf_cls=Idf,
        known_fields=_known_idf_fields() | set(RENAMED_IDF_FIELDS),
        idf_err_id="GEA_ERR0001", sdrf_err_id="GEA_ERR0001",
        account=account,
    )
    base.rename_idf_fields(sub.idf, RENAMED_IDF_FIELDS)
    return sub, pre


def wrong_db_reason(sub):
    """IDF が GEA 以外（MetaboBank）の MAGE-TAB に見えれば理由文字列を返す（abort 用）。"""
    return base.check_flavor(sub.idf, "gea")
