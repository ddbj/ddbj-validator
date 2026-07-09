"""BioProject locus_tag ルール（Step4。DB 非依存分）。

- BP_R0022: LocusTagPrefix@biosample_id が BioSample accession 形式（SAMD\\d+）でない → error。
- BP_R0041: locus_tag_prefix が 3-12 英数・先頭非数字でない → error（= BS_R0099 相当）。
- BP_R0042: umbrella project に locus_tag_prefix が付いている → error（prefix は primary project に記述する）。

保留（本ファイル未実装）:
- BP_R0016（umbrella 妥当性）・BP_R0021（prefix と BioSample のペア妥当性）は、
  umbrella 参照要素（Links）と account/BioSample DB 引き当てが必要。利用可能な PSUB サンプルに
  linkage 要素が無く、bioproject v は D-way 非運用で本番突合もできないため、実装を保留する。
"""
import re
from apps.bioproject.rules.base import BpRule

_SAMD_RE = re.compile(r"^SAMD\d+$")
_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,11}$")   # 3-12 英数・先頭非数字


class BP_R0022(BpRule):
    rule_id = "BP_R0022"
    level = "error"
    target = "LocusTagPrefix/biosample_id"
    description = "Invalid BioSample accession. Please provide a valid BioSample accession with format SAMD\\d+."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for lt in rec.locus_tags:
                bs = (lt.get("biosample_id") or "").strip()
                if bs and not _SAMD_RE.match(bs):
                    out.append(self.result(sample=rec.label,
                                           message=f"Invalid BioSample accession. (Found: '{bs}')"))
        return out


class BP_R0041(BpRule):
    rule_id = "BP_R0041"
    level = "error"
    target = "LocusTagPrefix"
    description = "Locus tag prefix must be 3-12 alphanumeric characters and the first character may not be a digit."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for lt in rec.locus_tags:
                pfx = (lt.get("prefix") or "").strip()
                if pfx and not _PREFIX_RE.match(pfx):
                    out.append(self.result(sample=rec.label,
                                           message=f"Invalid locus tag prefix format. (Found: '{pfx}')"))
        return out


class BP_R0042(BpRule):
    rule_id = "BP_R0042"
    level = "error"
    target = "LocusTagPrefix"
    description = "Locus tag prefix must be described in primary project."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            has_prefix = any((lt.get("prefix") or "").strip() for lt in rec.locus_tags)
            if rec.project_kind == "umbrella" and has_prefix:
                out.append(self.result(sample=rec.label, message=self.description))
        return out
