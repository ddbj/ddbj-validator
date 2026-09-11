"""参照オブジェクトのアカウント整合ルール（MB_IR0040 / MB_SR0041）。内部 DB ＋ アカウント権限が必要。

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


class MB_SR0041(MbRule):
    # Name: BioSample not citable
    # BioSample の参照は SDRF 側（Comment[BioSample] 等）にしか無いため、
    # target に合わせて rule id も IR → SR に変更した（旧 MB_IR0041）。
    rule_id = "MB_SR0041"; level = "error"; target = "SDRF"
    requires_rdb = True; requires_auth = True
    description = "Referenced BioSample is not citable in the account."

    def validate(self, sub, context):
        """参照 BioSample が引用できるか。旧 MB_SR0022（属性が引けない）も統合した。

        次の 2 つを同じ error で受ける。どちらも「その BioSample は参照先にできない」を意味する。
        - account で引用できない（account_biosamples に無い）
        - 引用はできるが内部 DB から属性が取れない（旧 MB_SR0022。warning から error に昇格）

        SAMD 以外（NCBI の SAMN / EBI の SAMEA 等の外部 BioSample）は account 判定の
        対象外なので飛ばす。書式の妥当性は MB_SR0019 の担当。
        """
        citable = getattr(context, "account_biosamples", None)
        if citable is None or not sub.sdrf:
            return []
        citable = {str(x).strip().upper() for x in citable}
        attrs = getattr(context, "biosample_attrs", None)
        refs = sorted({s.strip().upper()
                       for s in _bs.referenced_samds(sub, _bs.ref_columns(context, default=_REF_DEFAULT))
                       if s.strip()})
        out = []
        for s in refs:
            if not s.startswith("SAMD"):
                continue
            if s not in citable:
                out.append(self.result(message=f"{self.description} (BioSample: '{s}')",
                                       agg_noun="BioSamples", field="BioSample", value=s))
            elif attrs is not None and not attrs.get(s):
                out.append(self.result(
                    message=f"{self.description} (BioSample: '{s}', no attribute found in the DB)",
                    agg_noun="BioSamples", field="BioSample", value=s))
        return out
