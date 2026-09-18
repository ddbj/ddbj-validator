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
    "GEA_DF0001",  # Either one of Array Data File and Array Data Matrix File nodes are required.
    "GEA_REF0002",  # Referencing object is not registered in this submission account.
    "GEA_SR0012",  # A source should have a 'sample_title' characteristic/comment.
    "GEA_EX0001",  # An extract must have name specified.
    "GEA_SR0002",  # Undefined column exists.
    #
    "GEA_PR0010",  # Nucleic acid labeling protocol is required for Micro-array submissions.
    "GEA_PR0011",  # Nucleic acid hybridization to array protocol is required for Micro-array submissions.
    "GEA_PR0012",  # Array scanning and feature extraction protocol is required for Micro-array submissions.
    "GEA_PR0013",  # Sample collection protocol is required for submissions.
    "GEA_PR0014",  # Nucleic acid extraction protocol is required for submissions.
    "GEA_PR0015",  # Normalization data transformation protocol is required for submissions.
    #
    "GEA_EX0003",  # An Extraction protocol must be included.
    "GEA_AN0004",  # A Hybridization protocol must be included.
    "GEA_SR0008",  # A Growth, Treatment or Sample collection protocol must be included.
    "GEA_LE0005",  # A Labeling protocol must be included.
    #
    "GEA_DADMN0004",  # A Data processing protocol that describes the analysis methods used to generate the processed data matrix file must be included.
    #
    "GEA_DADN0004",  # A Data processing protocol that describes the analysis methods used to generate the processed data file(s) must be included.
    #
    "GEA_LE0002",  # A labeled extract must have name specified.
    "GEA_LE0004",  # A labeled extract must have 'Label' attribute specified.
    "GEA_AN0006",  # For an array assay the incoming nodes must be 'Labeled Extract' nodes only.
    "GEA_G0011",  # Array Design File (or Array Design REF) is required for micro-array submissions.
    #
    "GEA_COM0004",  # Value is not in controlled terms.（Comment[tissue_preservation_method]。2026-09-18）
    "GEA_G0016",  # Experiment Type is not allowed for the specified Submission Type.（2026-09-18）
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


class GeaRule(SimpleRule):
    # 適用する submission type（None=Both/全て、"microarray"/"sequencing" で限定）
    only_type = None

    def applies(self, sub, context):
        if self.only_type is None:
            return True
        return submission_type(sub, context) == self.only_type
