"""BioProject validator の検証コンテキスト。biosample と同じ skip_* 骨格。"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationContext:
    account: Any = None
    skip_db: bool = False
    skip_ncbi: bool = False
    skip_auth: bool = False
    # 定義ファイル（resources/definitions.json）。None の場合 __post_init__ で読み込む。
    definitions: Any = None
    cv_terms: dict = field(default_factory=dict)
    # organism 名 -> taxonomy 情報（common/db_taxonomy or NCBI。local では空）
    tax_data: dict = field(default_factory=dict)
    # taxonomy_id -> {scientific_name, rank, is_species_or_below, lineage, pl_code}（BP_R0018/0038 用）
    taxid_info: dict = field(default_factory=dict)
    # BioProject メタ {PRJDBxxxx: {project_type, status_id}}（BP_R0016 umbrella 判定・要 DB）
    bp_meta: dict = field(default_factory=dict)
    # --- DB 依存ルール用（None=未取得＝スキップ。default/-l モードでは None のまま）---
    umbrella_ok: Any = None       # BP_R0016: 妥当な umbrella accession の集合
    bs_locus_prefix: Any = None   # BP_R0021: SAMD -> {locus_tag_prefix,...}
    project_names: Any = None     # BP_R0004: account 登録済み project の [(title, description, accession, submission_id), ...]
    self_submission_id: Any = None  # BP_R0004: 検証対象自身の PSUB（重複比較から自己除外。CLI では None）

    def __post_init__(self):
        if self.definitions is None:
            from apps.bioproject.defs import load_definitions
            self.definitions = load_definitions()
        if not self.cv_terms:
            self.cv_terms = self.definitions.get("cv_terms", {})
