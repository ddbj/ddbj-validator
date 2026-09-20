"""DRA/DB 参照整合ルール（GEA_REF0002 / GEA_REF0009）。内部 DB が必要。

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
    """参照している array design。正は **SDRF の `Array Design REF` 列**（2026-09-18）。

    旧い submission は IDF の `Comment[Array Design REF]` にも持つので、後方互換で両方から集める。
    """
    out = set()
    if sub.idf:
        out |= {v.strip().upper() for v in sub.idf.get("Comment[Array Design REF]") if v.strip()}
    if sub.sdrf:
        out |= {v.strip().upper() for v in sub.sdrf.values("Array Design REF") if v.strip()}
    return out


#: 参照の種類。(ラベル, 集約名, 所有集合の属性, 実在集合の属性, 参照 accession の先頭, 実在判定する先頭, 参照値の取り方)
#: 実在判定は accession（PRJDB/SAMD/DRR）だけが対象。`PSUB` / `SSUB` は submission ID で
#: 実在判定のテーブルが別なので対象外（従来どおり GEA_REF0002 だけで見る）。
_REF_KINDS = (
    ("BioProject", "BioProjects", "account_bioprojects", "existing_bioprojects",
     r"^(PRJDB|PSUB)", r"^PRJDB", lambda sub: _idf_bps(sub)),
    ("BioSample", "BioSamples", "account_biosamples", "existing_biosamples",
     r"^SAMD", r"^SAMD", lambda sub: _sdrf_col_values(sub, "Comment[BioSample]")),
    ("Run", "Runs", "account_runs", "existing_runs",
     r"^DRR", r"^DRR", lambda sub: _sdrf_col_values(sub, "Comment[SRA_RUN]")),
)


def _missing_refs(sub, context):
    """**DB に実在しない**参照 accession を yield する（label, agg_noun, accession）。

    アカウントとは無関係に見る（存在しない番号は誰のものでもない）。
    実在集合が未取得（None）の種類はスキップ＝判定しない。
    """
    for label, agg, _owned, exist_attr, _pat, exist_pat, getter in _REF_KINDS:
        existing = getattr(context, exist_attr, None)
        if existing is None:
            continue
        existing_u = {x.upper() for x in existing}
        for acc in sorted(getter(sub)):
            if acc and re.match(exist_pat, acc) and acc.upper() not in existing_u:
                yield label, agg, acc


def _unowned_refs(sub, context):
    """**実在するが account の所有 ∪ permit に無い**参照を yield する（label, agg_noun, accession）。

    実在しないものは GEA_REF0009 の担当なので除く。実在集合が取れていないときは
    除外対象が空になり、従来どおり「所有していない参照」を全部返す（graceful degrade）。
    """
    missing = {acc.upper() for _l, _a, acc in _missing_refs(sub, context)}
    for label, agg, owned_attr, _exist, pat, _ep, getter in _REF_KINDS:
        owned = getattr(context, owned_attr, None)
        if owned is None:
            continue
        owned_u = {x.upper() for x in owned}
        for acc in sorted(getter(sub)):
            if acc and re.match(pat, acc) and acc.upper() not in owned_u and acc.upper() not in missing:
                yield label, agg, acc


class GEA_REF0002(GeaRule):
    """実在するが、このアカウントの所有でも外部参照許可でもない accession。

    **実在しない accession は `GEA_REF0009`** が見る。外部参照許可を出せば解決するので
    internal ignore（登録はブロックしない）のままにしている。
    """
    rule_id = "GEA_REF0002"; level = "error"; target = "IDF/SDRF"
    requires_rdb = True; requires_auth = True
    description = "Referencing object is not registered in this submission account."

    def validate(self, sub, context):
        # agg_noun を付けると summary で「'first' etc, N Nouns」に件数集約される（details は全件）。
        return [self.result(message=f"{self.description} ({label}: '{acc}')", agg_noun=agg)
                for label, agg, acc in _unowned_refs(sub, context)]


class GEA_REF0009(GeaRule):
    """DB に実在しない accession を参照している（打ち間違い・ダミー）。

    `GEA_REF0002`（実在するが他アカウントのもの）と分けている理由は、直し方が違うため。
    あちらは外部参照許可で解決できるので internal ignore だが、**こちらは番号自体が誤りなので
    登録をブロックする**（ignore を付けない）。
    アカウントを見ないので `requires_auth` は付けない（`--skip-auth` でも働く）。
    """
    rule_id = "GEA_REF0009"; level = "error"; target = "IDF/SDRF"
    requires_rdb = True
    description = "Referenced accession does not exist."

    def validate(self, sub, context):
        return [self.result(message=f"{self.description} ({label}: '{acc}')", agg_noun=agg)
                for label, agg, acc in _missing_refs(sub, context)]


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
