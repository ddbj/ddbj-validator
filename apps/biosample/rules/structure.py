"""構造・重複系ルール（DB 非依存。フェーズ A）。

- BS_R0126: 複数パッケージ（1 submission に 1 package のみ）
- BS_R0061: 同名属性の複数値（1 値のみ許可）
- BS_R0003: submission 内の sample_title 重複
"""
from collections import Counter
from apps.biosample.rules.base import BsRule


class BS_R0126(BsRule):
    rule_id = "BS_R0126"
    level = "error"
    target = "package"
    description = "Single package is allowed in a submission."

    def validate(self, submission, context):
        packages = {r.package for r in submission.records if r.package}
        if len(packages) > 1:
            return [self.result(message=f"Single package is allowed in a submission. (Found: {sorted(packages)})")]
        return []


class BS_R0061(BsRule):
    rule_id = "BS_R0061"
    level = "error"
    target = "#attributes"
    description = "Multiple values detected. Only one value is allowed. First value was used for subsequent validation."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            multi = [name for name, vals in rec.attributes.items() if len(vals) > 1]
            for name in sorted(multi):
                out.append(self.result(sample=rec.sample_id, target=name,
                                       message=f"Multiple values detected for '{name}'. Only one value is allowed."))
        return out


class BS_R0003(BsRule):
    rule_id = "BS_R0003"
    level = "error"
    target = "sample_title"
    description = "Sample title is duplicated in the submission."

    def validate(self, submission, context):
        titles = [r.title for r in submission.records if r.title]
        dup = {t for t, c in Counter(titles).items() if c > 1}
        out = []
        for rec in submission.records:
            if rec.title in dup:
                out.append(self.result(sample=rec.sample_id,
                                       message=f"Sample title is duplicated in the submission. (title: '{rec.title}')"))
        return out
