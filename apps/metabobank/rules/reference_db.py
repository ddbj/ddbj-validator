"""参照オブジェクトのアカウント整合ルール（MB_IR0040 / MB_IR0041）。内部 DB ＋ アカウント権限が必要。

IDF の Comment[BioProject] と、SDRF が参照する BioSample（Comment[BioSample] /
Characteristics[biosample_accession]）が、その投稿アカウントで **引用できる（citable）** かを検証する。

**「所有しているか」ではなく「引用できるか」を見る。** 両者は次の点で違う:

- **permitted を含む。** 他人の登録でも外部参照を許可されていれば引用できる
- **umbrella の BioProject は引用できない。** umbrella は直接データに紐づけられないため、
  accession が発行されていても参照先にはできない
- accession 未発行のものは引用できない

判定材料（context.account_bioprojects / account_biosamples）は CLI が入れる。
`DDBJ_RECORD_API_URL` があれば record-api の `?scope=citable` から、無ければ従来どおり
内部 DB（所有 ∪ DRA permit）から取る。**None＝判定材料が無い＝スキップ**
（gea の GEA_REF0002 と同じ骨格）。
"""
import re

from apps.metabobank.rules.base import MbRule
from common.magetab import biosample as _bs

# BioSample 参照列。MB_SR0021/0022/0023 と同じ定義（definitions.biosample_sync.biosample_ref_columns）を使う。
_REF_DEFAULT = ("Comment[BioSample]", "Characteristics[biosample_accession]")


class MB_IR0040(MbRule):
    # Name: BioProject not citable
    rule_id = "MB_IR0040"; level = "error"; target = "IDF"
    requires_rdb = True; requires_auth = True
    description = "Referenced BioProject is not citable in the account."

    def validate(self, sub, context):
        citable = getattr(context, "account_bioprojects", None)
        if citable is None or not sub.idf:
            return []
        citable = {str(x).strip().upper() for x in citable}
        refs = sorted({v.strip().upper() for v in sub.idf.get("Comment[BioProject]") if v.strip()})
        # agg_noun を付けると summary で「'first' etc, N Nouns」に集約される（details は全件）。
        return [self.result(message=f"{self.description} (BioProject: '{bp}')", agg_noun="BioProjects",
                            field="Comment[BioProject]", value=bp)
                for bp in refs if re.match(r"^(PRJDB|PSUB)", bp) and bp not in citable]


class MB_IR0041(MbRule):
    # Name: BioSample not citable
    # BioSample の参照は SDRF 側（Comment[BioSample] 等）にしか無いため target は SDRF。
    rule_id = "MB_IR0041"; level = "error"; target = "SDRF"
    requires_rdb = True; requires_auth = True
    description = "Referenced BioSample is not citable in the account."

    def validate(self, sub, context):
        citable = getattr(context, "account_biosamples", None)
        if citable is None or not sub.sdrf:
            return []
        citable = {str(x).strip().upper() for x in citable}
        refs = sorted({s.strip().upper()
                       for s in _bs.referenced_samds(sub, _bs.ref_columns(context, default=_REF_DEFAULT))
                       if s.strip()})
        return [self.result(message=f"{self.description} (BioSample: '{s}')", agg_noun="BioSamples",
                            field="BioSample", value=s)
                for s in refs if s.startswith("SAMD") and s not in citable]
