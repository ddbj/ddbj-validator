"""BioProject ルールの基底。biosample の BsRule と同型。"""

# internal_ignore（error は出すが登録は止めない）の rule_id 集合。docs/bioproject/rules.txt の
# Internal ignore 列と一致させる。2026-09-28 に BP_R0005 / BP_R0006 / BP_R0021 を追加。
# BP_R0020 は deprecated で発火しないが、rule 表の記載に合わせて集合には残す。
INTERNAL_IGNORE_RULE_IDS = frozenset({
    "BP_R0005", "BP_R0006", "BP_R0018", "BP_R0020", "BP_R0021",
})


def is_internal_ignore(rule_id):
    return rule_id in INTERNAL_IGNORE_RULE_IDS


class BpRule:
    """BioProject 検証ルールの基底。validate(submission, context) -> list[result dict]。"""
    rule_id = "BP_RXXXX"
    level = "error"
    target = ""
    description = ""
    requires_rdb = False       # skip_db 時にスキップ
    requires_network = False   # skip_ncbi 時にスキップ（taxonomy ソース）
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
