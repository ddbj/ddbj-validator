"""BioSample 整合ルール（GEA_BS0001/0002/0003）。DB 参照（内部 DB）。core は common/magetab/biosample。

SDRF の Characteristics[attr] を、参照 BioSample（Comment[BioSample]=SAMD）の DB 属性と突合。
いずれも **account が分からないと判定できない**（`allowed_biosamples` = その account が参照してよい SAMD)
ため `requires_auth = True`（2026-09-20）。
context.biosample_attrs（SAMD -> {attr: value}）が None（未取得＝skip_db 等）ならスキップ。
※これらは legacy rules.txt に無い GEA 追加ルール（MB_SR0021-0023 相当）。
"""
from apps.gea.rules.base import GeaRule
from common.magetab import biosample as _bs


class GEA_BS0002(GeaRule):
    """**deprecated**（validator に登録しない。2026-09-20）。

    `allowed_biosamples`（account 所有 ∪ permit）でゲートしているため、**account 外の SAMD では
    決して発火しない**。account 外の参照は `GEA_REF0002` が報告しており、役割が重複していた。
    残っていた出番は「allowed に入っているのに属性が 1 つも無い」という狭い場合だけで、
    Characteristics で参照している属性の欠落は `GEA_BS0001` が見る。クラスは rule 表のために残す。
    """
    deprecated = True
    rule_id = "GEA_BS0002"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Referenced BioSample is not found in the account/DB."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        allowed = getattr(context, "allowed_biosamples", None)   # account 外の SAMD はチェック対象外
        return [self.result(message=f"{self.description} ({samd})",
                            line=ri + 1, assay=_bs.assay_name(sub, ri))
                for samd, ri in _bs.iter_unknown_biosamples(sub, attrs, _bs.ref_columns(context), allowed=allowed)]


class GEA_BS0001(GeaRule):
    """**deprecated**（validator に登録しない。2026-09-20）。

    突合の中核 `common/magetab/biosample.py:iter_missing_attrs` が何も yield しないため
    **決して発火しない**。「SDRF 値あり × BS 空/不在」は値不一致として `GEA_BS0003` が拾い、
    「SDRF 空 × BS 空/不在」は両方 not present なので報告しない、という整理になっているため。
    MetaboBank の対応物 `MB_SR0021` も同じ理由で deprecated。クラスは rule 表のために残す。
    """
    deprecated = True
    rule_id = "GEA_BS0001"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "BioSample attribute referenced in Characteristics is missing in the BioSample."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        return [self.result(message=f"{self.description} ({samd}: '{attr}')",
                            line=ri + 1, assay=_bs.assay_name(sub, ri))
                for samd, attr, ri in _bs.iter_missing_attrs(sub, context, attrs, _bs.ref_columns(context))]


class GEA_BS0003(GeaRule):
    rule_id = "GEA_BS0003"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True  # 2026-09-17 error→warning
    description = "Characteristics value and BioSample attribute value do not match."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        out = []
        for samd, attr, sdrf_v, bs_v, ri in _bs.iter_value_mismatches(sub, context, attrs, _bs.ref_columns(context)):
            # 双方向 autofix 用の構造化フィールド（sdrf_value/bs_value）も付与
            out.append(self.result(
                message=f"{self.description} ({samd} {attr}: SDRF:'{sdrf_v}', BioSample:'{bs_v}')",
                autofix=True, samd=samd, attr=attr, new_value=bs_v,
                sdrf_value=sdrf_v, bs_value=bs_v, line=ri + 1, assay=_bs.assay_name(sub, ri)))
        return out
