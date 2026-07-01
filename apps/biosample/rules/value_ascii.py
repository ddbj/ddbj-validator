"""文字種・任意属性の値ルール（DB 非依存。フェーズ A 続き）。

- BS_R0058: 属性値に非 ASCII 文字が含まれる
- BS_R0100: 任意属性に missing 値が入っている（任意は空でよい）
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value


def _non_ascii(v):
    try:
        v.encode("ascii")
        return False
    except (UnicodeEncodeError, AttributeError):
        return True


class BS_R0058(BsRule):
    rule_id = "BS_R0058"
    level = "error"
    target = "#attributes"
    description = "Non-ASCII format characters detected."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            checked = dict(rec.attributes)
            # Description 由来も対象
            extra = {"sample_name": rec.sample_name, "sample_title": rec.title, "organism": rec.organism}
            for name, v in extra.items():
                if v:
                    checked.setdefault(name, [v])
            for name in sorted(checked):
                for v in checked[name]:
                    if v and _non_ascii(v):
                        out.append(self.result(sample=(rec.sample_name or rec.accession), target=name,
                                               message=f"Non-ASCII characters detected in '{name}'. (Found: '{v}')"))
                        break
        return out


class BS_R0100(BsRule):
    rule_id = "BS_R0100"
    level = "warning"
    target = "#attributes"
    description = "Missing values are not necessary for optional attributes. Leave values empty when there is no information."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.package or context.package_def(rec.package) is None:
                continue
            uses = context.attribute_uses(rec.package)
            for name, vals in rec.attributes.items():
                use = uses.get(name, "")
                if use in ("mandatory", "either_one_mandatory"):
                    continue  # 任意属性のみ対象
                for v in vals:
                    if v and is_missing_value(v):
                        out.append(self.result(sample=(rec.sample_name or rec.accession), target=name,
                                               message=f"Missing value is unnecessary for optional attribute '{name}'."))
                        break
        return out
