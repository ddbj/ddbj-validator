"""軽量ルール基底（dra / metabobank / gea 共有）。

capability flags（requires_rdb/network/auth）＋ result() dict 生成を提供する。
※ ddbj/bs 系の common/rules/base.py:BaseRule（get_features / validate_file 等を持つ重い基底）とは別物。
"""


class SimpleRule:
    rule_id = "RXXXX"
    level = "error"
    target = ""
    description = ""
    requires_rdb = False       # skip_db 時にスキップ
    requires_network = False   # skip_ncbi 時にスキップ
    requires_auth = False      # skip_auth 時にスキップ

    def result(self, message=None, level=None, target=None, **extra):
        r = {
            "rule_id": self.rule_id,
            "level": (level or self.level),
            "target": (target if target is not None else self.target),
            "message": message or self.description,
        }
        r.update(extra)
        return r


class SimpleValidator:
    """ルールの登録・モード別スキップ・実行・`external` 付与をまとめた validator の骨格。

    biosample / bioproject / dra / gea / metabobank の 5 app で同じだった
    「requires_* フラグで active_rules を絞る → 順に validate → rule_id が internal ignore なら
    external=True」を 1 箇所にした。各 app のサブクラスは

    - `build_rules(context)`  … 順序つきのルールインスタンス列（順序は手で書く。CLAUDE.md の方針）
    - `ignore_ids`            … internal ignore（管理システムが無視する error）の rule_id 集合

    を与えるだけでよい。前処理（biosample の autocleanup）は `pre_run`、ルールごとの適用可否
    （gea の only_type）は `applies` を上書きする。
    ddbj は BaseRule 系（validate_file / validate_submission を持つ）なので対象外。
    """
    ignore_ids = frozenset()

    def __init__(self, context):
        self.context = context
        self.active_rules = [r for r in self.build_rules(context) if self.enabled(r, context)]

    def build_rules(self, context):
        raise NotImplementedError

    @staticmethod
    def enabled(rule, context):
        """実行モード（skip_db / skip_ncbi / skip_auth）でスキップされないルールか。"""
        if context.skip_db and getattr(rule, "requires_rdb", False):
            return False
        if context.skip_ncbi and getattr(rule, "requires_network", False):
            return False
        if context.skip_auth and getattr(rule, "requires_auth", False):
            return False
        return True

    def applies(self, rule, sub):
        """このルールを sub に適用するか（既定は常に適用。gea が submission type で絞る）。"""
        return True

    def pre_run(self, sub):
        """active_rules の前に走らせる処理の結果（既定なし。biosample の autocleanup 用）。"""
        return []

    def run(self, sub):
        results = list(self.pre_run(sub))
        for rule in self.active_rules:
            if not self.applies(rule, sub):
                continue
            results.extend(rule.validate(sub, self.context))
        for r in results:
            r["external"] = r["rule_id"] in self.ignore_ids
        return results
