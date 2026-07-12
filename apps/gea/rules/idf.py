"""IDF ルール（GEA_C / COM / ED / EF / G / PB / PR / MAN / RC / REGEX）。

definitions.json の idf.* / value_formats を data 駆動で参照。
experiment_type（Both / Micro-array / HTS）は only_type（None/microarray/sequencing）で表現。
"""
import re
from apps.gea.rules.base import GeaRule, null_values

_DATE_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _idf(context):
    return (context.definitions or {}).get("idf", {})


def _empty(v):
    return v is None or str(v).strip() == ""


# ---------------- Contact (Person) ----------------
class GEA_C0001(GeaRule):
    rule_id = "GEA_C0001"; level = "error"; target = "IDF/Person"
    description = "At least one contact must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Person Last Name")) else [self.result()]


class GEA_C0002(GeaRule):
    rule_id = "GEA_C0002"; level = "error"; target = "IDF/Person"
    description = "A contact must have last name specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        # Person* のいずれかに値がある「人物列」で Last Name が空のものを検出
        keys = ["Person First Name", "Person Mid Initials", "Person Affiliation", "Person Roles"]
        last = sub.idf.get("Person Last Name")
        n = max([len(last)] + [len(sub.idf.get(k)) for k in keys])
        bad = 0
        for i in range(n):
            has_other = any(i < len(sub.idf.get(k)) and not _empty(sub.idf.get(k)[i]) for k in keys)
            has_last = i < len(last) and not _empty(last[i])
            if has_other and not has_last:
                bad += 1
        return [self.result(message=f"{self.description} ({bad} contact(s))")] if bad else []


class GEA_C0008(GeaRule):
    rule_id = "GEA_C0008"; level = "warning"; target = "IDF/Person"
    description = "A contact should have first name specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        last = sub.idf.get("Person Last Name")
        first = sub.idf.get("Person First Name")
        bad = sum(1 for i in range(len(last)) if not _empty(last[i]) and (i >= len(first) or _empty(first[i])))
        return [self.result(message=f"{self.description} ({bad} contact(s))")] if bad else []


# ---------------- Comment / General ----------------
class GEA_COM0001(GeaRule):
    rule_id = "GEA_COM0001"; level = "error"; target = "IDF/Comment"
    description = "Non-empty value for 'Comment[AEExperimentType]' must be provided in IDF."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.ae_experiment_type) else [self.result()]


class GEA_G0001(GeaRule):
    rule_id = "GEA_G0001"; level = "error"; target = "IDF/General"
    description = "Experiment title must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.first("Investigation Title")) else [self.result()]


class GEA_G0002(GeaRule):
    rule_id = "GEA_G0002"; level = "error"; target = "IDF/General"
    description = "Experiment description must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.first("Experiment Description")) else [self.result()]


class GEA_G0009(GeaRule):
    rule_id = "GEA_G0009"; level = "warning"; target = "IDF/General"
    description = "Experiment description should be at least 100 characters long."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        desc = sub.idf.first("Experiment Description").strip()
        mn = _idf(context).get("description_min_length", 100)
        return [self.result(message=f"{self.description} (Found: {len(desc)})")] if desc and len(desc) < mn else []


class _DateFormat(GeaRule):
    _field = None
    def validate(self, sub, context):
        if not sub.idf:
            return []
        v = sub.idf.first(self._field).strip()
        return [self.result(message=f"{self.description} ('{v}')")] if v and not _DATE_OK.match(v) else []


class GEA_G0004(_DateFormat):
    rule_id = "GEA_G0004"; level = "error"; target = "IDF/General"; _field = "Date of Experiment"
    description = "Date of Experiment must be in 'YYYY-MM-DD' format."


class GEA_G0006(_DateFormat):
    rule_id = "GEA_G0006"; level = "error"; target = "IDF/General"; _field = "Public Release Date"
    description = "Experiment public release date must be in 'YYYY-MM-DD' format."


class GEA_G0007(GeaRule):
    rule_id = "GEA_G0007"; level = "error"; target = "IDF/General"
    description = "Reference to the SDRF file must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.first("SDRF File")) else [self.result()]


class GEA_G0012(GeaRule):
    rule_id = "GEA_G0012"; level = "error"; target = "IDF/General"; only_type = "microarray"
    description = "Number of channel should be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if not _empty(sub.idf.number_of_channel) else [self.result()]


class GEA_G0013(GeaRule):
    rule_id = "GEA_G0013"; level = "error"; target = "IDF/General"
    description = "An additional file name must only contain alphanumeric characters, underscores, hyphens and dots."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        out = []
        for v in sub.idf.get("Comment[AdditionalFile:TXT]"):
            if v and v.strip() and not re.fullmatch(r"[A-Za-z0-9._-]+", v.strip()):
                out.append(self.result(message=f"{self.description} ('{v}')"))
        return out


# ---------------- Experimental design / variable ----------------
class GEA_ED0001(GeaRule):
    rule_id = "GEA_ED0001"; level = "error"; target = "IDF/ExperimentalDesign"; only_type = "microarray"
    description = "Experiment must have at least one experimental design specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Experimental Design")) else [self.result()]


class GEA_EF0001(GeaRule):
    rule_id = "GEA_EF0001"; level = "error"; target = "IDF/ExperimentalVariable"
    description = "An experiment must have at least one experimental variable specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Experimental Factor Name")) else [self.result()]


class GEA_EF0003(GeaRule):
    rule_id = "GEA_EF0003"; level = "warning"; target = "IDF/ExperimentalVariable"
    description = "An experimental variable should have a type specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        names = sub.idf.get("Experimental Factor Name")
        types = sub.idf.get("Experimental Factor Type")
        bad = sum(1 for i in range(len(names)) if not _empty(names[i]) and (i >= len(types) or _empty(types[i])))
        return [self.result(message=f"{self.description} ({bad})")] if bad else []


# ---------------- Publication ----------------
class GEA_PB0002(GeaRule):
    rule_id = "GEA_PB0002"; level = "error"; target = "IDF/Publication"
    description = "PubMed ID must be numeric."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        nulls = null_values(context)
        out = []
        for v in sub.idf.get("PubMed ID"):
            if v and v.strip() and v.strip() not in nulls and not re.fullmatch(r"\d+", v.strip()):
                out.append(self.result(message=f"{self.description} ('{v}')"))
        return out


# ---------------- Protocol ----------------
class GEA_PR0001(GeaRule):
    rule_id = "GEA_PR0001"; level = "error"; target = "IDF/Protocol"
    description = "At least one protocol must be used in an experiment."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        return [] if any(not _empty(v) for v in sub.idf.get("Protocol Name")) else [self.result()]


class GEA_PR0002(GeaRule):
    rule_id = "GEA_PR0002"; level = "error"; target = "IDF/Protocol"
    description = "Name of a protocol must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if _empty(p["Protocol Name"]) and not _empty(p["Protocol Type"]))
        return [self.result(message=f"{self.description} ({bad})")] if bad else []


class GEA_PR0003(GeaRule):
    rule_id = "GEA_PR0003"; level = "error"; target = "IDF/Protocol"
    description = "A protocol type must be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if not _empty(p["Protocol Name"]) and _empty(p["Protocol Type"]))
        return [self.result(message=f"{self.description} ({bad})")] if bad else []


class GEA_PR0005(GeaRule):
    rule_id = "GEA_PR0005"; level = "error"; target = "IDF/Protocol"
    description = "Description of a protocol should be specified."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if not _empty(p["Protocol Name"]) and _empty(p["Protocol Description"]))
        return [self.result(message=f"{self.description} ({bad})")] if bad else []


class GEA_PR0006(GeaRule):
    rule_id = "GEA_PR0006"; level = "warning"; target = "IDF/Protocol"
    description = "Description of a protocol should be over 100 characters long."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        mn = _idf(context).get("protocol_description_min_length", 100)
        protos = sub.idf.protocols()
        bad = sum(1 for p in protos if p["Protocol Description"] and 0 < len(p["Protocol Description"].strip()) < mn)
        return [self.result(message=f"{self.description} ({bad})")] if bad else []


class _ProtocolRequired(GeaRule):
    """submission type ごとの必須 protocol type が Protocol Type 群に含まれるか。"""
    _ptype = None
    level = "error"; target = "IDF/Protocol"

    def validate(self, sub, context):
        if not sub.idf:
            return []
        have = {t.strip() for t in sub.idf.get("Protocol Type") if t.strip()}
        return [] if self._ptype in have else [self.result()]


class GEA_PR0013(_ProtocolRequired):
    rule_id = "GEA_PR0013"; _ptype = "sample collection protocol"
    description = "Sample collection protocol is required for submissions."


class GEA_PR0014(_ProtocolRequired):
    rule_id = "GEA_PR0014"; _ptype = "nucleic acid extraction protocol"
    description = "Nucleic acid extraction protocol is required for submissions."


class GEA_PR0015(_ProtocolRequired):
    rule_id = "GEA_PR0015"; _ptype = "normalization data transformation protocol"
    description = "Normalization data transformation protocol is required for submissions."


class GEA_PR0010(_ProtocolRequired):
    rule_id = "GEA_PR0010"; only_type = "microarray"; _ptype = "nucleic acid labeling protocol"
    description = "Nucleic acid labeling protocol is required for Micro-array submissions."


class GEA_PR0011(_ProtocolRequired):
    rule_id = "GEA_PR0011"; only_type = "microarray"; _ptype = "nucleic acid hybridization to array protocol"
    description = "Nucleic acid hybridization to array protocol is required for Micro-array submissions."


class GEA_PR0012(_ProtocolRequired):
    rule_id = "GEA_PR0012"; only_type = "microarray"; _ptype = "array scanning and feature extraction protocol"
    description = "Array scanning and feature extraction protocol is required for Micro-array submissions."


class GEA_PR0008(_ProtocolRequired):
    rule_id = "GEA_PR0008"; only_type = "sequencing"; _ptype = "nucleic acid library construction protocol"
    description = "Library construction protocol is required for HTS submissions."


class GEA_PR0009(_ProtocolRequired):
    rule_id = "GEA_PR0009"; only_type = "sequencing"; _ptype = "nucleic acid sequencing protocol"
    description = "Sequencing protocol is required for HTS submissions."


# ---------------- 一意性 / 未定義 / CV / 形式 ----------------
class GEA_RC0001(GeaRule):
    rule_id = "GEA_RC0001"; level = "error"; target = "IDF"
    description = "Predefined comment fields must be unique."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        dup = sorted(set(sub.idf.duplicate_fields))
        return [self.result(message=f"{self.description} ({', '.join(dup)})")] if dup else []


class GEA_MAN0001(GeaRule):
    rule_id = "GEA_MAN0001"; level = "error"; target = "IDF"; only_type = "microarray"
    description = "Mandatory field is required."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        req = _idf(context).get("required_microarray", [])
        miss = [f for f in req if _empty(" ".join(sub.idf.get(f)))]
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class _CvBase(GeaRule):
    _level_key = None
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


class GEA_CV_ERR(_CvBase):
    rule_id = "GEA_COM0002"; level = "error"; target = "IDF"; _level_key = "error"
    description = "Value is not in controlled terms."


class GEA_CV_WARN(_CvBase):
    rule_id = "GEA_COM0003"; level = "warning"; target = "IDF"; _level_key = "warning"
    description = "Value is not in controlled terms."


class _IdfRegex(GeaRule):
    """value_formats のうち IDF 側フィールドの形式検査。"""
    rule_id = "GEA_REGEX0001"; level = "error"; target = "IDF"
    _fields = ()
    description = "Format Error"

    def validate(self, sub, context):
        if not sub.idf:
            return []
        fmts = (context.definitions or {}).get("value_formats", {})
        nulls = null_values(context)
        out = []
        for f in self._fields:
            pat = fmts.get(f)
            if not pat:
                continue
            for v in sub.idf.get(f):
                if v and v.strip() and v.strip() not in nulls and not re.fullmatch(pat, v.strip()):
                    out.append(self.result(message=f"Format Error '{f}' ('{v}')"))
        return out


class GEA_REGEX0001(_IdfRegex):
    rule_id = "GEA_REGEX0001"; _fields = ("Comment[GEAAccession]",)
    description = "Format Error 'Comment[GEAAccession]'"


class GEA_REGEX0002(_IdfRegex):
    rule_id = "GEA_REGEX0002"; _fields = ("Protocol Name",)
    description = "Format Error 'Protocol Name'"


class GEA_REGEX0003(_IdfRegex):
    rule_id = "GEA_REGEX0003"; _fields = ("Comment[BioProject]",)
    description = "Format Error 'Comment[BioProject]'"


class GEA_REGEX0004(_IdfRegex):
    rule_id = "GEA_REGEX0004"; _fields = ("Comment[SecondaryAccession]",)
    description = "Format Error 'Comment[SecondaryAccession]'"
