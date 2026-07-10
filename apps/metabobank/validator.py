"""MetaboBank ルールの登録と実行。bs/bp/dra と同型。"""
from apps.metabobank.rules.base import is_internal_ignore
from apps.metabobank.rules import idf as I
from apps.metabobank.rules import sdrf as S
from apps.metabobank.rules import cross as C
from apps.metabobank.rules import biosample as B


class Validator:
    def __init__(self, context):
        self.context = context
        available_rules = [
            # --- IDF ---
            I.MB_IR0003(), I.MB_IR0004(), I.MB_IR0005(), I.MB_IR0006(), I.MB_IR0007(),
            I.MB_IR0008(), I.MB_IR0009(), I.MB_IR0010(), I.MB_IR0011(), I.MB_IR0013(),
            I.MB_IR0015(), I.MB_IR0016(), I.MB_IR0017(), I.MB_IR0018(), I.MB_IR0020(),
            I.MB_IR0023(), I.MB_IR0025(), I.MB_IR0033(), I.MB_IR0034(), I.MB_IR0035(),
            I.MB_IR0037(), I.MB_IR0038(),
            # --- SDRF（metadata）---
            S.MB_SR0003(), S.MB_SR0004(), S.MB_SR0005(), S.MB_SR0006(), S.MB_SR0009(),
            S.MB_SR0017(), S.MB_SR0018(), S.MB_SR0019(), S.MB_SR0024(), S.MB_SR0026(),
            S.MB_SR0030(), S.MB_SR0033(), S.MB_SR0045(), S.MB_SR0046(),
            # --- cross ---
            C.MB_CR0001(), C.MB_CR0002(), C.MB_CR0003(), C.MB_CR0004(),
            # --- BioSample DB 整合 ---
            B.MB_SR0021(), B.MB_SR0022(), B.MB_SR0023(),
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

    def run(self, sub):
        results = []
        for rule in self.active_rules:
            results.extend(rule.validate(sub, self.context))
        for r in results:
            r["external"] = is_internal_ignore(r["rule_id"])
        return results
