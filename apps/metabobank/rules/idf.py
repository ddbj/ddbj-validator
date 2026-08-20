"""IDF ルール（MB_IR）。definitions.json の idf.* を data 駆動で参照。"""
import datetime
import re
from apps.metabobank.rules.base import MbRule, null_values

_DATE_OK = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
_DATE_FIELDS = ("Public Release Date", "Comment[Submission Date]", "Comment[Last Update Date]", "Date of Experiment")


def _idf(context):
    return (context.definitions or {}).get("idf", {})


def _empty(v):
    return v is None or str(v).strip() == ""


class MB_IR0003(MbRule):
    rule_id = "MB_IR0003"; level = "error"; target = "IDF"
    description = "Field names are duplicated."

    def validate(self, sub, context):
        if not sub.idf or not sub.idf.duplicate_fields:
            return []
        return [self.result(message=f"{self.description} ({', '.join(sorted(set(sub.idf.duplicate_fields)))})")]


class MB_IR0004(MbRule):
    rule_id = "MB_IR0004"; level = "error"; target = "IDF"
    description = "Only pre-defined fields are allowed."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        allowed = set(_idf(context).get("fields", []))
        bad = [n for n in sub.idf.field_order if n not in allowed]
        return [self.result(message=f"{self.description} ({', '.join(bad)})")] if bad else []


class _RequiredBase(MbRule):
    _key = None
    def validate(self, sub, context):
        if not sub.idf:
            return []
        req = _idf(context).get(self._key, [])
        ignore = set(_idf(context).get("required_ignore_error", []))
        miss = [f for f in req if f not in ignore and _empty(" ".join(sub.idf.get(f)))]
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class MB_IR0005(_RequiredBase):
    rule_id = "MB_IR0005"; level = "error"; target = "IDF"; _key = "required_error"
    description = "IDF has missing mandatory field(s)."


class MB_IR0006(_RequiredBase):
    rule_id = "MB_IR0006"; level = "warning"; target = "IDF"; _key = "required_warning"
    description = "IDF has missing mandatory field(s)."


class MB_IR0007(MbRule):
    rule_id = "MB_IR0007"; level = "error"; target = "IDF"
    description = "IDF has null value(s) for mandatory field(s)."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        bad = []
        for f in _idf(context).get("required_not_null", []):
            vals = sub.idf.get(f)
            if vals and all(_empty(v) or v.strip() in nulls for v in vals):
                bad.append(f)
        return [self.result(message=f"{self.description} ({', '.join(bad)})")] if bad else []


class _GroupBase(MbRule):
    _key = None
    def validate(self, sub, context):
        if not sub.idf:
            return []
        groups = _idf(context).get(self._key, {})
        out = []
        for gname, fields_ in (groups.items() if isinstance(groups, dict) else []):
            present = [f for f in fields_ if not _empty(" ".join(sub.idf.get(f)))]
            if present and len(present) < len(fields_):
                miss = [f for f in fields_ if _empty(" ".join(sub.idf.get(f)))]
                out.append(self.result(message=f"{self.description} ({gname}: {', '.join(miss)})"))
        return out


class MB_IR0008(_GroupBase):
    rule_id = "MB_IR0008"; level = "error"; target = "IDF"; _key = "required_group_error"
    description = "All fields are required for the field group."


class MB_IR0009(_GroupBase):
    rule_id = "MB_IR0009"; level = "warning"; target = "IDF"; _key = "required_group_warning"
    description = "All fields are required for the field group."


class MB_IR0010(MbRule):
    rule_id = "MB_IR0010"; level = "error"; target = "IDF"
    description = "Multiple values are provided for a single-value field."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        single = _idf(context).get("single_value", [])
        bad = [f for f in single if len(sub.idf.get(f)) > 1]
        return [self.result(message=f"{self.description} ({', '.join(bad)})")] if bad else []


class MB_IR0011(MbRule):
    rule_id = "MB_IR0011"; level = "error"; target = "IDF"
    description = "Study description is short. Please provide more than 100 characters."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        desc = sub.idf.first("Study Description")
        if desc and len(desc.strip()) < 100:
            return [self.result(message=f"{self.description} (Found: {len(desc.strip())} chars)")]
        return []


class MB_IR0013(MbRule):
    rule_id = "MB_IR0013"; level = "error"; target = "IDF"
    description = "Invalid date format. Use YYYY-MM-DD."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        out = []
        for f in _DATE_FIELDS:
            v = sub.idf.first(f).strip()
            if v and not _DATE_OK.match(v):
                out.append(self.result(message=f"{self.description} ({f}: '{v}')"))
        return out


class MB_IR0033(MbRule):
    rule_id = "MB_IR0033"; level = "error"; target = "IDF"
    description = "Future date is not allowed."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        today = datetime.date.today()
        out = []
        for f in _DATE_FIELDS:
            v = sub.idf.first(f).strip()
            m = re.match(r"^(20\d{2})-(\d{2})-(\d{2})$", v)
            if m:
                try:
                    d = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    if d > today:
                        out.append(self.result(message=f"{self.description} ({f}: {v})"))
                except ValueError:
                    pass
        return out


class _CvBase(MbRule):
    _level_key = None   # "error" or "warning"
    def validate(self, sub, context):
        if not sub.idf:
            return []
        cv = ((context.definitions or {}).get("controlled_terms", {}).get("idf", {}).get(self._level_key, {}))
        out = []
        for field_name, allowed in cv.items():
            for v in sub.idf.get(field_name):
                if v and v.strip() and v.strip() not in allowed:
                    out.append(self.result(message=f"{self.description} ({field_name}: '{v}')"))
        return out


class MB_IR0015(_CvBase):
    rule_id = "MB_IR0015"; level = "error"; target = "IDF"; _level_key = "error"
    description = "Value is not in controlled terms."


class MB_IR0016(_CvBase):
    rule_id = "MB_IR0016"; level = "warning"; target = "IDF"; _level_key = "warning"
    description = "Value is not in controlled terms."


class MB_IR0017(MbRule):
    rule_id = "MB_IR0017"; level = "error"; target = "IDF"
    description = "Missing protocol type(s) for the submission type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st = sub.idf.submission_type
        req = _idf(context).get("required_protocol_types", {}).get(st)
        if not req:
            return []
        have = set(sub.idf.get("Protocol Type"))
        miss = [t for t in req if t not in have]
        return [self.result(message=f"{self.description} ({st}: {', '.join(miss)})")] if miss else []


class MB_IR0018(MbRule):
    rule_id = "MB_IR0018"; level = "error"; target = "IDF"
    description = "Missing protocol parameter(s) for the submission type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st = sub.idf.submission_type
        spec = _idf(context).get("required_protocol_parameters", {}).get(st, {})
        if not spec:
            return []
        out = []
        protos = {p["Protocol Type"]: p for p in sub.idf.protocols()}
        for ptype, params in spec.items():
            p = protos.get(ptype)
            have = set((p["Protocol Parameters"].split(";") if p else []))
            miss = [x for x in params if x not in have]
            if miss:
                out.append(self.result(message=f"{self.description} ({st} {ptype}: {', '.join(miss)})"))
        return out


class MB_IR0034(MbRule):
    rule_id = "MB_IR0034"; level = "error"; target = "IDF"
    description = "Missing experiment type for the submission type."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        st = sub.idf.submission_type
        req = _idf(context).get("required_experiment_types", {}).get(st)
        if not req:
            return []
        have = set(sub.idf.get("Comment[Experiment type]"))
        miss = [t for t in req if t not in have]
        return [self.result(message=f"{self.description} ({st}: {', '.join(miss)})")] if miss else []


class MB_IR0020(MbRule):
    rule_id = "MB_IR0020"; level = "error"; target = "IDF"
    description = "At least one submitter must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        roles = [r.strip().lower() for r in sub.idf.get("Person Roles")]
        return [] if "submitter" in roles else [self.result()]


class MB_IR0037(MbRule):
    rule_id = "MB_IR0037"; level = "error"; target = "IDF"
    description = "Email address is required for the submitter."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        roles = sub.idf.get("Person Roles")
        emails = sub.idf.get("Person Email")
        for i, role in enumerate(roles):
            if role.strip().lower() == "submitter":
                if i >= len(emails) or _empty(emails[i]):
                    return [self.result()]
        return []


class MB_IR0035(MbRule):
    rule_id = "MB_IR0035"; level = "warning"; target = "IDF"
    description = "Experimental factor name and type do not match (type auto-corrected to name)."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        names = sub.idf.get("Experimental Factor Name")
        types = sub.idf.get("Experimental Factor Type")
        if names != types and set(names) - set(types):
            return [self.result(message=f"{self.description} ({', '.join(set(names) - set(types))})")]
        return []


class MB_IR0025(MbRule):
    rule_id = "MB_IR0025"; level = "warning"; target = "IDF"
    description = "Invalid publication identifier (PubMed ID must be numeric)."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        out = []
        for v in sub.idf.get("PubMed ID"):
            if v and v.strip() and v.strip() not in nulls and not re.match(r"^\d+$", v.strip()):
                out.append(self.result(message=f"{self.description} (PubMed ID: '{v}')"))
        return out


class MB_IR0038(MbRule):
    rule_id = "MB_IR0038"; level = "warning"; target = "IDF"
    description = "MetaboBank study accession (MTBKS...) should be specified for re-analysis."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        out = []
        for v in sub.idf.get("Comment[Related study]"):
            if v and v.strip() and v.strip() not in nulls and not re.match(r"^MTBKS\d+$", v.strip()):
                out.append(self.result(message=f"{self.description} (Comment[Related study]: '{v}')"))
        return out


class MB_IR0023(MbRule):
    rule_id = "MB_IR0023"; level = "warning"; target = "IDF"
    description = "Null value is provided for an optional field."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        required = set(_idf(context).get("required_error", [])) | set(_idf(context).get("required_not_null", []))
        out = []
        for f in sub.idf.field_order:
            if f in required:
                continue
            for v in sub.idf.get(f):
                if v.strip() in nulls:
                    out.append(self.result(message=f"{self.description} ({f}: '{v}')"))
                    break
        return out


class MB_IR0024(MbRule):
    rule_id = "MB_IR0024"; level = "warning"; target = "IDF"
    # IDF フィールド値の非 ASCII 文字を ASCII へ強制正規化（reader で適用済み）。
    # mapped は warning（autofix 報告）、正規化しきれず残った非 ASCII は error。
    description = "Non-ASCII characters in an IDF field were normalized to ASCII."

    def validate(self, sub, context):
        from apps.metabobank.charnorm import fix_warning_message, residual_error_message
        if not sub.idf:
            return []
        out = []
        for fx in getattr(sub, "char_fixes", []):
            if fx["target"] != "IDF":
                continue
            if fx["mapped"]:
                out.append(self.result(
                    message=fix_warning_message(fx["where"], fx["mapped"]), level="warning"))
            if fx["residual"]:
                out.append(self.result(
                    message=residual_error_message(fx["where"], fx["residual"]), level="error"))
        return out
