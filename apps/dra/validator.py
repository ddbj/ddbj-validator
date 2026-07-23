"""DRA ルールの登録と実行（ddbj/biosample/bioproject validator と同型）。

ルールはここに明示列挙して順序を制御する。モード別スキップは能力フラグ（requires_rdb/network/auth）。
順序: 構造(R0002) → cv(R0039) → content → file → 参照整合 → account/DB。
"""
from apps.dra.rules.base import is_internal_ignore
from apps.dra.rules.structure import DRA_R0002
from apps.dra.rules.cv import DRA_R0039
from apps.dra.rules.reference import (
    DRA_R0003, DRA_R0017, DRA_R0033, DRA_R0034, DRA_R0035, DRA_R0036, DRA_R0037, DRA_R0038,
    DRA_R0041, DRA_R0042, DRA_R0043, DRA_R0048,
)
from apps.dra.rules.content import (
    DRA_R0010, DRA_R0011, DRA_R0012, DRA_R0013, DRA_R0014, DRA_R0018, DRA_R0019, DRA_R0020,
)
from apps.dra.rules.file import (
    DRA_R0021, DRA_R0022, DRA_R0023, DRA_R0024, DRA_R0025, DRA_R0026,
    DRA_R0027, DRA_R0028, DRA_R0029, DRA_R0030, DRA_R0031, DRA_R0040, DRA_R0049,
)
from apps.dra.rules.account import (
    DRA_R0004, DRA_R0006, DRA_R0009, DRA_R0015, DRA_R0016,
)


class Validator:
    def __init__(self, context):
        self.context = context
        available_rules = [
            # --- 構造 / cv（XSD 縮小の代替）---
            DRA_R0002(),   # 必須コンテナの構造チェック
            DRA_R0039(),   # cv_terms（LIBRARY_* / INSTRUMENT_MODEL）
            # --- content ---
            DRA_R0010(), DRA_R0011(), DRA_R0012(), DRA_R0014(),
            # DRA_R0013()=Experiment description（DESIGN_DESCRIPTION）必須。現行 D-way は description 入力欄を
            # 省略しており通常空のため、呼び出しをコメントアウト（クラス・import は残置。bs/ddbj と同方針）。
            # DRA_R0013(),
            DRA_R0018(), DRA_R0019(), DRA_R0020(),
            # --- file ---
            DRA_R0021(), DRA_R0022(), DRA_R0023(), DRA_R0024(), DRA_R0025(), DRA_R0026(),
            DRA_R0027(), DRA_R0028(), DRA_R0029(), DRA_R0030(), DRA_R0031(),
            DRA_R0040(),   # 同一 filename の重複
            DRA_R0049(),   # 別名だが md5 同一（同一内容の二重登録）
            # --- 参照整合 ---
            DRA_R0003(), DRA_R0017(), DRA_R0034(), DRA_R0033(),
            DRA_R0035(), DRA_R0036(), DRA_R0037(), DRA_R0038(),
            DRA_R0048(),   # submission あたり Run 数上限（2000）
            # --- account/DB（-l/-n ではスキップ）---
            DRA_R0006(),   # hold date（DB 非依存）
            DRA_R0004(), DRA_R0009(),
            DRA_R0041(), DRA_R0042(), DRA_R0043(),  # Experiment BP/BS・Analysis Run が account∪permit
            DRA_R0015(), DRA_R0016(),               # Analysis BP/BS が account∪permit
        ]
        self.active_rules = []
        for rule in available_rules:
            if context.skip_db and getattr(rule, "requires_rdb", False):
                continue
            if context.skip_ncbi and getattr(rule, "requires_network", False):
                continue
            if context.skip_auth and getattr(rule, "requires_auth", False):
                continue
            self.active_rules.append(rule)

    def run(self, submission):
        results = []
        for rule in self.active_rules:
            results.extend(rule.validate(submission, self.context))
        for r in results:
            r["external"] = is_internal_ignore(r["rule_id"])
        return results
