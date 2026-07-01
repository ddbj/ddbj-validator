"""BioSample ルールの基底（ddbj の BaseRule とは分離した biosample 専用の軽量基盤）。

各ルールは `validate(submission, context) -> list[result dict]` を実装する。
result dict: {rule_id, level, target, sample, message}（sample は accession か sample_name）。
能力フラグ（requires_rdb/network/auth）でモード別スキップ（ddbj と同じ考え方）。
"""


class BsRule:
    rule_id = "BS_UNKNOWN"
    level = "error"            # 既定レベル（rules.txt 準拠）
    target = ""
    description = ""
    requires_rdb = False
    requires_network = False
    requires_auth = False

    def validate(self, submission, context):
        raise NotImplementedError

    def result(self, sample=None, message=None, level=None, target=None, **extra):
        """結果 dict を返す。extra には autofix 提案用の任意フィールドを渡せる
        （例: autofix=True, attribute=..., new_value=...）。将来の autofix 適用層で参照する。"""
        r = {
            "rule_id": self.rule_id,
            "level": (level or self.level),
            "target": (target if target is not None else self.target),
            "sample": sample,
            "message": message or self.description,
        }
        r.update(extra)
        return r
