"""文字種・任意属性の値ルール（DB 非依存。フェーズ A 続き）。

- BS_R0058: 属性値に非 ASCII 文字が含まれる
- BS_R0100: 任意属性に missing 値が入っている（任意は空でよい）
- BS_R0012: 特殊文字（℃/°C/μm/μ 等）を推奨表記へ置換（autofix）
"""
import re
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value, is_empty
# 純テキストユーティリティは common に集約（bioproject と共有。app 間相互 import を避ける）。
from common.text import (
    _WS_RE, _HTML_RE, normalize_data_format, apply_special_chars, _non_ascii, _has_html,
)


class BS_R0013(BsRule):
    rule_id = "BS_R0013"
    level = "warning"
    target = "#attributes"
    description = "Invalid data format."

    def validate(self, submission, context):
        # autocleanup（ddbj の cleanup 相当）: 全属性値を正規化（連続空白畳み込み＋前後クオート除去）し
        # **in-place で置換**する。validator.run の最初に実行され、cleanup 後の値で後続ルールが評価される。
        # → 専用 autofix（geo/date 等）との二重提案は起きない（後続は正規化済みの値を見るため）。
        # missing 値は対象外。sample_name は autofix のサンプル同定キーのため除外。Ruby v invalid_data_format 準拠。
        out = []
        for rec in submission.records:
            for name, vals in rec.attributes.items():
                if name == "sample_name":
                    continue
                for i, v in enumerate(vals):
                    if is_empty(v) or is_missing_value(v):
                        continue
                    fixed = normalize_data_format(v)
                    if fixed and fixed != v:
                        vals[i] = fixed  # in-place cleanup（後続ルールが cleaned 値を読む）
                        out.append(self.autofix_result(
                            sample=rec.sample_id, target=name,
                            message=f"Invalid data format. ({name}: '{v}', Suggested: '{fixed}')",
                            attribute=name, old_value=v, new_value=fixed))
        return out


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
                        pos = "".join("[### Non-ASCII character ###]" if ord(c) > 127 else c for c in v)
                        out.append(self.result(sample=rec.sample_id, target=name,
                                               anno_cols=[{"key": "Attribute", "value": name},
                                                          {"key": "Attribute value", "value": v},
                                                          {"key": "Position", "value": pos}],
                                               message=f"Non-ASCII characters detected in '{name}'. (Found: '{v}')"))
                        break
        return out


class BS_R0142(BsRule):
    rule_id = "BS_R0142"
    level = "error"
    target = "#attributes"
    description = "Sample description should not include HTML markup."

    def validate(self, submission, context):
        # INSDC Sample Minimum Specification: メタデータに HTML マークアップを含めてはならない（reject 対象）。
        # R0058(非ASCII) は HTML タグ（ASCII）を捕まえないため専用に検出する。対象は属性値＋Description 由来。
        out = []
        for rec in submission.records:
            checked = dict(rec.attributes)
            extra = {"sample_name": rec.sample_name, "sample_title": rec.title, "organism": rec.organism}
            for name, v in extra.items():
                if v:
                    checked.setdefault(name, [v])
            for name in sorted(checked):
                for v in checked[name]:
                    if _has_html(v):
                        out.append(self.result(
                            sample=rec.sample_id, target=name,
                            message=f"HTML markup is not allowed in metadata; remove HTML tags. ({name}: '{v}')"))
                        break
        return out


class BS_R0100(BsRule):
    rule_id = "BS_R0100"
    level = "warning"
    target = "#attributes"
    description = "Missing values are not necessary for optional attributes. Leave values empty when there is no information."

    def validate(self, submission, context):
        # missing 系（INSDC CV）に加え、非推奨 null（NA / unknown / . / - 等 null_not_recommended）も
        # missing 相当として拾う（production 準拠。R0001 が NA→missing 補正するのと同じ null 集合）。
        nnr = context.null_not_recommended or []

        def _is_null(v):
            if is_missing_value(v):
                return True
            for pat in nnr:
                try:
                    if re.fullmatch(pat, v.strip(), re.I):
                        return True
                except re.error:
                    continue
            return False

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
                    if v and _is_null(v):
                        out.append(self.result(sample=rec.sample_id, target=name,
                                               anno_cols=[{"key": "Attribute name", "value": name},
                                                          {"key": "Attribute value", "value": v},
                                                          {"key": "Suggested value", "value": ""}],
                                               message=f"Missing value is unnecessary for optional attribute '{name}'."))
                        break
        return out


class BS_R0012(BsRule):
    rule_id = "BS_R0012"
    level = "warning"
    target = "#all"
    description = "Special character is included."

    def validate(self, submission, context):
        # 属性値の特殊文字（℃/°C/μm/μ 等）を推奨表記へ置換する autofix。
        # autocleanup（BS_R0013 の直後）として **in-place で置換** し、後続ルールは置換済みの値を読む。
        # → ℃ 等は R0058(非ASCII) より先に ASCII 表記へ直るため R0058 の二重検知を避けられる（production 準拠）。
        special = context.special_chars or {}
        if not special:
            return []
        out = []
        for rec in submission.records:
            for name, vals in rec.attributes.items():
                for i, v in enumerate(vals):
                    if not v or is_missing_value(v):
                        continue
                    fixed = apply_special_chars(v, special)
                    if fixed != v:
                        vals[i] = fixed  # in-place（後続ルールが置換済み値を読む）
                        out.append(self.autofix_result(
                            sample=rec.sample_id, target=name,
                            message=f"Special character is included. ({name}: '{v}', Suggested: '{fixed}')",
                            attribute=name, old_value=v, new_value=fixed, suggest_key="Suggestion"))
        return out
