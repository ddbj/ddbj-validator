"""MetaboBank ルールの基底。共通 flags/result は common/rules/simple:SimpleRule に集約。"""
from common.rules.simple import SimpleRule

# internal_ignore（＝管理システム側で無視する error）の rule_id 集合。
# MetaboBank ルール表の「Internal ignore」列に準拠（ai_logs/2026-09-04/mb-rules2.txt）。
# JSON 出力の `external` フィールドを駆動する。
INTERNAL_IGNORE_RULE_IDS = frozenset({
    # --- IDF ---
    "MB_IR0005",   # IDF has missing mandatory field(s).
    "MB_IR0007",   # IDF has null value(s) for mandatory field(s).
    "MB_IR0011",   # Study description is short. Please provide more than 100 characters.
    "MB_IR0013",   # Invalid date format. Use YYYY-MM-DD.
    "MB_IR0017",   # Missing protocol type(s) for the submission type.
    "MB_IR0018",   # Missing protocol parameter(s) for the submission type.
    "MB_IR0024",   # Non-ASCII characters in an IDF field were normalized to ASCII.
    "MB_IR0037",   # Email address is required for the submitter.（非公開のため reminder）
    # --- SDRF ---
    "MB_SR0009",   # Missing or null value for a required column.
    "MB_SR0017",   # Factor value is constant across all rows.
    "MB_SR0023",   # Characteristics value and BioSample attribute value do not match.
    "MB_SR0030",   # Non-ASCII or control characters in an SDRF cell.
})


def is_internal_ignore(rule_id):
    """rule_id が internal_ignore（管理システムで無視する error）か。JSON の external フィールド用。"""
    return rule_id in INTERNAL_IGNORE_RULE_IDS


def null_values(context):
    nv = (context.definitions or {}).get("null_values", {})
    return set(nv.get("accepted", []))


class MbRule(SimpleRule):
    rule_id = "MB_RXXXX"
