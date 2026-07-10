"""GEA ルールの基底。bs/bp/dra/metabobank の *Rule と同型。"""

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


class GeaRule:
    rule_id = "GEA_RXXXX"
    level = "error"
    target = ""
    description = ""
    # 適用する submission type（None=Both/全て、"microarray"/"sequencing" で限定）
    only_type = None
    requires_rdb = False
    requires_network = False
    requires_auth = False

    def applies(self, sub, context):
        if self.only_type is None:
            return True
        return submission_type(sub, context) == self.only_type

    def result(self, message=None, level=None, target=None, **extra):
        r = {
            "rule_id": self.rule_id,
            "level": (level or self.level),
            "target": (target if target is not None else self.target),
            "message": message or self.description,
        }
        r.update(extra)
        return r
