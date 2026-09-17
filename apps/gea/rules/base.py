"""GEA ルールの基底。共通 flags/result は common/rules/simple:SimpleRule に集約。
GEA 固有: only_type（submission type 限定）と applies()。"""
from common.rules.simple import SimpleRule

# 内部無視（external）扱いのルール。error のまま出すが JSON の `external` を True にし、
# 登録システム側では登録をブロックしない（mb の INTERNAL_IGNORE_RULE_IDS と同じ扱い）。
INTERNAL_IGNORE_RULE_IDS = frozenset({
    "GEA_REF0008",  # BioSample-Experiment-Run sets are not identical in the DRA submission and SDRF.（2026-09-17）
})


def is_internal_ignore(rule_id):
    return rule_id in INTERNAL_IGNORE_RULE_IDS


def null_values(context):
    nv = (context.definitions or {}).get("null_values", {})
    return set(nv.get("accepted", []))


def submission_type(sub, context):
    """microarray / sequencing / other を返す。"""
    try:
        return sub.submission_type(context.definitions)
    except Exception:
        return "other"


class GeaRule(SimpleRule):
    # 適用する submission type（None=Both/全て、"microarray"/"sequencing" で限定）
    only_type = None

    def applies(self, sub, context):
        if self.only_type is None:
            return True
        return submission_type(sub, context) == self.only_type
