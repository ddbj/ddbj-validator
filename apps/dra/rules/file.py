"""DRA ファイルルール（filename/checksum/filetype/系列）。

- DRA_R0021/0022: Run/Analysis の filename 必須。
- DRA_R0023/0024: Run/Analysis の filename 文字種（英数・ハイフン・アンダースコア・ドットのみ）。
- DRA_R0025/0026: Run/Analysis の md5 checksum（32 英数字）。
- DRA_R0027: paired experiment を参照する Run に fastq が 1 本だけ → warning。
- DRA_R0028: PacBio RS II hdf 系列（bas 1＋bax 3）が Run 単位で揃っていない。
- DRA_R0029: bam alignment 系列（bam/tab/reference_fasta のうち 2 種以上混在）。
- DRA_R0030: filetype が受理値でない（cv_terms run_filetype/analysis_filetype）。
- DRA_R0031: Run 内で filetype が混在（系列許容の companion type を除いて 2 種以上）。
- DRA_R0040: submission 内で同一 filename が複数回登録（min spec: deposited more than once）。
- DRA_R0049: submission 内で別名だが md5 が同一（＝同一内容ファイルの二重登録）。
"""
from apps.dra.rules.base import DraRule
from apps.dra.defs import compiled

_FASTQ = {"fastq", "generic_fastq"}
# 系列の companion（混在チェックから除外する型）
_SERIES_COMPANION = {"bam", "tab", "reference_fasta", "SOLiD_native_csfasta", "SOLiD_native_qual"}
_BAM_SERIES = {"bam", "tab", "reference_fasta"}


def _fname_re(context):
    f = (context.definitions or {}).get("formats", {}) if context else {}
    return compiled(f.get("filename", r"^[A-Za-z0-9._-]+$"))


def _md5_re(context):
    f = (context.definitions or {}).get("formats", {}) if context else {}
    return compiled(f.get("md5_checksum", r"^[A-Za-z0-9]{32}$"))


# ---- filename 必須 ----
class DRA_R0021(DraRule):
    rule_id = "DRA_R0021"
    level = "error"
    target = "RUN/FILE/@filename"
    description = "Run filename is required."

    def validate(self, submission, context):
        return [self.result(sample=r.label, message=self.description)
                for r in submission.runs
                if not any((f.filename or "").strip() for f in r.files)]


class DRA_R0022(DraRule):
    rule_id = "DRA_R0022"
    level = "error"
    target = "ANALYSIS/FILE/@filename"
    description = "Analysis filename is required."

    def validate(self, submission, context):
        return [self.result(sample=a.label, message=self.description)
                for a in submission.analyses
                if not any((f.filename or "").strip() for f in a.files)]


# ---- filename 文字種 ----
class DRA_R0023(DraRule):
    rule_id = "DRA_R0023"
    level = "error"
    target = "RUN/FILE/@filename"
    description = ("Invalid Run filename. Filenames must be constructed only from alphanumerals, "
                  "hyphens, underscores and dots.")

    def validate(self, submission, context):
        rx = _fname_re(context)
        out = []
        for r in submission.runs:
            for f in r.files:
                fn = (f.filename or "").strip()
                if fn and not rx.match(fn):
                    out.append(self.result(sample=r.label, message=f"{self.description} (Found: '{fn}')"))
        return out


class DRA_R0024(DraRule):
    rule_id = "DRA_R0024"
    level = "error"
    target = "ANALYSIS/FILE/@filename"
    description = ("Invalid Analysis filename. Filenames must be constructed only from alphanumerals, "
                  "hyphens, underscores and dots.")

    def validate(self, submission, context):
        rx = _fname_re(context)
        out = []
        for a in submission.analyses:
            for f in a.files:
                fn = (f.filename or "").strip()
                if fn and not rx.match(fn):
                    out.append(self.result(sample=a.label, message=f"{self.description} (Found: '{fn}')"))
        return out


# ---- md5 checksum ----
class DRA_R0025(DraRule):
    rule_id = "DRA_R0025"
    level = "error"
    target = "RUN/FILE/@checksum"
    description = "Run file md5 checksum is invalid. Checksum must be 32 alphanumeric characters."

    def validate(self, submission, context):
        rx = _md5_re(context)
        out = []
        for r in submission.runs:
            for f in r.files:
                cs = (f.checksum or "").strip()
                if cs and not rx.match(cs):
                    out.append(self.result(sample=r.label, message=f"{self.description} (Found: '{cs}')"))
        return out


class DRA_R0026(DraRule):
    rule_id = "DRA_R0026"
    level = "error"
    target = "ANALYSIS/FILE/@checksum"
    description = "Analysis file md5 checksum is invalid. Checksum must be 32 alphanumeric characters."

    def validate(self, submission, context):
        rx = _md5_re(context)
        out = []
        for a in submission.analyses:
            for f in a.files:
                cs = (f.checksum or "").strip()
                if cs and not rx.match(cs):
                    out.append(self.result(sample=a.label, message=f"{self.description} (Found: '{cs}')"))
        return out


# ---- 系列・filetype ----
class DRA_R0027(DraRule):
    """paired experiment を参照する Run に fastq が 1 本だけ → warning。"""
    rule_id = "DRA_R0027"
    level = "warning"
    target = "RUN/FILE"
    description = ("In most cases, more than two fastq files per Run need to be registered "
                  "for paired sequencing Experiment.")

    def validate(self, submission, context):
        # Experiment の layout を accession/alias で索引
        layout = {}
        for e in submission.experiments:
            for k in (e.accession, e.alias):
                if k:
                    layout[k.strip()] = (e.library_layout or "")
        out = []
        for r in submission.runs:
            lay = layout.get((r.experiment_ref or "").strip()) or layout.get((r.experiment_refname or "").strip())
            if lay != "PAIRED":
                continue
            n_fastq = sum(1 for f in r.files if (f.filetype or "") in _FASTQ)
            if n_fastq == 1:
                out.append(self.result(sample=r.label, message=self.description))
        return out


class DRA_R0028(DraRule):
    """PacBio RS II hdf 系列: bas 1＋bax 3 が揃っていない。"""
    rule_id = "DRA_R0028"
    level = "error"
    target = "RUN/FILE"
    description = "A series of PacBio RS II hdf files, one bas and three bax files, must be registered per Run."

    def validate(self, submission, context):
        out = []
        for r in submission.runs:
            hdf = [(f.filename or "") for f in r.files if (f.filetype or "") == "PacBio_HDF5"]
            if not hdf:
                continue
            bas = sum(1 for n in hdf if n.endswith(".bas.h5"))
            bax = sum(1 for n in hdf if n.endswith(".bax.h5"))
            if not (bas == 1 and bax == 3):
                out.append(self.result(sample=r.label,
                                       message=f"{self.description} (Found: {bas} bas, {bax} bax)"))
        return out


class DRA_R0029(DraRule):
    """bam alignment 系列の不正。

    (1) bam 系列（bam/tab/reference_fasta）内で同一 companion が重複（例: bam 2 つ）。
    (2) bam があるのに bam 系列以外の filetype（fastq 等）と混在（genelab-0011）。
    """
    rule_id = "DRA_R0029"
    level = "error"
    target = "RUN/FILE"
    description = ("A series of bam alignment files, one bam | one reference mapping table | "
                  "one reference fasta, must be registered per Run. Other filetypes such as "
                  "fastq must not be mixed with bam.")

    def validate(self, submission, context):
        out = []
        for r in submission.runs:
            all_types = [(f.filetype or "") for f in r.files if (f.filetype or "")]
            series = [t for t in all_types if t in _BAM_SERIES]
            # (1) bam 系列内で同一 companion type が重複（例: bam 2 つ）
            dup = len(series) >= 2 and len(set(series)) < len(series)
            # (2) bam があるのに bam 系列（bam/tab/reference_fasta）以外の filetype と混在（fastq 等）
            mixed = ("bam" in all_types) and any(t not in _BAM_SERIES for t in all_types)
            if dup or mixed:
                out.append(self.result(sample=r.label,
                                       message=f"{self.description} (Found: {all_types})"))
        return out


class DRA_R0030(DraRule):
    """filetype が受理値でない（cv_terms run_filetype/analysis_filetype）。"""
    rule_id = "DRA_R0030"
    level = "error"
    target = "FILE/@filetype"
    description = "Filetype is not accepted or combination of sequencing platform and filetype is invalid."

    def validate(self, submission, context):
        cv = context.cv_terms or {}
        run_ok = set(cv.get("run_filetype", []))
        ana_ok = set(cv.get("analysis_filetype", []))
        out = []
        if run_ok:
            for r in submission.runs:
                for f in r.files:
                    ft = (f.filetype or "").strip()
                    if ft and ft not in run_ok:
                        out.append(self.result(sample=r.label,
                                               message=f"Filetype is not accepted. (Found: '{ft}')"))
        if ana_ok:
            for a in submission.analyses:
                for f in a.files:
                    ft = (f.filetype or "").strip()
                    if ft and ft not in ana_ok:
                        out.append(self.result(sample=a.label,
                                               message=f"Filetype is not accepted. (Found: '{ft}')"))
        return out


class DRA_R0040(DraRule):
    """submission 内で同一 filename が複数回登録（min spec: deposited more than once）。"""
    rule_id = "DRA_R0040"
    level = "error"
    target = "FILE"
    description = "File must not be deposited more than once in a submission."

    def validate(self, submission, context):
        by_name = {}
        for obj in submission.runs + submission.analyses:
            for f in getattr(obj, "files", []):
                fn = (f.filename or "").strip()
                if fn:
                    by_name.setdefault(fn, []).append(obj.label)
        out = []
        for fn, labels in by_name.items():
            if len(labels) > 1:
                out.append(self.result(sample=None,
                                       message=f"Duplicate filename in submission: '{fn}' ({', '.join(labels)})"))
        return out


class DRA_R0049(DraRule):
    """submission 内で別名（filename が異なる）だが md5 が同一 = 同一内容ファイルの二重登録。

    filename 重複（DRA_R0040）とは別事象。名前が違うため R0040 では捕捉できない、
    「内容が同一のファイルを別名で二重に登録している」ケースを検知する。
    """
    rule_id = "DRA_R0049"
    level = "error"
    # target は Run/Analysis の FILE 横断チェック。特定 object に帰属しないためレポート上は OTHER。
    target = "FILE"
    description = "Duplicate file content (same md5) in submission"

    def validate(self, submission, context):
        by_md5 = {}
        for obj in submission.runs + submission.analyses:
            for f in getattr(obj, "files", []):
                cs = (f.checksum or "").strip().lower()
                fn = (f.filename or "").strip()
                if cs:
                    by_md5.setdefault(cs, []).append((obj.label, fn))
        out = []
        for cs, items in by_md5.items():
            # md5 が同一かつ filename が 2 種以上（＝別名で同一内容）。同名重複は DRA_R0040 の管轄。
            if len({fn for _, fn in items}) > 1 and len(items) > 1:
                names = ", ".join(sorted({fn for _, fn in items}))
                out.append(self.result(sample=None, message=f"{self.description}: {names}"))
        return out


class DRA_R0031(DraRule):
    """Run 内で filetype が混在（系列許容 companion を除いて 2 種以上）。"""
    rule_id = "DRA_R0031"
    level = "error"
    target = "RUN/FILE/@filetype"
    description = "Different filetypes are mixed in a Run."

    def validate(self, submission, context):
        out = []
        for r in submission.runs:
            types = [(f.filetype or "") for f in r.files if (f.filetype or "")]
            core = [t for t in types if t not in _SERIES_COMPANION]
            if len(set(core)) >= 2:
                out.append(self.result(sample=r.label,
                                       message=f"{self.description} (Found: {sorted(set(types))})"))
        return out
