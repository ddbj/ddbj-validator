"""GEA validator の検証コンテキスト。bs/bp/dra/metabobank と同じ skip_* 骨格。"""
from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationContext:
    account: Any = None
    skip_db: bool = False
    skip_ncbi: bool = False
    skip_auth: bool = False
    definitions: Any = None
    # DB 依存（GEA_BS biosample 整合）: SAMD -> {attr: value}（内部 DB 取得。None=未取得＝スキップ）
    biosample_attrs: Any = None
    # DB 依存（GEA_REF0002）: account で登録済み（所有 or DRA permit）の参照集合。None=未取得＝スキップ
    account_bioprojects: Any = None
    account_biosamples: Any = None
    account_runs: Any = None
    # DB 依存（GEA_REF0005）: account 所有＋公開の Array Design accession 集合
    array_designs_registered: Any = None
    # DB 依存（GEA_REF0003/0004）: 連携先 DRA submission の全 Run/BioSample。None=DRA 連携なし/未取得
    dra_submission_runs: Any = None
    dra_submission_biosamples: Any = None
    # DB 依存（GEA_REF0008）: DRR -> {drx, biosample, bioproject} の DRA 実 triple
    dra_run_triples: Any = None

    def __post_init__(self):
        if self.definitions is None:
            from apps.gea.defs import load_definitions
            self.definitions = load_definitions()
