"""BioProject 値ルール（文字種・データ形式）。biosample の R0058/R0013 と同型ロジック。

- BP_R0060: 非 ASCII 文字（= BS_R0058）。error。
- BP_R0059: 不正データ形式（前後/連続空白・囲みクオート。= BS_R0013）。warning。
検査対象: title / description / organism_name / publication reference（自由文フィールド）。
"""
from apps.bioproject.rules.base import BpRule
# 空白正規化・非 ASCII 判定は common に集約した共有ロジック（旧: apps.biosample.rules.value_ascii）
from common.text import normalize_data_format, _non_ascii


def _text_fields(rec):
    """自由文フィールド {ラベル: 値} を返す（None は除外）。"""
    fields = {"Title": rec.title, "Description": rec.description, "organism": rec.organism_name}
    for i, pub in enumerate(rec.publications):
        if pub.reference:
            fields[f"Publication[{i}].Reference"] = pub.reference
    return {k: v for k, v in fields.items() if v}


class BP_R0060(BpRule):
    rule_id = "BP_R0060"
    level = "error"
    target = "#fields"
    description = "Non-ASCII format characters detected."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for name, v in _text_fields(rec).items():
                if _non_ascii(v):
                    out.append(self.result(sample=rec.label, target=name,
                                           message=f"Non-ASCII characters detected in '{name}'. (Found: '{v}')"))
                    break
        return out


class BP_R0059(BpRule):
    rule_id = "BP_R0059"
    level = "warning"
    target = "#fields"
    description = "Invalid data format."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for name, v in _text_fields(rec).items():
                fixed = normalize_data_format(v)
                if fixed and fixed != v:
                    out.append(self.result(sample=rec.label, target=name,
                                           message=f"Invalid data format. ({name}: '{v}', Suggested: '{fixed}')"))
        return out
