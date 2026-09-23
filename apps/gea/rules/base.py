"""GEA ルールの基底。共通 flags/result は common/rules/simple:SimpleRule に集約。
GEA 固有: only_type（submission type 限定）と applies()。"""
from common.rules.simple import SimpleRule

# 内部無視（external）扱いのルール。error のまま出すが JSON の `external` を True にし、
# 登録システム側では登録をブロックしない（mb の INTERNAL_IGNORE_RULE_IDS と同じ扱い）。
INTERNAL_IGNORE_RULE_IDS = frozenset({
    "GEA_REF0008",  # BioSample-Experiment-Run sets are not identical in the DRA submission and SDRF.（2026-09-17）
    # --- 2026-09-18 追加（error のまま internal ignore）---
    "GEA_FV0004",  # Values of an experimental variable must vary (for compound+dose at least one must vary).
    "GEA_LC0001",  # Library source, layout, selection and strategy must be specified.
    "GEA_DF0001",  # Raw Data File node is required.
    "GEA_REF0002",  # Referencing object is not registered in this submission account.
    "GEA_SR0012",  # A source should have a 'sample_title' characteristic/comment.
    "GEA_EX0001",  # An extract must have name specified.
    "GEA_SR0002",  # Undefined column exists.
    #
    "GEA_EX0003",  # An Extraction protocol must be included.
    "GEA_AN0004",  # A Hybridization protocol must be included.
    "GEA_SR0008",  # A Growth, Treatment or Sample collection protocol must be included.
    "GEA_LE0005",  # A Labeling protocol must be included.
    #
    "GEA_DADN0004",  # A Data processing protocol that describes the analysis methods used to generate the processed data file(s) must be included.
    #
    "GEA_LE0002",  # A labeled extract must have name specified.
    "GEA_LE0004",  # A labeled extract must have 'Label' attribute specified.
    "GEA_AN0006",  # For an array assay the incoming nodes must be 'Labeled Extract' nodes only.
    "GEA_G0011",  # Array Design File (or Array Design REF) is required for microarray submissions.
    #
    "GEA_COM0004",  # Value is not in controlled terms.（SDRF の Comment[tissue_preservation_method]。2026-09-18）
    "GEA_G0016",  # Experiment Type is not allowed for the specified Submission Type.（2026-09-18）
    #
    # --- 2026-09-19 追加（protocol 系。error のまま internal ignore）---
    "GEA_PR0017",  # Protocol Type is not used in the specified Submission Type.（2026-09-20 に GEA_PR0007 から改番）
    "GEA_PR0018",  # Required Protocol Type is missing for the specified Submission Type.
    "GEA_PR0019",  # Protocol Type required for raw data is missing for the specified Submission Type.
    "GEA_PR0020",  # Value is not in controlled terms.（Protocol Type）
    "GEA_REF0001",  # IDF Protocol Name and SDRF Protocol REF do not match.（only in SDRF は error）
    #
    # --- 2026-09-20 追加 ---
    "GEA_MT0002",  # A material type must be specified.（Material Type 全必須化）
    "GEA_MAN0012",  # Mandatory node (column) is required.（Sequencing の SRA_RUN / SRA_EXPERIMENT）
    "GEA_EX0004",  # A Library construction protocol must be included.
    "GEA_ADN0001",  # A raw data file must have a name.
    "GEA_SR0013",  # A source must have a 'BioSample' comment specified.
    "GEA_LC0002",  # Instrument model should be specified.
    "GEA_LC0003",  # Value is not in controlled terms.（library 4 項目 ＋ instrument model）
    "GEA_MAN0014",  # Mandatory node (column) is required.（Xenium の tissue_preservation_method）
})


def is_internal_ignore(rule_id):
    return rule_id in INTERNAL_IGNORE_RULE_IDS


def null_values(context):
    nv = (context.definitions or {}).get("null_values", {})
    return set(nv.get("accepted", []))


def submission_type_value(sub, context):
    """`Comment[Submission Type]` の値（CV 表記。例 "Microarray"）を返す。

    IDF に無ければ **DB 由来**（`context.db_submission_type`）を使う。既存 submission の IDF は
    この項目を持たないため（移行で付与する）、DB の数値から解決した値をここで拾う。
    どちらも無ければ空文字。
    """
    v = ""
    try:
        if sub is not None and getattr(sub, "idf", None):
            v = (sub.idf.first("Comment[Submission Type]") or "").strip()
    except Exception:
        v = ""
    return v or (getattr(context, "db_submission_type", None) or "")


def submission_type(sub, context):
    """microarray / sequencing / xenium / other を返す（ルールの only_type と突き合わせる内部表記）。"""
    try:
        defs = context.definitions or {}
        return defs.get("submission_type_map", {}).get(submission_type_value(sub, context)) or "other"
    except Exception:
        return "other"


def raw_less(sub, context):
    """raw データを伴わない submission か（2026-09-19）。

    `sdrf.raw_none_columns`（= `Raw Data File`）が **列ごと無い**、または **全行が空 or magic word
    `none`** なら raw 無しとみなす。新 GEA は「どの submission type でも raw なしを許す」方針なので、
    raw を前提にしたルール（`skip_conditions["raw-less"]`）はこのとき出さない。
    """
    sdrf = getattr(sub, "sdrf", None)
    if sdrf is None:
        return False                                   # SDRF が無いときは別のルールの担当
    cols = ((context.definitions or {}).get("sdrf", {}) or {}).get("raw_none_columns", [])
    seen = False
    for col in cols:
        for i in sdrf.col_indices(col):
            seen = True
            for row in sdrf.rows:
                v = (row[i] if i < len(row) else "").strip()
                if v and v.lower() != "none":
                    return False                       # 実ファイル名が 1 つでもあれば raw あり
    return True if seen or cols else False


def skipped_when_raw_less(rule_id, context):
    """`skip_conditions["raw-less"]` に載っているルールか（ルール表の Skip 列と対応）。"""
    conds = (context.definitions or {}).get("skip_conditions", {}) or {}
    return rule_id in (conds.get("raw-less") or [])


class GeaRule(SimpleRule):
    # 適用する submission type（None=Both/全て、"microarray"/"sequencing"/"xenium" で限定）
    only_type = None

    def applies(self, sub, context):
        # raw なしのときに出さないルール（Skip = raw-less）。判定は定義 1 箇所で持つ。
        if skipped_when_raw_less(self.rule_id, context) and raw_less(sub, context):
            return False
        if self.only_type is None:
            return True
        return submission_type(sub, context) == self.only_type
