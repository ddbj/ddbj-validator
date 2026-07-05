"""文字種・任意属性の値ルール（DB 非依存。フェーズ A 続き）。

- BS_R0058: 属性値に非 ASCII 文字が含まれる
- BS_R0100: 任意属性に missing 値が入っている（任意は空でよい）
- BS_R0012: 特殊文字（℃/°C/μm/μ 等）を推奨表記へ置換（autofix）
"""
import re
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value, is_empty


_WS_RE = re.compile(r"\s+")


def normalize_data_format(v):
    """連続空白の畳み込み（前後 strip＋タブ/改行/連続空白→半角空白1つ）＋前後を囲む対クオートの除去。
    Ruby v invalid_data_format(String#squish 相当) に準拠。補正不要なら元の値と同じ文字列を返す。"""
    s = _WS_RE.sub(" ", v.strip())
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = _WS_RE.sub(" ", s[1:-1].strip())
    return s


def apply_special_chars(value, special_chars):
    """special_chars に従い特殊文字を置換した文字列を返す。
    長いキーを先に処理し "μm"→"micro"+"m" のような部分置換を防ぐ。"""
    out = value
    for target in sorted(special_chars, key=len, reverse=True):
        out = out.replace(target, special_chars[target])
    return out


def _non_ascii(v):
    try:
        v.encode("ascii")
        return False
    except (UnicodeEncodeError, AttributeError):
        return True


class BS_R0013(BsRule):
    rule_id = "BS_R0013"
    level = "warning"
    target = "#attributes"
    description = "Invalid data format."

    # 専用の書式 autofix を持つ属性は二重提案を避けるため除外
    # （collection_date=R0136 / geo_loc_name=R0094 / lat_lon=R0009 / organism=R0045 / host=R0015 / component_organism=R0105）。
    _EXCLUDE = {"collection_date", "geo_loc_name", "lat_lon",
                "organism", "host", "component_organism"}

    def validate(self, submission, context):
        # 全属性値の連続空白畳み込み・前後クオート除去（missing 値は対象外）。Ruby v invalid_data_format 準拠。
        out = []
        for rec in submission.records:
            for name, vals in rec.attributes.items():
                if name in self._EXCLUDE:
                    continue
                for v in vals:
                    if is_empty(v) or is_missing_value(v):
                        continue
                    fixed = normalize_data_format(v)
                    if fixed and fixed != v:
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
                        out.append(self.result(sample=rec.sample_id, target=name,
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
                        out.append(self.result(sample=rec.sample_id, target=name,
                                               message=f"Missing value is unnecessary for optional attribute '{name}'."))
                        break
        return out


class BS_R0012(BsRule):
    rule_id = "BS_R0012"
    level = "warning"
    target = "#all"
    description = "Special character is included."

    def validate(self, submission, context):
        # 属性値に特殊文字（℃/°C/μm/μ 等）が含まれる場合、推奨表記へ置換する autofix 提案。
        special = context.special_chars or {}
        if not special:
            return []
        out = []
        for rec in submission.records:
            for name, vals in rec.attributes.items():
                for v in vals:
                    if not v or is_missing_value(v):
                        continue
                    fixed = apply_special_chars(v, special)
                    if fixed != v:
                        out.append(self.autofix_result(
                            sample=rec.sample_id, target=name,
                            message=f"Special character is included. ({name}: '{v}', Suggested: '{fixed}')",
                            attribute=name, old_value=v, new_value=fixed))
        return out
