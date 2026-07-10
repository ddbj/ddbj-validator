"""DRA 内容ルール（title/description/library/insert size）。

- DRA_R0010/0011/0012: Experiment/Run/Analysis の TITLE 必須。
- DRA_R0013: Experiment description（DESIGN/DESIGN_DESCRIPTION）必須。
- DRA_R0014: Analysis description（DESCRIPTION）必須。
- DRA_R0018: Experiment の LIBRARY_NAME 必須。
- DRA_R0019: PAIRED ライブラリで insert size（NOMINAL_LENGTH）必須。
- DRA_R0020: insert size は 10,000,000 未満。
"""
from apps.dra.rules.base import DraRule


def _empty(v):
    return v is None or not str(v).strip()


class DRA_R0010(DraRule):
    rule_id = "DRA_R0010"
    level = "error"
    target = "EXPERIMENT/TITLE"
    description = "Experiment Title is required."

    def validate(self, submission, context):
        return [self.result(sample=e.label, message=self.description)
                for e in submission.experiments if _empty(e.title)]


class DRA_R0011(DraRule):
    rule_id = "DRA_R0011"
    level = "error"
    target = "RUN/TITLE"
    description = "Run Title is required."

    def validate(self, submission, context):
        return [self.result(sample=r.label, message=self.description)
                for r in submission.runs if _empty(r.title)]


class DRA_R0012(DraRule):
    rule_id = "DRA_R0012"
    level = "error"
    target = "ANALYSIS/TITLE"
    description = "Analysis Title is required."

    def validate(self, submission, context):
        return [self.result(sample=a.label, message=self.description)
                for a in submission.analyses if _empty(a.title)]


class DRA_R0013(DraRule):
    rule_id = "DRA_R0013"
    level = "error"
    target = "EXPERIMENT/DESIGN/DESIGN_DESCRIPTION"
    description = "Experiment description is required."

    def validate(self, submission, context):
        return [self.result(sample=e.label, message=self.description)
                for e in submission.experiments if _empty(e.description)]


class DRA_R0014(DraRule):
    rule_id = "DRA_R0014"
    level = "error"
    target = "ANALYSIS/DESCRIPTION"
    description = "Analysis description is required."

    def validate(self, submission, context):
        return [self.result(sample=a.label, message=self.description)
                for a in submission.analyses if _empty(a.description)]


class DRA_R0018(DraRule):
    rule_id = "DRA_R0018"
    level = "error"
    target = "LIBRARY_NAME"
    description = "Library name is missing."

    def validate(self, submission, context):
        return [self.result(sample=e.label, message=self.description)
                for e in submission.experiments if _empty(e.library_name)]


class DRA_R0019(DraRule):
    rule_id = "DRA_R0019"
    level = "error"
    target = "PAIRED/@NOMINAL_LENGTH"
    description = "Insert size (nominal length) is required for paired library."

    def validate(self, submission, context):
        out = []
        for e in submission.experiments:
            if (e.library_layout or "") == "PAIRED" and _empty(e.nominal_length):
                out.append(self.result(sample=e.label, message=self.description))
        return out


class DRA_R0020(DraRule):
    rule_id = "DRA_R0020"
    level = "error"
    target = "PAIRED/@NOMINAL_LENGTH"
    description = "Insert size (nominal length) must be less than 10000000."

    def validate(self, submission, context):
        limit = ((context.definitions or {}).get("formats", {}) or {}).get("insert_size_max", 10000000)
        out = []
        for e in submission.experiments:
            v = (e.nominal_length or "").strip()
            if v.isdigit() and int(v) > limit:
                out.append(self.result(sample=e.label,
                                       message=f"{self.description} (Found: {v})"))
        return out
