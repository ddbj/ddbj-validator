"""GEA ルールの登録と実行。bs/bp/dra/metabobank と同型。

only_type（None/microarray/sequencing）により submission type 別にルールを出し分ける。
"""
from apps.gea.rules.base import is_internal_ignore
from apps.gea.rules import idf as I
from apps.gea.rules import sdrf as S
from apps.gea.rules import nodes as N
from apps.gea.rules import cross as C
from apps.gea.rules import biosample as B
from apps.gea.rules import reference_db as RDB


class Validator:
    def __init__(self, context):
        self.context = context
        available_rules = [
            # --- IDF ---
            I.GEA_C0001(), I.GEA_C0002(), I.GEA_C0008(),
            I.GEA_COM0001(),
            I.GEA_G0001(), I.GEA_G0002(), I.GEA_G0009(), I.GEA_G0004(), I.GEA_G0006(),
            I.GEA_G0007(), I.GEA_G0012(), I.GEA_G0013(),
            I.GEA_ED0001(), I.GEA_EF0001(), I.GEA_EF0003(),
            I.GEA_PB0002(),
            I.GEA_PR0001(), I.GEA_PR0002(), I.GEA_PR0003(), I.GEA_PR0005(), I.GEA_PR0006(),
            I.GEA_PR0013(), I.GEA_PR0014(), I.GEA_PR0015(),
            I.GEA_PR0010(), I.GEA_PR0011(), I.GEA_PR0012(),
            I.GEA_PR0008(), I.GEA_PR0009(),
            I.GEA_RC0001(), I.GEA_MAN0001(),
            I.GEA_CV_ERR(), I.GEA_CV_WARN(),
            I.GEA_REGEX0001(), I.GEA_REGEX0002(), I.GEA_REGEX0003(), I.GEA_REGEX0004(),
            # --- SDRF ---
            S.GEA_SR0001(), S.GEA_SR0004(), S.GEA_SR0009(), S.GEA_SR0005(), S.GEA_SR0006(), S.GEA_SR0012(),
            S.GEA_EX0001(), S.GEA_EX0002(),
            S.GEA_AN0001(), S.GEA_AN0002(), S.GEA_TT0001(), S.GEA_AN0005(), S.GEA_AN0009(),
            S.GEA_MT0004(),
            S.GEA_LE0002(), S.GEA_LE0004(), S.GEA_LE0001(), S.GEA_AD0001(), S.GEA_AD0004(),
            S.GEA_DF0001(), S.GEA_DF0002(),
            S.GEA_CN0001(), S.GEA_RC0002(), S.GEA_UNDEF(),
            S.GEA_MAN0011(), S.GEA_MAN0012(),
            S.GEA_SDRF_REGEX(),
            # --- SDRF node グラフ / 属性名 ---
            N.GEA_EX0003(), N.GEA_EX0004(), N.GEA_LE0005(),
            N.GEA_AN0003(), N.GEA_AN0004(), N.GEA_AN0006(), N.GEA_AN0008(),
            N.GEA_ADN0004(), N.GEA_ADMN0004(), N.GEA_DADN0004(), N.GEA_DADMN0004(),
            N.GEA_ADN0001(), N.GEA_ADMN0001(), N.GEA_DADN0001(), N.GEA_DADMN0001(),
            N.GEA_SM0001(), N.GEA_SM0003(), N.GEA_SC0001(), N.GEA_NN0001(),
            N.GEA_SR0008(), N.GEA_PN0001(), N.GEA_PN0003(),
            N.GEA_LC0001(), N.GEA_FV0004(), N.GEA_G0011(),
            N.GEA_CA0001(), N.GEA_PV0001(), N.GEA_UA0001(), N.GEA_FV0001(),
            N.GEA_L0001(), N.GEA_MT0001(),
            # --- cross（IDF↔SDRF）---
            C.GEA_REF0001(), C.GEA_REF0006(), C.GEA_REF0007(),
            # --- BioSample DB 整合 ---
            B.GEA_BS0002(), B.GEA_BS0001(), B.GEA_BS0003(),
            # --- DRA/DB 参照整合 ---
            RDB.GEA_REF0002(), RDB.GEA_REF0003(), RDB.GEA_REF0004(), RDB.GEA_REF0005(), RDB.GEA_REF0008(),
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
            try:
                if not rule.applies(sub, self.context):
                    continue
            except Exception:
                pass
            results.extend(rule.validate(sub, self.context))
        for r in results:
            r["external"] = is_internal_ignore(r["rule_id"])
        return results
