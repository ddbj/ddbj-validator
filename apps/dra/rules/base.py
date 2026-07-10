"""DRA ルールの基底。biosample の BsRule / bioproject の BpRule と同型。"""

# internal_ignore（外部由来で無視可）の rule_id 集合。rules.txt の Internal ignore に準拠（現状なし）。
INTERNAL_IGNORE_RULE_IDS = frozenset()


def is_internal_ignore(rule_id):
    return rule_id in INTERNAL_IGNORE_RULE_IDS


class DraRule:
    """DRA 検証ルールの基底。validate(submission, context) -> list[result dict]。"""
    rule_id = "DRA_RXXXX"
    level = "error"
    target = ""
    description = ""
    requires_rdb = False       # skip_db 時にスキップ
    requires_network = False   # skip_ncbi 時にスキップ
    requires_auth = False      # skip_auth 時にスキップ

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
