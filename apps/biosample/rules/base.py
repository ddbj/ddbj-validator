"""BioSample ルールの基底（ddbj の BaseRule とは分離した biosample 専用の軽量基盤）。

各ルールは `validate(submission, context) -> list[result dict]` を実装する。
result dict: {rule_id, level, target, sample, message}（sample は accession か sample_name）。
能力フラグ（requires_rdb/network/auth）でモード別スキップ（ddbj と同じ考え方）。
"""

# internal_ignore（＝外部由来で無視可）のルール ID 集合。docs/biosample/rules.txt の
# 「Internal ignore」列に準拠（BS_R0096 は除外済み）。JSON 出力の `external` フィールドを駆動する。
# voucher（R0117/R0119 は非 ignore）等、同一クラスが複数 rule_id を emit するため rule_id 単位で持つ。
INTERNAL_IGNORE_RULE_IDS = frozenset({
    "BS_R0003", "BS_R0007", "BS_R0008", "BS_R0027", "BS_R0028",
    "BS_R0036", "BS_R0040", "BS_R0048", "BS_R0074", "BS_R0075",
    "BS_R0076", "BS_R0077", "BS_R0078", "BS_R0080", "BS_R0081",
    "BS_R0082", "BS_R0083", "BS_R0084", "BS_R0085", "BS_R0086",
    "BS_R0088", "BS_R0089", "BS_R0093", "BS_R0101", "BS_R0103",
    "BS_R0104", "BS_R0106", "BS_R0110", "BS_R0111", "BS_R0112",
    "BS_R0113", "BS_R0114", "BS_R0115", "BS_R0116", "BS_R0118",
    "BS_R0120", "BS_R0121", "BS_R0128", "BS_R0130", "BS_R0132",
    "BS_R0135", "BS_R0137", "BS_R0138", "BS_R0139", "BS_R0141",
})


def is_internal_ignore(rule_id):
    """rule_id が internal_ignore（外部由来で無視可）か。JSON の external フィールド用。"""
    return rule_id in INTERNAL_IGNORE_RULE_IDS


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

    def autofix_result(self, sample=None, message=None, **fields):
        """autofix 提案付きの結果 dict を返す（result に autofix=True を付与するショートカット）。
        fields には属性値置換なら attribute/old_value/new_value、organism 補正なら
        kind='organism'/old_value/new_value/new_taxid 等を渡す。level/target も指定可。"""
        return self.result(sample=sample, message=message, autofix=True, **fields)
