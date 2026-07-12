"""BioSample 整合ルール（MB_SR0021/0022/0023）。DB 参照（内部 DB）。core は common/magetab/biosample。

SDRF の Characteristics[attr] を、参照 BioSample（Comment[BioSample] / Characteristics[biosample_accession] = SAMD）の
DB 属性と突合。context.biosample_attrs（SAMD -> {attr: value}）が None（未取得＝skip_db 等）ならスキップ。
"""
from apps.metabobank.rules.base import MbRule
from common.magetab import biosample as _bs

# mb の参照列（definitions.biosample_sync.biosample_ref_columns にも同値が定義済み）
_REF_DEFAULT = ("Comment[BioSample]", "Characteristics[biosample_accession]")


def _cols(context):
    return _bs.ref_columns(context, default=_REF_DEFAULT)


class MB_SR0021(MbRule):
    rule_id = "MB_SR0021"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "BioSample attribute referenced in Characteristics is missing in the BioSample."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        return [self.result(message=f"{self.description} ({samd}: '{attr}')",
                            line=ri + 1, assay=_bs.assay_name(sub, ri))
                for samd, attr, ri in _bs.iter_missing_attrs(sub, context, attrs, _cols(context))]


class MB_SR0022(MbRule):
    rule_id = "MB_SR0022"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Referenced BioSample has no attribute (not found in the account/DB)."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        return [self.result(message=f"{self.description} ({samd})",
                            line=ri + 1, assay=_bs.assay_name(sub, ri))
                for samd, ri in _bs.iter_unknown_biosamples(sub, attrs, _cols(context))]


class MB_SR0023(MbRule):
    rule_id = "MB_SR0023"; level = "error"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Characteristics value and BioSample attribute value do not match."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        out = []
        for samd, attr, sdrf_v, bs_v, ri in _bs.iter_value_mismatches(sub, context, attrs, _cols(context)):
            out.append(self.result(message=f"{self.description} ({samd} {attr}: SDRF '{sdrf_v}', BioSample '{bs_v}')",
                                    line=ri + 1, assay=_bs.assay_name(sub, ri)))
        return out
