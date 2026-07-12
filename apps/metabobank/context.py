"""MetaboBank validator の検証コンテキスト。bs/bp/dra と同じ skip_* 骨格。"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationContext:
    account: Any = None
    skip_db: bool = False
    skip_ncbi: bool = False
    skip_auth: bool = False
    definitions: Any = None
    # DB 依存（MB_SR0021/0022/0023）: SAMD -> {attr: value} の BioSample 属性（内部 DB 取得。None=未取得＝スキップ）
    biosample_attrs: Any = None

    def __post_init__(self):
        if self.definitions is None:
            from apps.metabobank.defs import load_definitions
            self.definitions = load_definitions()
