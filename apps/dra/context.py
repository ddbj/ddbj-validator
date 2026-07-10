"""DRA validator の検証コンテキスト。biosample/bioproject と同じ skip_* 骨格。"""
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
    # --- DB 依存ルール用（None=未取得＝スキップ。default/-l モードでは None のまま）---
    account_bioprojects: Any = None   # DRA_R0015: account の BioProject 集合
    account_biosamples: Any = None    # DRA_R0016/0042: account∪permit の BioSample 集合
    account_runs: Any = None          # DRA_R0043: account∪permit の Run(DRR) 集合
    account_object_names: Any = None  # DRA_R0009: account 既存 object 名（重複判定）
    account_org_name: Any = None      # DRA_R0004: account の組織名（center_name 照合）
    hold_ref_date: Any = None          # DRA_R0006: hold date 2 年判定の基準日（None=実行日）

    def __post_init__(self):
        if self.definitions is None:
            from apps.dra.defs import load_definitions
            self.definitions = load_definitions()
        if not self.cv_terms:
            self.cv_terms = self.definitions.get("cv_terms", {})
