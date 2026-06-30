"""識別子の形式・重複ルール（DB 非依存。フェーズ A 続き）。

- BS_R0005: BioProject accession の形式（PRJ[D|E|N]xxxxxx / PSUBxxxxxx）
- BS_R0099: locus_tag_prefix の形式（3-12 英数字、先頭は数字不可）
- BS_R0102: submission 内で locus_tag_prefix が重複
- BS_R0122: GISAID accession の形式
"""
import re
from collections import Counter
from apps.biosample.rules.base import BsRule

# BioProject: PRJDB12345 / PRJNA123 / PRJEB456（PRJ＋2文字アーカイブコード＋数字）または PSUB＋数字
_BP_RE = re.compile(r"^(PRJ[A-Z]{2}\d+|PSUB\d+)$")
_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,11}$")
_GISAID_RE = re.compile(r"^EPI_ISL_\d+$", re.IGNORECASE)


def _empty(v):
    return v is None or str(v).strip() == ""


class BS_R0005(BsRule):
    rule_id = "BS_R0005"
    level = "error"
    target = "bioproject_id"
    description = "Invalid BioProject accession. Format: PRJ[D|E|N]xxxxxx or PSUBxxxxxx."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("bioproject_id")
            if _empty(v):
                continue
            if not _BP_RE.match(v.strip()):
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Invalid BioProject accession. (Found: '{v}')"))
        return out


class BS_R0099(BsRule):
    rule_id = "BS_R0099"
    level = "error"
    target = "locus_tag_prefix"
    description = "Locus tag prefix must be 3-12 alphanumeric characters and the first character may not be a digit."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("locus_tag_prefix")
            if _empty(v):
                continue
            if not _PREFIX_RE.match(v.strip()):
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Invalid locus tag prefix format. (Found: '{v}')"))
        return out


class BS_R0102(BsRule):
    rule_id = "BS_R0102"
    level = "error"
    target = "locus_tag_prefix"
    description = "Locus tag prefix is duplicated in the submission."

    def validate(self, submission, context):
        prefixes = [rec.attr("locus_tag_prefix").strip()
                    for rec in submission.records if not _empty(rec.attr("locus_tag_prefix"))]
        dup = {p for p, c in Counter(prefixes).items() if c > 1}
        out = []
        for rec in submission.records:
            v = rec.attr("locus_tag_prefix")
            if not _empty(v) and v.strip() in dup:
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Locus tag prefix is duplicated in the submission. (prefix: '{v}')"))
        return out


class BS_R0069(BsRule):
    rule_id = "BS_R0069"
    level = "warning"
    target = "bioproject_id"
    description = "Consecutive BioProjects are referenced in this submission. This is often a mistake caused by incrementing autofill in Excel."

    _NUM_RE = re.compile(r"^(PRJ[A-Z]{2}|PSUB)(\d+)$")

    def validate(self, submission, context):
        # prefix ごとに数値を集め、連番（n, n+1）があれば警告
        by_prefix = {}
        for rec in submission.records:
            v = rec.attr("bioproject_id")
            if _empty(v):
                continue
            m = self._NUM_RE.match(v.strip())
            if m:
                by_prefix.setdefault(m.group(1), set()).add(int(m.group(2)))
        consecutive = False
        for pfx, nums in by_prefix.items():
            s = sorted(nums)
            if any(b - a == 1 for a, b in zip(s, s[1:])):
                consecutive = True
        if consecutive:
            return [self.result(message="Consecutive BioProjects are referenced in this submission. Please check your file.")]
        return []


class BS_R0122(BsRule):
    rule_id = "BS_R0122"
    level = "warning"
    target = "gisaid_accession"
    description = "Invalid GISAID accession number."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("gisaid_accession")
            if _empty(v):
                continue
            if not _GISAID_RE.match(v.strip()):
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Invalid GISAID accession number. (Found: '{v}')"))
        return out
