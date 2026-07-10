"""MetaboBank ルールの基底。bs/bp/dra の *Rule と同型。"""

# 現行 v で error_ignore（内部無視可）のルール。MB_IR0037（submitter email; 非公開のため reminder）。
INTERNAL_IGNORE_RULE_IDS = frozenset({"MB_IR0037"})


def is_internal_ignore(rule_id):
    return rule_id in INTERNAL_IGNORE_RULE_IDS


def null_values(context):
    nv = (context.definitions or {}).get("null_values", {})
    return set(nv.get("accepted", []))


class MbRule:
    rule_id = "MB_RXXXX"
    level = "error"
    target = ""
    description = ""
    requires_rdb = False
    requires_network = False
    requires_auth = False

    def result(self, message=None, level=None, target=None, **extra):
        r = {
            "rule_id": self.rule_id,
            "level": (level or self.level),
            "target": (target if target is not None else self.target),
            "message": message or self.description,
        }
        r.update(extra)
        return r
