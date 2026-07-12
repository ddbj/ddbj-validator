"""DRA ルールの基底。共通 flags/result は common/rules/simple:SimpleRule に集約。"""
from common.rules.simple import SimpleRule

# internal_ignore（外部由来で無視可）の rule_id 集合。rules.txt の Internal ignore に準拠（現状なし）。
INTERNAL_IGNORE_RULE_IDS = frozenset()


def is_internal_ignore(rule_id):
    return rule_id in INTERNAL_IGNORE_RULE_IDS


class DraRule(SimpleRule):
    """DRA 検証ルールの基底。validate(submission, context) -> list[result dict]。
    DRA は結果に sample（対象オブジェクトのラベル）を必ず含める。"""
    rule_id = "DRA_RXXXX"

    def result(self, sample=None, message=None, level=None, target=None, **extra):
        r = {
            "rule_id": self.rule_id,
            "level": (level or self.level),
            "target": (target if target is not None else self.target),
            "sample": sample,
            "message": message or self.description,
        }
        r.update(extra)
        return r
