"""MetaboBank ルールの基底。共通 flags/result は common/rules/simple:SimpleRule に集約。"""
from common.rules.simple import SimpleRule

# 現行 v で error_ignore（内部無視可）のルール。MB_IR0037（submitter email; 非公開のため reminder）。
INTERNAL_IGNORE_RULE_IDS = frozenset({"MB_IR0037"})


def is_internal_ignore(rule_id):
    return rule_id in INTERNAL_IGNORE_RULE_IDS


def null_values(context):
    nv = (context.definitions or {}).get("null_values", {})
    return set(nv.get("accepted", []))


class MbRule(SimpleRule):
    rule_id = "MB_RXXXX"
