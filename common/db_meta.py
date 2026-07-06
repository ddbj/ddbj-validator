"""ddbj / biosample 共通の DB fetch ファサード（Tier3）。

DB 取得関数は既存の apps/ddbj 実装を単一の共通入口から参照できるようにする
（物理移動はせず re-export。ddbj 側の既存 import を壊さない）。biosample はここから import する。
将来的に完全移設する場合も、参照側はこの common.db_meta を使い続けられる。
"""
from apps.ddbj.db_auth import fetch_authorized_accessions
from apps.ddbj.db_meta_bioproject import fetch_bp_psubs, fetch_prjdb_by_psub

__all__ = ["fetch_authorized_accessions", "fetch_bp_psubs", "fetch_prjdb_by_psub"]
