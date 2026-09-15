"""互換用の再エクスポート。実体は common/db_meta_bioproject.py（biosample も使うため common へ移した）。"""
from common.db_meta_bioproject import fetch_bp_psubs, fetch_prjdb_by_psub  # noqa: F401
