"""DRA account/DB 依存ルール。

- DRA_R0004: submission の center_name が account の組織名と異なる → warning（要 DB）。
- DRA_R0006: hold date が 2 年以内でない → error（日付計算のみ・DB 非依存）。
- DRA_R0009: object 名（alias）が account で既に使われている → error（要 DB）。
- DRA_R0015: 参照 BioProject が account に無い → error（要 DB）。
- DRA_R0016: 参照 BioSample が account に無い → error（要 DB）。
"""
import datetime
import re
from apps.dra.rules.base import DraRule
from common.jst import today as jst_today

_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


class DRA_R0004(DraRule):
    rule_id = "DRA_R0004"
    level = "warning"
    requires_rdb = True
    requires_auth = True
    target = "SUBMISSION/@center_name"
    description = "Submission center name is different from the organization name of the account."

    def validate(self, submission, context):
        org = getattr(context, "account_org_name", None)
        if not org or submission.submission is None:
            return []
        cn = (submission.submission.center_name or "").strip()
        if cn and cn != org.strip():
            return [self.result(sample=submission.submission.label,
                                message=f"{self.description} (center_name: '{cn}', account: '{org}')")]
        return []


class DRA_R0006(DraRule):
    rule_id = "DRA_R0006"
    level = "error"
    target = "HOLD/@HoldUntilDate"
    description = "Hold date must be within two years."

    def validate(self, submission, context):
        if submission.submission is None or not submission.submission.hold_date:
            return []
        m = _DATE_RE.search(submission.submission.hold_date)
        if not m:
            return []
        try:
            hold = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return []
        ref = getattr(context, "hold_ref_date", None) or jst_today()   # 起点は JST
        limit = datetime.date(ref.year + 2, ref.month, ref.day) if not (ref.month == 2 and ref.day == 29) \
            else datetime.date(ref.year + 2, 3, 1)
        if hold > limit:
            return [self.result(sample=submission.submission.label,
                                message=f"{self.description} (HoldUntilDate: {submission.submission.hold_date})")]
        return []


class DRA_R0009(DraRule):
    rule_id = "DRA_R0009"
    level = "error"
    requires_rdb = True
    requires_auth = True
    target = "@alias"
    description = "Object name is already used in the account."

    def validate(self, submission, context):
        used = getattr(context, "account_object_names", None)
        if not used:   # None/空（未取得）はスキップ
            return []
        # 自己除外: 検証対象自身の submission に属する登録済みオブジェクト（同一 alias prefix）は
        # 「既使用」としない（登録済みデータの再検証で自己 alias に誤ヒットするのを防ぐ）。
        # submission alias 例 "dradev-0062_Submission" → prefix "dradev-0062"。同 prefix の登録名を除外。
        self_prefix = None
        sm = submission.submission
        if sm and sm.alias:
            a = sm.alias.strip()
            self_prefix = a.split("_Submission")[0] if "_Submission" in a else a
        if self_prefix:
            used = {n for n in used if not n.startswith(self_prefix)}
        out = []
        objs = ([submission.submission] if submission.submission else []) \
            + submission.experiments + submission.runs + submission.analyses
        for o in objs:
            alias = (getattr(o, "alias", None) or "").strip()
            if alias and alias in used:
                out.append(self.result(sample=o.label,
                                       message=f"{self.description} (alias: '{alias}')"))
        return out


class DRA_R0015(DraRule):
    # Analysis の STUDY_REF(BioProject) が account 所有でない。Experiment 側は DRA_R0041 が担当。
    rule_id = "DRA_R0015"
    level = "error"
    requires_rdb = True
    requires_auth = True
    target = "ANALYSIS/STUDY_REF"
    description = "Referenced BioProject is not found in the account."

    def validate(self, submission, context):
        owned = getattr(context, "account_bioprojects", None)
        if owned is None:
            return []
        out = []
        seen = set()
        for a in submission.analyses:
            bp = (a.study_ref or "").strip().upper()
            if bp and bp not in seen:
                seen.add(bp)
                if bp not in owned:
                    out.append(self.result(sample=a.label,
                                           message=f"{self.description} (Found: '{bp}')"))
        return out


class DRA_R0016(DraRule):
    # Analysis の SAMPLE(BioSample) が account 所有でない。Experiment 側は DRA_R0042 が担当。
    rule_id = "DRA_R0016"
    level = "error"
    requires_rdb = True
    requires_auth = True
    target = "ANALYSIS/SAMPLE_REF"
    description = "Referenced BioSample is not found in the account."

    def validate(self, submission, context):
        owned = getattr(context, "account_biosamples", None)
        if owned is None:
            return []
        out = []
        seen = set()
        for a in submission.analyses:
            for samd in a.sample_refs:
                key = (samd or "").strip().upper()
                if key and key not in seen:
                    seen.add(key)
                    if key not in owned:
                        out.append(self.result(sample=a.label,
                                               message=f"{self.description} (Found: '{key}')"))
        return out
