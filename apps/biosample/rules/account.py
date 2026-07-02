"""BioProject / account / locus_tag 関連ルール（フェーズ D の実装可能分）。

DB/account 依存ルールは context に事前取得した以下を参照:
  - authorized_projects / authorized_samds（account 所属。db_auth 経由）
  - bp_meta（BioProject の project_type/status。fetch_bp_psubs 経由）
  - psub_to_prjd（PSUB→PRJDB。fetch_prjdb_by_psub 経由）
共通 DB fetch は common/db_meta（ddbj 実装の re-export）を cli 側で使う。

- BS_R0006: BioProject が account に無い（warning）
- BS_R0129: derived_from(BioSample) が account に無い（warning）
- BS_R0070: BioProject が umbrella type（error）
- BS_R0095: bioproject_id が PSUB で、対応する PRJDB がある（置換提案・warning）
- BS_R0128: locus_tag_prefix があるのに bioproject_id が無い（error。DB 非依存）

新規 DB クエリが要る R0028(account 内 sample_name 重複)/R0103(取得済み prefix)/R0108 は本バッチ対象外。
"""
import re
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_empty

_SAMD_RE = re.compile(r"SAMD\d+", re.IGNORECASE)


class BS_R0006(BsRule):
    rule_id = "BS_R0006"
    level = "warning"
    target = "bioproject_id"
    description = "BioProject accession is not registered in your account."
    requires_auth = True

    def validate(self, submission, context):
        if not context.account:
            return []
        out = []
        for rec in submission.records:
            v = rec.attr("bioproject_id")
            if is_empty(v):
                continue
            if v.strip().upper() not in {p.upper() for p in context.authorized_projects}:
                out.append(self.result(sample=rec.sample_id,
                                       message=f"BioProject accession not registered in your account. (Found: '{v}')"))
        return out


class BS_R0129(BsRule):
    rule_id = "BS_R0129"
    level = "warning"
    target = "derived_from"
    description = "BioSample accession(s) is not registered in your account."
    requires_auth = True

    def validate(self, submission, context):
        if not context.account:
            return []
        out = []
        authorized = {s.upper() for s in context.authorized_samds}
        for rec in submission.records:
            v = rec.attr("derived_from")
            if is_empty(v):
                continue
            for samd in _SAMD_RE.findall(v):
                if samd.upper() not in authorized:
                    out.append(self.result(sample=rec.sample_id,
                                           message=f"derived_from BioSample not registered in your account. (Found: '{samd}')"))
        return out


class BS_R0070(BsRule):
    rule_id = "BS_R0070"
    level = "error"
    target = "bioproject_id"
    description = "BioProject is an Umbrella project, not a primary data type of BioProject."
    requires_auth = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("bioproject_id")
            if is_empty(v):
                continue
            meta = context.bp_meta.get(v.strip())
            if meta and str(meta.get("project_type", "")).lower() == "umbrella":
                out.append(self.result(sample=rec.sample_id,
                                       message=f"BioProject is an Umbrella project. (Found: '{v}')"))
        return out


class BS_R0095(BsRule):
    rule_id = "BS_R0095"
    level = "warning"
    target = "bioproject_id"
    description = "BioProject submission id (PSUBxxxxxx) is replaced to the PRJD accession number if available."
    requires_auth = True

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("bioproject_id")
            if is_empty(v):
                continue
            info = context.psub_to_prjd.get(v.strip())
            if v.strip().upper().startswith("PSUB") and info and info.get("accession"):
                out.append(self.result(sample=rec.sample_id,
                                       message=f"PSUB is replaced to {info['accession']}. (Found: '{v}')"))
        return out


class BS_R0128(BsRule):
    rule_id = "BS_R0128"
    level = "error"
    target = "bioproject_id, locus_tag_prefix"
    description = "Provide a BioProject ID for a locus tag prefix."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not is_empty(rec.attr("locus_tag_prefix")) and is_empty(rec.attr("bioproject_id")):
                out.append(self.result(sample=rec.sample_id,
                                       message="Provide a BioProject ID for a locus tag prefix."))
        return out
