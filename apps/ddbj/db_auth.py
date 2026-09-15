"""互換用の再エクスポート。実体は common/db_auth.py（biosample も使うため common へ移した）。"""
from common.db_auth import fetch_authorized_accessions  # noqa: F401
