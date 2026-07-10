"""DRA 参照整合ルール（submission 内の相互参照・orphan 検査）。

- DRA_R0003: submission 内で参照する BioProject が 2 種以上（1 submission = 単一 BioProject）。
- DRA_R0017: Run の EXPERIMENT_REF が提出 Experiment に見つからない。
- DRA_R0033（新規）: どの Run からも参照されない Experiment（orphan Experiment）。

参照は accession（DRX 等）と refname/alias の両方で解決する。
"""
from apps.dra.rules.base import DraRule


class DRA_R0003(DraRule):
    rule_id = "DRA_R0003"
    level = "error"
    target = "STUDY_REF"
    description = "Multiple BioProjects are referenced. Objects must reference single BioProject in a submission."

    def validate(self, submission, context):
        bps = set()
        for e in submission.experiments:
            if e.study_ref:
                bps.add(e.study_ref.strip())
        for a in submission.analyses:
            if a.study_ref:
                bps.add(a.study_ref.strip())
        if len(bps) > 1:
            return [self.result(sample=None,
                                message=f"{self.description} (Found: {', '.join(sorted(bps))})")]
        return []


class DRA_R0017(DraRule):
    rule_id = "DRA_R0017"
    level = "error"
    target = "EXPERIMENT_REF"
    description = "Referenced Experiment is not found in the submitted objects."

    def validate(self, submission, context):
        keys = set()
        for e in submission.experiments:
            if e.accession:
                keys.add(e.accession.strip())
            if e.alias:
                keys.add(e.alias.strip())
        out = []
        for r in submission.runs:
            ref = (r.experiment_ref or "").strip()
            refname = (r.experiment_refname or "").strip()
            if not (ref in keys or refname in keys):
                shown = ref or refname or "(none)"
                out.append(self.result(sample=r.label,
                                       message=f"{self.description} (Found: '{shown}')"))
        return out


class DRA_R0033(DraRule):
    """orphan Experiment: どの Run からも参照されない Experiment。min spec の Run⇔Experiment 紐付け担保。"""
    rule_id = "DRA_R0033"
    level = "error"
    target = "EXPERIMENT"
    description = "Experiment is not referenced by any Run."

    def validate(self, submission, context):
        referenced = set()
        for r in submission.runs:
            if r.experiment_ref:
                referenced.add(r.experiment_ref.strip())
            if r.experiment_refname:
                referenced.add(r.experiment_refname.strip())
        out = []
        for e in submission.experiments:
            acc = (e.accession or "").strip()
            alias = (e.alias or "").strip()
            if not (acc in referenced or alias in referenced):
                out.append(self.result(sample=e.label, message=self.description))
        return out


class DRA_R0034(DraRule):
    """Run が Experiment を参照していない（EXPERIMENT_REF 欠落）。"""
    rule_id = "DRA_R0034"
    level = "error"
    target = "RUN"
    description = "Run does not reference an Experiment."

    def validate(self, submission, context):
        out = []
        for r in submission.runs:
            if not ((r.experiment_ref or "").strip() or (r.experiment_refname or "").strip()):
                out.append(self.result(sample=r.label, message=self.description))
        return out


class DRA_R0035(DraRule):
    """Experiment が BioProject を参照していない（STUDY_REF 欠落）。
    ※ rules.txt の message は 'Analysis...' 表記だが target=EXPERIMENT のため Experiment の意味で実装。"""
    rule_id = "DRA_R0035"
    level = "error"
    target = "EXPERIMENT"
    description = "Experiment does not reference a BioProject."

    def validate(self, submission, context):
        return [self.result(sample=e.label, message=self.description)
                for e in submission.experiments if not (e.study_ref or "").strip()]


class DRA_R0036(DraRule):
    """Experiment が BioSample を参照していない（SAMPLE_DESCRIPTOR 欠落）。"""
    rule_id = "DRA_R0036"
    level = "error"
    target = "EXPERIMENT"
    description = "Experiment does not reference a BioSample."

    def validate(self, submission, context):
        return [self.result(sample=e.label, message=self.description)
                for e in submission.experiments if not (e.sample_ref or "").strip()]


class DRA_R0037(DraRule):
    """Analysis が BioProject を参照していない（STUDY_REF 必須）。"""
    rule_id = "DRA_R0037"
    level = "error"
    target = "ANALYSIS"
    description = "Analysis does not reference a BioProject."

    def validate(self, submission, context):
        return [self.result(sample=a.label, message=self.description)
                for a in submission.analyses if not (a.study_ref or "").strip()]


class DRA_R0038(DraRule):
    """Analysis が BioSample を参照していない（SAMPLE_REF 1 以上必須）。"""
    rule_id = "DRA_R0038"
    level = "error"
    target = "ANALYSIS"
    description = "Analysis does not reference a BioSample."

    def validate(self, submission, context):
        return [self.result(sample=a.label, message=self.description)
                for a in submission.analyses if not a.sample_refs]


class DRA_R0041(DraRule):
    """Experiment の STUDY_REF(BioProject) が account 所有でも DRA permit でもない → error。"""
    rule_id = "DRA_R0041"
    level = "error"
    requires_rdb = True
    requires_auth = True
    target = "EXPERIMENT/STUDY_REF"
    description = ("BioProject accession is not registered in your account. "
                  "Please provide a valid BioProject accession.")

    def validate(self, submission, context):
        owned = getattr(context, "account_bioprojects", None)
        if owned is None:
            return []
        out, seen = [], set()
        for e in submission.experiments:
            bp = (e.study_ref or "").strip().upper()
            if bp and bp not in seen:
                seen.add(bp)
                if bp not in owned:
                    out.append(self.result(sample=e.label, message=f"{self.description} (Found: '{bp}')"))
        return out


class DRA_R0042(DraRule):
    """Experiment の SAMPLE(BioSample) が account 所有でも DRA permit でもない → error。"""
    rule_id = "DRA_R0042"
    level = "error"
    requires_rdb = True
    requires_auth = True
    target = "EXPERIMENT/SAMPLE_DESCRIPTOR"
    description = ("BioSample accession(s) is not registered in your account. "
                  "Please provide a valid BioSample accession(s).")

    def validate(self, submission, context):
        owned = getattr(context, "account_biosamples", None)
        if owned is None:
            return []
        out, seen = [], set()
        for e in submission.experiments:
            bs = (e.sample_ref or "").strip().upper()
            if bs and bs not in seen:
                seen.add(bs)
                if bs not in owned:
                    out.append(self.result(sample=e.label, message=f"{self.description} (Found: '{bs}')"))
        return out


class DRA_R0043(DraRule):
    """Analysis の RUN_REF(DRR) が account 所有でも DRA permit でもない → error。"""
    rule_id = "DRA_R0043"
    level = "error"
    requires_rdb = True
    requires_auth = True
    target = "ANALYSIS/RUN_REF"
    description = ("Run accession(s) is not registered in your account. "
                  "Please provide a valid Run accession(s).")

    def validate(self, submission, context):
        owned = getattr(context, "account_runs", None)
        if owned is None:
            return []
        out, seen = [], set()
        for a in submission.analyses:
            for drr in a.run_refs:
                key = (drr or "").strip().upper()
                if key and key not in seen:
                    seen.add(key)
                    if key not in owned:
                        out.append(self.result(sample=a.label, message=f"{self.description} (Found: '{key}')"))
        return out
