"""BioProject locus_tag / umbrella ルール（Step4）。

DB 非依存:
- BP_R0022: LocusTagPrefix@biosample_id が BioSample accession 形式（SAMD\\d{8,}）でない → error。
- BP_R0041: locus_tag_prefix が 3-12 英数・先頭非数字でない → error（= BS_R0099 相当）。
- BP_R0042: umbrella project に locus_tag_prefix が付いている → error（prefix は primary project に記述する）。

DB 依存（default/-l ではスキップ、-d 内部 DB のみ実行）:
- BP_R0016: ProjectLinks で参照する umbrella が DB 上 umbrella project でない → error。
- BP_R0021: LocusTagPrefix の prefix と biosample_id(SAMD) のペアが BioSample DB と不一致 → error。
"""
from apps.bioproject.rules.base import BpRule
from apps.bioproject.defs import formats, compiled


def _samd_re(context):   # BioSample accession（SAMD＋8桁以上）
    f = (context.definitions or {}).get("formats", {}) if context else formats()
    return compiled(f.get("biosample_accession", r"^SAMD\d{8,}$"))


def _prefix_re(context):  # locus_tag_prefix（3-12 英数・先頭非数字）
    f = (context.definitions or {}).get("formats", {}) if context else formats()
    return compiled(f.get("locus_tag_prefix", r"^[A-Za-z][A-Za-z0-9]{2,11}$"))


class BP_R0022(BpRule):
    rule_id = "BP_R0022"
    level = "error"
    target = "LocusTagPrefix/biosample_id"
    description = "Invalid BioSample accession. Please provide a valid BioSample accession with format SAMD\\d+."

    def validate(self, submission, context):
        out = []
        samd_re = _samd_re(context)
        for rec in submission.records:
            for lt in rec.locus_tags:
                bs = (lt.get("biosample_id") or "").strip()
                if bs and not samd_re.match(bs):
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
        prefix_re = _prefix_re(context)
        for rec in submission.records:
            for lt in rec.locus_tags:
                pfx = (lt.get("prefix") or "").strip()
                if pfx and not prefix_re.match(pfx):
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


class BP_R0016(BpRule):
    """ProjectLinks で umbrella として参照する BioProject が DB 上 umbrella でない → error。"""
    rule_id = "BP_R0016"
    level = "error"
    requires_rdb = True
    target = "Link/Hierarchical/MemberID"
    description = "Invalid project is selected as an umbrella project. Please select a valid umbrella project."

    def validate(self, submission, context):
        out = []
        umbrella_ok = getattr(context, "umbrella_ok", None)
        if umbrella_ok is None:   # DB 未取得（スキップ）
            return out
        for rec in submission.records:
            for acc in rec.umbrella_member_ids:
                if acc and acc not in umbrella_ok:
                    out.append(self.result(sample=rec.label,
                                           message=f"{self.description} (Found: '{acc}')"))
        return out


class BP_R0021(BpRule):
    """locus_tag_prefix と biosample_id(SAMD) のペアが BioSample DB と不一致 → error。

    biosample_id の SAMD が BioSample DB で当該 prefix を locus_tag_prefix 属性として持っていなければ不正。
    形式不正（SAMD\\d{8,} でない）は BP_R0022 が担当するためここでは対象外。
    """
    rule_id = "BP_R0021"
    level = "error"
    requires_rdb = True
    target = "LocusTagPrefix"
    description = "Locus tag prefix and DDBJ BioSample accession pair is invalid."

    def validate(self, submission, context):
        out = []
        bs_prefix = getattr(context, "bs_locus_prefix", None)
        if bs_prefix is None:   # DB 未取得（スキップ）
            return out
        samd_re = _samd_re(context)
        for rec in submission.records:
            for lt in rec.locus_tags:
                samd = (lt.get("biosample_id") or "").strip()
                pfx = (lt.get("prefix") or "").strip()
                if not pfx or not samd_re.match(samd):
                    continue   # prefix 無し / SAMD 形式不正は対象外
                if pfx not in bs_prefix.get(samd, set()):
                    out.append(self.result(sample=rec.label,
                                           message=f"{self.description} (prefix '{pfx}', biosample '{samd}')"))
        return out
