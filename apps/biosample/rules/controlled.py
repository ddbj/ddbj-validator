"""controlled vocabulary（属性別 CV）ルール（C 群）。

CV ソースは context.cv_attr（attributes_packages.json の attributes[name].allowed_values から構築）。
Ruby 実装（biosample_validator.rb rule:2 / rule:138）に準拠。

- BS_R0002（warning, autofix）: CV 属性で、値が CV に大文字小文字違いで一致する場合に
  正しい表記を提案（autofix）。sex の "M"/"F" は "male"/"female" へ特殊置換。
  完全一致・全く一致しない場合は発火しない（後者は R0138 の担当）。
- BS_R0138（error）: CV 属性で、値が CV リストに（完全一致で）存在しない場合にエラー。
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty, is_missing_value


def _cv_attributes(rec, cv_attr):
    """レコードの (attr_name, value) のうち、CV 対象かつ非空・非 missing のものを列挙。"""
    for name, vals in rec.attributes.items():
        if name not in cv_attr:
            continue
        for v in vals:
            if is_empty(v) or is_missing_value(v):
                continue
            yield name, v


class BS_R0002(BsRule):
    rule_id = "BS_R0002"
    level = "warning"
    target = "#attributes"
    description = "Attribute value is not in controlled terms."

    def validate(self, submission, context):
        cv_attr = context.cv_attr or {}
        if not cv_attr:
            return []
        out = []
        for rec in submission.records:
            for name, val in _cv_attributes(rec, cv_attr):
                replace = ""
                if name == "sex" and val.casefold() in ("m", "f"):
                    replace = "male" if val.casefold() == "m" else "female"
                else:
                    for term in cv_attr[name]:
                        if term.casefold() == val.casefold() and term != val:
                            replace = term  # 大文字小文字違いの一致 → 正表記を提案
                            break
                if replace:
                    out.append(self.result(
                        sample=(rec.sample_name or rec.accession),
                        message=(f"Attribute value is not in controlled terms. "
                                 f"({name}: '{val}', Suggested: '{replace}')"),
                        autofix=True, attribute=name, old_value=val, new_value=replace))
        return out


class BS_R0138(BsRule):
    rule_id = "BS_R0138"
    level = "error"
    target = "#attributes"
    description = "Attribute value is not in controlled terms."

    def validate(self, submission, context):
        cv_attr = context.cv_attr or {}
        if not cv_attr:
            return []
        out = []
        for rec in submission.records:
            for name, val in _cv_attributes(rec, cv_attr):
                if val not in cv_attr[name]:  # 完全一致で CV に無い
                    out.append(self.result(
                        sample=(rec.sample_name or rec.accession),
                        message=(f"Attribute value is not in controlled terms. "
                                 f"({name}: '{val}')")))
        return out
