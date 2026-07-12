"""DRA/DB 参照整合ルール（GEA_REF0002）。内部 DB＋アカウント権限が必要。

GEA が参照する BioProject（IDF Comment[BioProject]）/ BioSample（SDRF Comment[BioSample]）/
Run（SDRF Comment[SRA_RUN]）が、そのアカウントで登録済み（所有 or DRA permit）かを検証する。
account_bioprojects / account_biosamples / account_runs は CLI で DRA の db_meta を用いて取得
（None＝未取得＝skip）。
"""
import re
from apps.gea.rules.base import GeaRule


def _idf_bps(sub):
    return {v.strip().upper() for v in sub.idf.get("Comment[BioProject]")} if sub.idf else set()


def _sdrf_col_values(sub, col):
    out = set()
    if not sub.sdrf:
        return out
    for i in sub.sdrf.col_indices(col):
        for row in sub.sdrf.rows:
            v = (row[i] if i < len(row) else "").strip().upper()
            if v:
                out.add(v)
    return out


def _idf_array_designs(sub):
    out = set()
    if sub.idf:
        out |= {v.strip().upper() for v in sub.idf.get("Comment[Array Design REF]") if v.strip()}
    if sub.sdrf:
        out |= {v.strip().upper() for v in sub.sdrf.values("Array Design REF") if v.strip()}
    return out


class GEA_REF0002(GeaRule):
    rule_id = "GEA_REF0002"; level = "error"; target = "IDF/SDRF"
    requires_rdb = True; requires_auth = True
    description = "Referencing object is not registered in this submission account."

    def validate(self, sub, context):
        out = []
        bps_owned = getattr(context, "account_bioprojects", None)
        bs_owned = getattr(context, "account_biosamples", None)
        runs_owned = getattr(context, "account_runs", None)
        # agg_noun を付けると summary で「'first' etc, N Nouns」に件数集約される（details は全件）。
        if bps_owned is not None:
            for bp in sorted(_idf_bps(sub)):
                if bp and re.match(r"^(PRJDB|PSUB)", bp) and bp not in {x.upper() for x in bps_owned}:
                    out.append(self.result(message=f"{self.description} (BioProject: '{bp}')", agg_noun="BioProjects"))
        if bs_owned is not None:
            for s in sorted(_sdrf_col_values(sub, "Comment[BioSample]")):
                if s and re.match(r"^SAMD", s) and s not in {x.upper() for x in bs_owned}:
                    out.append(self.result(message=f"{self.description} (BioSample: '{s}')", agg_noun="BioSamples"))
        if runs_owned is not None:
            for r in sorted(_sdrf_col_values(sub, "Comment[SRA_RUN]")):
                if r and re.match(r"^DRR", r) and r not in {x.upper() for x in runs_owned}:
                    out.append(self.result(message=f"{self.description} (Run: '{r}')", agg_noun="Runs"))
        return out


class GEA_REF0003(GeaRule):
    rule_id = "GEA_REF0003"; level = "warning"; target = "SDRF"; only_type = "sequencing"
    requires_rdb = True; requires_auth = True
    description = ("All Runs used in the DRA submission are not referenced. Upon the DRA submission release, "
                   "the other non-referenced Runs will be released.")

    def validate(self, sub, context):
        dra_runs = getattr(context, "dra_submission_runs", None)
        if not dra_runs:
            return []
        ref = _sdrf_col_values(sub, "Comment[SRA_RUN]")
        unref = sorted({r for r in dra_runs} - {x.upper() for x in ref})
        return [self.result(message=f"{self.description} (Not referenced: {', '.join(unref)})")] if unref else []


class GEA_REF0004(GeaRule):
    rule_id = "GEA_REF0004"; level = "warning"; target = "SDRF"; only_type = "sequencing"
    requires_rdb = True; requires_auth = True
    description = ("All BioSamples used in the DRA submission are not referenced. Upon the DRA submission release, "
                   "the other non-referenced BioSamples will be released.")

    def validate(self, sub, context):
        dra_bs = getattr(context, "dra_submission_biosamples", None)
        if not dra_bs:
            return []
        ref = _sdrf_col_values(sub, "Comment[BioSample]")
        unref = sorted({s for s in dra_bs} - {x.upper() for x in ref})
        return [self.result(message=f"{self.description} (Not referenced: {', '.join(unref)})")] if unref else []


class GEA_REF0005(GeaRule):
    rule_id = "GEA_REF0005"; level = "error"; target = "IDF/SDRF"; only_type = "microarray"
    requires_rdb = True; requires_auth = True
    description = "ADF accession is not registered in this submission account or publicly available."

    def validate(self, sub, context):
        registered = getattr(context, "array_designs_registered", None)
        if registered is None:
            return []
        reg = {x.upper() for x in registered}
        out = []
        for ad in sorted(_idf_array_designs(sub)):
            # A-* 形式（accession）のみ検査。ファイル名指定は対象外。
            if re.match(r"^A-[A-Z]+-\d+$", ad) and ad not in reg:
                out.append(self.result(message=f"{self.description} (Array Design: '{ad}')"))
        return out


class GEA_REF0008(GeaRule):
    rule_id = "GEA_REF0008"; level = "error"; target = "SDRF"; only_type = "sequencing"
    requires_rdb = True; requires_auth = True
    description = "BioSample-Experiment-Run sets are not identical in the DRA submission and SDRF."

    def validate(self, sub, context):
        triples = getattr(context, "dra_run_triples", None)
        if not triples or not sub.sdrf:
            return []
        run_i = sub.sdrf.col_indices("Comment[SRA_RUN]")
        drx_i = sub.sdrf.col_indices("Comment[SRA_EXPERIMENT]")
        bs_i = sub.sdrf.col_indices("Comment[BioSample]")
        if not run_i:
            return []
        from common.magetab.biosample import assay_name
        out, seen = [], set()
        for ri, row in enumerate(sub.sdrf.rows):
            drr = (row[run_i[0]] if run_i[0] < len(row) else "").strip().upper()
            if not drr.startswith("DRR") or drr in seen:
                continue
            seen.add(drr)
            dra = triples.get(drr)
            if not dra:   # DRA 側に無い（未登録参照は REF0002 で検出）
                continue
            tsv_drx = (row[drx_i[0]] if drx_i and drx_i[0] < len(row) else "").strip().upper()
            tsv_bs = (row[bs_i[0]] if bs_i and bs_i[0] < len(row) else "").strip().upper()
            diffs = []
            if tsv_drx and dra.get("drx") and tsv_drx != dra["drx"]:
                diffs.append(f"Experiment SDRF '{tsv_drx}' != DRA '{dra['drx']}'")
            # BioSample は PRIMARY_ID(BioSample ID) 由来（SAMD）。DRA 側で導出不可（旧 DRS 等）なら None＝skip。
            if tsv_bs and dra.get("biosample") and tsv_bs != dra["biosample"]:
                diffs.append(f"BioSample SDRF '{tsv_bs}' != DRA '{dra['biosample']}'")
            if diffs:
                out.append(self.result(message=f"{self.description} ({drr}: {'; '.join(diffs)})",
                                       line=ri + 1, assay=assay_name(sub, ri)))
        return out
