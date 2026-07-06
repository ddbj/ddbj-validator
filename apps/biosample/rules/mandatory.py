"""必須・パッケージ系の基礎ルール（DB 非依存。フェーズ1）。

- BS_R0018: Sample name 欠落
- BS_R0020: organism 欠落
- BS_R0025: Package 情報欠落
- BS_R0026: 未知の Package
- BS_R0027: 必須属性の欠落（collection_date / geo_loc_name を除く。JSON 定義の mandatory を参照）

「欠落」の判定は、値が無い／空文字を欠落とみなす（missing 等の reporting term は別ルールで扱う）。
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty


class BS_R0018(BsRule):
    rule_id = "BS_R0018"
    level = "error"
    target = "sample_name"
    description = "Sample name is missing."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if is_empty(rec.sample_name):
                out.append(self.result(sample=rec.accession, message=self.description))
        return out


class BS_R0020(BsRule):
    rule_id = "BS_R0020"
    level = "error"
    target = "organism"
    description = "Organism is missing."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if is_empty(rec.organism):
                out.append(self.result(sample=rec.sample_id, message=self.description))
        return out


class BS_R0025(BsRule):
    rule_id = "BS_R0025"
    level = "error"
    target = "package"
    description = "Package information is missing."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if is_empty(rec.package):
                out.append(self.result(sample=rec.sample_id, message=self.description))
        return out


class BS_R0026(BsRule):
    rule_id = "BS_R0026"
    level = "error"
    target = "package"
    description = "Sample refers to unknown Package."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if is_empty(rec.package):
                continue  # 欠落は R0025 で扱う
            if context.package_def(rec.package) is None:
                out.append(self.result(sample=rec.sample_id,
                                       message=f"Sample refers to unknown Package. (Found: '{rec.package}')"))
        return out


class BS_R0027(BsRule):
    rule_id = "BS_R0027"
    level = "error"
    target = "#mandatory_attributes"
    description = "Sample has missing mandatory attribute(s)."

    # 未入力（欠落）は collection_date / geo_loc_name も含めて R0027 で検出する
    # （present だが無効な missing 記載は R0137 が担当し、二重には出さない）。
    _EXCLUDE = set()

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if is_empty(rec.package) or context.package_def(rec.package) is None:
                continue  # package が無効なら R0025/R0026 側
            mandatory = context.mandatory_attributes(rec.package) - self._EXCLUDE
            # Description 由来でも充足とみなす固定属性（XML では Attributes に出ないため）
            desc_fields = {
                "sample_name": rec.sample_name,
                "sample_title": rec.title,
                "organism": rec.organism,
                "taxonomy_id": rec.taxonomy_id,
            }
            missing = []
            for name in sorted(mandatory):
                if name in desc_fields:
                    if not is_empty(desc_fields[name]) or not is_empty(rec.attr(name)):
                        continue
                    missing.append(name)
                elif is_empty(rec.attr(name)):
                    missing.append(name)
            if missing:
                out.append(self.result(
                    sample=rec.sample_id,
                    message=f"Sample has missing mandatory attribute(s): {', '.join(missing)}"))
        return out
