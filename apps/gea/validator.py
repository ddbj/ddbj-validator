"""GEA ルールの登録と実行。bs/bp/dra/metabobank と同型。

only_type（None/microarray/sequencing）により submission type 別にルールを出し分ける。
"""
from common.rules.simple import SimpleValidator
from apps.gea.rules.base import INTERNAL_IGNORE_RULE_IDS
from apps.gea.rules import idf as I
from apps.gea.rules import sdrf as S
from apps.gea.rules import nodes as N
from apps.gea.rules import cross as C
from apps.gea.rules import biosample as B
from apps.gea.rules import reference_db as RDB


class Validator(SimpleValidator):
    # モード別スキップ・実行・external 付与は common.rules.simple.SimpleValidator。
    # ここはルールの登録順（手で並べる）と internal ignore 集合だけを持つ。
    ignore_ids = INTERNAL_IGNORE_RULE_IDS

    def build_rules(self, context):
        return [
            # --- IDF ---
            I.GEA_C0001(), I.GEA_C0002(), I.GEA_C0008(),
            I.GEA_COM0001(),
            I.GEA_G0001(), I.GEA_G0002(), I.GEA_G0009(), I.GEA_G0004(), I.GEA_G0006(),
            I.GEA_G0015(),
            # GEA_G0013 は deprecated（2026-09-18。additional file 廃止で検査対象が無い）のため登録しない。
            I.GEA_G0007(), I.GEA_G0012(), I.GEA_G0016(),
            I.GEA_ED0001(), I.GEA_EF0001(), I.GEA_EF0003(),
            I.GEA_PB0002(),
            I.GEA_PR0001(), I.GEA_PR0002(), I.GEA_PR0003(), I.GEA_PR0005(), I.GEA_PR0006(),
            # GEA_PR0008-0015（submission type ごとの必須 protocol）は GEA_PR0018 / GEA_PR0019 に
            # 集約したため登録しない。
            I.GEA_PR0018(), I.GEA_PR0019(), I.GEA_PR0007(), I.GEA_PR0020(),
            I.GEA_RC0001(), I.GEA_MAN0001(),
            I.GEA_CV_ERR(), I.GEA_CV_WARN(),
            # GEA_REGEX0002 は deprecated（2026-09-19。Protocol Name の値形式を廃止）。
            I.GEA_REGEX0001(), I.GEA_REGEX0003(), I.GEA_REGEX0004(),
            # --- SDRF ---
            S.GEA_SR0001(), S.GEA_SR0004(), S.GEA_SR0009(), S.GEA_SR0005(), S.GEA_SR0006(), S.GEA_SR0012(),
            S.GEA_EX0001(), S.GEA_EX0002(),
            # GEA_AN0002 / GEA_AN0005 は deprecated（2026-09-18。Technology Type 列の有無・array assay 強制を廃止）のため登録しない。
            # GEA_TT0001 / GEA_AN0009 は deprecated（2026-09-18。SDRF Technology Type 廃止）のため登録しない。
            S.GEA_AN0001(),
            S.GEA_COM0004(), S.GEA_MT0004(),
            S.GEA_LE0002(), S.GEA_LE0004(), S.GEA_LE0001(), S.GEA_AD0001(), S.GEA_AD0004(),
            S.GEA_DF0001(), S.GEA_DF0002(),
            # GEA_RC0002 は deprecated（2026-09-17。Comment 列の重複は取込で畳む）のため登録しない。
            S.GEA_CN0001(), S.GEA_UNDEF(), S.GEA_SR0003(),
            S.GEA_MAN0011(), S.GEA_MAN0012(),
            S.GEA_SDRF_REGEX(),
            # --- SDRF node グラフ / 属性名 ---
            N.GEA_EX0003(), N.GEA_EX0004(), N.GEA_LE0005(),
            N.GEA_AN0003(), N.GEA_AN0004(), N.GEA_AN0006(), N.GEA_AN0008(),
            # GEA_DADMN0001 / GEA_DADMN0004 は deprecated（2026-09-19。Processed Data File に統合）。
            N.GEA_ADN0004(), N.GEA_ADMN0004(), N.GEA_DADN0004(),
            N.GEA_ADN0001(), N.GEA_ADMN0001(), N.GEA_DADN0001(),
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

    def applies(self, rule, sub):
        """only_type（microarray / sequencing）で限定されたルールは submission type が合うときだけ適用。
        判定に失敗したら従来どおり適用側に倒す。"""
        try:
            return rule.applies(sub, self.context)
        except Exception:
            return True
