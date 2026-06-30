"""BioSample ルールの登録と実行（ddbj validator.py と同型）。

ルールはここに明示列挙して順序を制御する（ddbj 同様、手作業で並べる）。
モード別スキップは能力フラグ（requires_rdb/network/auth）で行う。
"""
from apps.biosample.rules.mandatory import BS_R0018, BS_R0020, BS_R0025, BS_R0026, BS_R0027


class Validator:
    def __init__(self, context):
        self.context = context
        ctx = context

        available_rules = [
            # --- フェーズ1: 必須・パッケージ（DB 非依存）---
            BS_R0025(),  # Package 欠落
            BS_R0026(),  # 未知 Package
            BS_R0018(),  # sample_name 欠落
            BS_R0020(),  # organism 欠落
            BS_R0027(),  # 必須属性欠落
            # 以降フェーズ2/3 でルールを追記（taxonomy / 値形式 / DB 系）
        ]

        self.active_rules = []
        for rule in available_rules:
            if ctx.skip_db and getattr(rule, "requires_rdb", False):
                continue
            if ctx.skip_ncbi and getattr(rule, "requires_network", False):
                continue
            if ctx.skip_auth and getattr(rule, "requires_auth", False):
                continue
            self.active_rules.append(rule)

    def run(self, submission):
        """submission を全 active_rules で検証し、結果 dict のリストを返す。"""
        results = []
        for rule in self.active_rules:
            results.extend(rule.validate(submission, self.context))
        return results
