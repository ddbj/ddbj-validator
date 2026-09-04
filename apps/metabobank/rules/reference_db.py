"""参照オブジェクトのアカウント整合ルール（MB_IR0040 / MB_IR0041）。内部 DB ＋ アカウント権限が必要。

IDF の Comment[BioProject] と、SDRF が参照する BioSample（Comment[BioSample] /
Characteristics[biosample_accession]）が、その投稿アカウントで登録済み（所有 or DRA permit）かを検証する。
context.account_bioprojects / account_biosamples は CLI が DRA の db_meta を用いて取得する
（None＝未取得＝スキップ。gea の GEA_REF0002 と同じ骨格）。
"""
import re

from apps.metabobank.rules.base import MbRule
from common.magetab import biosample as _bs

# BioSample 参照列。MB_SR0021/0022/0023 と同じ定義（definitions.biosample_sync.biosample_ref_columns）を使う。
_REF_DEFAULT = ("Comment[BioSample]", "Characteristics[biosample_accession]")


class MB_IR0040(MbRule):
    rule_id = "MB_IR0040"; level = "error"; target = "IDF"
    requires_rdb = True; requires_auth = True
    description = "Referenced BioProject is not found in the account."

    def validate(self, sub, context):
        owned = getattr(context, "account_bioprojects", None)
        if owned is None or not sub.idf:
            return []
        owned = {str(x).strip().upper() for x in owned}
        refs = sorted({v.strip().upper() for v in sub.idf.get("Comment[BioProject]") if v.strip()})
        # agg_noun を付けると summary で「'first' etc, N Nouns」に集約される（details は全件）。
        return [self.result(message=f"{self.description} (BioProject: '{bp}')", agg_noun="BioProjects")
                for bp in refs if re.match(r"^(PRJDB|PSUB)", bp) and bp not in owned]


class MB_IR0041(MbRule):
    # BioSample の参照は SDRF 側（Comment[BioSample] 等）にしか無いため target は SDRF。
    rule_id = "MB_IR0041"; level = "error"; target = "SDRF"
    requires_rdb = True; requires_auth = True
    description = "Referenced BioSample is not found in the account."

    def validate(self, sub, context):
        owned = getattr(context, "account_biosamples", None)
        if owned is None or not sub.sdrf:
            return []
        owned = {str(x).strip().upper() for x in owned}
        refs = sorted({s.strip().upper()
                       for s in _bs.referenced_samds(sub, _bs.ref_columns(context, default=_REF_DEFAULT))
                       if s.strip()})
        return [self.result(message=f"{self.description} (BioSample: '{s}')", agg_noun="BioSamples")
                for s in refs if s.startswith("SAMD") and s not in owned]
