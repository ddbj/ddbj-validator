"""識別子の形式・重複ルール（DB 非依存。フェーズ A 続き）。

- BS_R0005: BioProject accession の形式（PRJ[D|E|N]xxxxxx / PSUBxxxxxx）
- BS_R0099: locus_tag_prefix の形式（3-12 英数字、先頭は数字不可）
- BS_R0102: submission 内で locus_tag_prefix が重複
- BS_R0122: GISAID accession の形式
"""
import re
from collections import Counter
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty, is_missing_value, pkg_startswith, MIGS_BA_EU


def _skip_ltp(v):
    """locus_tag_prefix として無視すべき値（空 or missing 系）か。
    missing/not applicable/missing: xxx 等の null 相当値は prefix ではないため R0091/R0102/R0099 の対象外。"""
    return is_empty(v) or is_missing_value(v)

# BioProject: PRJDB12345 / PRJNA123 / PRJEB456（PRJ＋2文字アーカイブコード＋数字）または PSUB＋数字
# BioProject accession 形式: PRJ[DEN][A-Z]+数字（桁数は縛らない）／ PSUB＋6-7桁。
_BP_RE = re.compile(r"^(PRJ[A-Z]{2}\d{1,}|PSUB\d{6,7})$")
_PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,11}$")
_GISAID_RE = re.compile(r"^EPI_ISL_\d+$", re.IGNORECASE)


class BS_R0005(BsRule):
    rule_id = "BS_R0005"
    level = "error"
    target = "bioproject_id"
    description = "Invalid BioProject accession. Format: PRJ[D|E|N]xxxxxx or PSUBxxxxxx."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("bioproject_id")
            if is_empty(v):
                continue
            if not _BP_RE.match(v.strip()):
                out.append(self.result(sample=rec.sample_id,
                                       attribute="bioproject_id", old_value=v,
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
            if _skip_ltp(v):
                continue
            if not _PREFIX_RE.match(v.strip()):
                out.append(self.result(sample=rec.sample_id,
                                       attribute="locus_tag_prefix", old_value=v,
                                       message=f"Invalid locus tag prefix format. (Found: '{v}')"))
        return out


class BS_R0102(BsRule):
    rule_id = "BS_R0102"
    level = "error"
    target = "locus_tag_prefix"
    description = "Locus tag prefix is duplicated in the submission."

    def validate(self, submission, context):
        prefixes = [rec.attr("locus_tag_prefix").strip()
                    for rec in submission.records if not _skip_ltp(rec.attr("locus_tag_prefix"))]
        dup = {p for p, c in Counter(prefixes).items() if c > 1}
        out = []
        for rec in submission.records:
            v = rec.attr("locus_tag_prefix")
            if not _skip_ltp(v) and v.strip() in dup:
                out.append(self.result(sample=rec.sample_id,
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
            if is_empty(v):
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
            if is_empty(v):
                continue
            if not _GISAID_RE.match(v.strip()):
                out.append(self.result(sample=rec.sample_id,
                                       attribute="gisaid_accession", old_value=v,
                                       message=f"Invalid GISAID accession number. (Found: '{v}')"))
        return out


class BS_R0091(BsRule):
    rule_id = "BS_R0091"
    level = "error"
    target = "locus_tag_prefix"
    description = "Locus tag prefix is duplicated."
    requires_rdb = True  # biosample DB の登録済み prefix を参照

    def validate(self, submission, context):
        # DB に登録済みで、かつ現サブミッション以外が使用している locus_tag_prefix はエラー。
        # submission 内重複は R0102 が担当（役割分担。Ruby では OR で両方 R0091 だが本実装は分離）。
        registered = context.registered_locus_tag_prefixes or {}
        if not registered:
            return []
        cur_sub = submission.submission_id
        out = []
        for rec in submission.records:
            v = rec.attr("locus_tag_prefix")
            if _skip_ltp(v):
                continue
            subs = registered.get(v.strip())
            if subs and any(s != cur_sub for s in subs):
                out.append(self.result(
                    sample=rec.sample_id,
                    message=f"Locus tag prefix is duplicated. (Found: '{v}')"))
        return out


class BS_R0109(BsRule):
    rule_id = "BS_R0109"
    level = "warning"
    target = "locus_tag_prefix"
    description = "Locus tag prefix is required for annotated genome submission."

    def validate(self, submission, context):
        # 原核/真核ゲノム系パッケージ（MIGS.ba / MIGS.eu）で locus_tag_prefix 任意提示
        out = []
        for rec in submission.records:
            if not pkg_startswith(rec.package, *MIGS_BA_EU):
                continue
            if is_empty(rec.attr("locus_tag_prefix")):
                out.append(self.result(
                    sample=rec.sample_id,
                    message="Locus tag prefix is required for annotated genome submission. "
                            "If you are submitting genome with annotation, please take locus tag prefix."))
        return out
