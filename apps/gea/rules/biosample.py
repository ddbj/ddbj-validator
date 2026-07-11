"""BioSample 整合ルール（GEA_BS0001/0002/0003）。DB 参照（内部 DB）。core は common/magetab/biosample。

SDRF の Characteristics[attr] を、参照 BioSample（Comment[BioSample]=SAMD）の DB 属性と突合。
context.biosample_attrs（SAMD -> {attr: value}）が None（未取得＝skip_db 等）ならスキップ。
※これらは legacy rules.txt に無い GEA 追加ルール（MB_SR0021-0023 相当）。
"""
from apps.gea.rules.base import GeaRule
from common.magetab import biosample as _bs


class GEA_BS0002(GeaRule):
    rule_id = "GEA_BS0002"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Referenced BioSample is not found in the account/DB."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        return [self.result(message=f"{self.description} ({samd})")
                for samd in _bs.iter_unknown_biosamples(sub, attrs, _bs.ref_columns(context))]


class GEA_BS0001(GeaRule):
    rule_id = "GEA_BS0001"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "BioSample attribute referenced in Characteristics is missing in the BioSample."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        return [self.result(message=f"{self.description} ({samd}: '{attr}')")
                for samd, attr in _bs.iter_missing_attrs(sub, context, attrs, _bs.ref_columns(context))]


class GEA_BS0003(GeaRule):
    rule_id = "GEA_BS0003"; level = "error"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Characteristics value and BioSample attribute value do not match."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        out = []
        for samd, attr, sdrf_v, bs_v in _bs.iter_value_mismatches(sub, context, attrs, _bs.ref_columns(context)):
            out.append(self.result(
                message=f"{self.description} ({samd} {attr}: SDRF '{sdrf_v}' != BS '{bs_v}')",
                autofix=True, samd=samd, attr=attr, new_value=bs_v))
        return out
