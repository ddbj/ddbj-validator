"""GEA ルールの基底。共通 flags/result は common/rules/simple:SimpleRule に集約。
GEA 固有: only_type（submission type 限定）と applies()。"""
from common.rules.simple import SimpleRule

# 内部無視（external）扱いのルール。現状なし。
INTERNAL_IGNORE_RULE_IDS = frozenset()


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
