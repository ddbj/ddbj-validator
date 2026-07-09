"""BioProject validator の検証コンテキスト。biosample と同じ skip_* 骨格。"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationContext:
    account: Any = None
    skip_db: bool = False
    skip_ncbi: bool = False
    skip_auth: bool = False
    # organism 名 -> taxonomy 情報（common/db_taxonomy or NCBI。local では空）
    tax_data: dict = field(default_factory=dict)
    # taxonomy_id -> {scientific_name, rank, is_species_or_below, lineage, pl_code}（BP_R0018/0038 用）
    taxid_info: dict = field(default_factory=dict)
    # BioProject メタ {PRJDBxxxx: {project_type, status_id}}（BP_R0016 umbrella 判定・要 DB）
    bp_meta: dict = field(default_factory=dict)
