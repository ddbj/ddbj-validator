"""ddbj / biosample 共通の DB fetch ファサード（Tier3）。

実体は common/db_auth.py と common/db_meta_bioproject.py（2026-09-15 に apps/ddbj から移設。
ddbj 側の旧モジュールは互換の再エクスポート）。biosample はここから import する。
"""
from common.db_auth import fetch_authorized_accessions
from common.db_meta_bioproject import fetch_bp_psubs, fetch_prjdb_by_psub

__all__ = ["fetch_authorized_accessions", "fetch_bp_psubs", "fetch_prjdb_by_psub"]
