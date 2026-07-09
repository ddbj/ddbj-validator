"""BioProject ルールの登録と実行（ddbj/biosample validator と同型）。

ルールはここに明示列挙して順序を制御する。モード別スキップは能力フラグ（requires_rdb/network/auth）で行う。
現状の実装範囲: Step1(形式は xml_reader 側 R0001/0002/0037)＋Step2(taxonomy R0018/0020/0038/0039, 値 R0060/0059)。
"""
from apps.bioproject.rules.base import is_internal_ignore
from apps.bioproject.rules.value import BP_R0060, BP_R0059
from apps.bioproject.rules.taxonomy import BP_R0018, BP_R0020, BP_R0038, BP_R0039


class Validator:
    def __init__(self, context):
        self.context = context
        available_rules = [
            # --- 値・文字種（DB 非依存）---
            BP_R0060(),  # 非 ASCII
            BP_R0059(),  # データ形式（空白）
            # --- taxonomy（DB/NCBI 依存。local ではスキップ）---
            BP_R0038(),  # organism ↔ taxonomy_id 不一致
            BP_R0039(),  # taxonomy 未解決 warning
            BP_R0018(),  # species/infraspecific rank
            BP_R0020(),  # Environment は metagenome
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
