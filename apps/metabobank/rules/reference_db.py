"""参照オブジェクトの整合ルール（MB_IR0040 / MB_SR0041 / MB_IR0042 / MB_SR0051）。内部 DB が必要。

IDF の Comment[BioProject] と、SDRF が参照する BioSample（Comment[BioSample] /
Characteristics[biosample_accession]）が、その投稿アカウントで **引用できる（citable）** かを検証する。

**「所有しているか」ではなく「引用できるか」を見る。** 両者は次の点で違う:

- **permitted を含む。** 他人の登録でも外部参照を許可されていれば引用できる
- **umbrella の BioProject は引用できない。** umbrella は直接データに紐づけられないため、
  accession が発行されていても参照先にはできない
- accession 未発行のものは引用できない

**「存在しない」は別ルール**（`MB_IR0042` / `MB_SR0051`）。citable でない理由は
「他アカウント」「umbrella」「未採番」「そもそも存在しない」の 4 つあり、登録者から見て直し方が違う。
このうち**番号自体が誤り**である最後の 1 つだけを切り出し、登録をブロックする error にしている
（gea の GEA_REF0009 と同じ考え方）。

判定材料（context.account_bioprojects / account_biosamples / existing_*）は CLI が入れる。
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
        missing = _missing_bioprojects(sub, context)    # 存在しないものは MB_IR0042 の担当
        # agg_noun を付けると summary で「'first' etc, N Nouns」に集約される（details は全件）。
        return [self.result(message=f"{self.description} (BioProject: '{bp}')", agg_noun="BioProjects",
                            field="Comment[BioProject]", value=bp)
                for bp in refs
                if re.match(r"^(PRJDB|PSUB)", bp) and bp not in citable and bp not in missing]


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
        missing = _missing_biosamples(sub, context)     # 存在しないものは MB_SR0051 の担当
        out = []
        for s in refs:
            if not s.startswith("SAMD") or s in missing:
                continue
            if s not in citable:
                out.append(self.result(message=f"{self.description} (BioSample: '{s}')",
                                       agg_noun="BioSamples", field="BioSample", value=s))
            elif attrs is not None and not attrs.get(s):
                out.append(self.result(
                    message=f"{self.description} (BioSample: '{s}', no attribute found in the DB)",
                    agg_noun="BioSamples", field="BioSample", value=s))
        return out


# ---- 「そもそも存在しない」accession（MB_IR0042 / MB_SR0051）------------------
# `citable` が偽になる理由のうち**番号自体の誤り**だけを切り出す。実在集合は CLI が
# 内部 DB から入れる（`context.existing_bioprojects` / `existing_biosamples`）。
# **未取得（None）なら判定しない** = 新ルールは黙り、従来どおり MB_IR0040 / MB_SR0041 だけが出る。
# `PSUB` / `SSUB` は accession ではなく submission ID で引くテーブルが別なので対象外。
# `SAMN`（NCBI）/ `SAMEA`（EBI）も内部 DB では実在を引けないので対象外。

def _missing_bioprojects(sub, context):
    """参照 BioProject のうち DB に実在しないもの（大文字の集合）。"""
    existing = getattr(context, "existing_bioprojects", None)
    if existing is None or not sub.idf:
        return set()
    existing = {str(x).strip().upper() for x in existing}
    return {v.strip().upper() for v in sub.idf.get("Comment[BioProject]")
            if v.strip() and v.strip().upper().startswith("PRJDB")
            and v.strip().upper() not in existing}


def _missing_biosamples(sub, context):
    """参照 BioSample のうち DB に実在しないもの（大文字の集合）。"""
    existing = getattr(context, "existing_biosamples", None)
    if existing is None or not sub.sdrf:
        return set()
    existing = {str(x).strip().upper() for x in existing}
    return {s.strip().upper()
            for s in _bs.referenced_samds(sub, _bs.ref_columns(context, default=_REF_DEFAULT))
            if s.strip() and s.strip().upper().startswith("SAMD")
            and s.strip().upper() not in existing}


class MB_IR0042(MbRule):
    # Name: BioProject not found
    rule_id = "MB_IR0042"; level = "error"; target = "IDF"
    requires_rdb = True
    description = "Referenced BioProject does not exist."

    def validate(self, sub, context):
        return [self.result(message=f"{self.description} (BioProject: '{bp}')", agg_noun="BioProjects",
                            field="Comment[BioProject]", value=bp)
                for bp in sorted(_missing_bioprojects(sub, context))]


class MB_SR0051(MbRule):
    # Name: BioSample not found
    rule_id = "MB_SR0051"; level = "error"; target = "SDRF"
    requires_rdb = True
    description = "Referenced BioSample does not exist."

    def validate(self, sub, context):
        return [self.result(message=f"{self.description} (BioSample: '{s}')", agg_noun="BioSamples",
                            field="BioSample", value=s)
                for s in sorted(_missing_biosamples(sub, context))]
