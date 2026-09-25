"""autofix の proposal / updates 辞書を構築するファクトリ（提案 E / K）。

proposal dict の組み立てが orchestrator・autofix/format・autofix/external_db に分散・重複していたため、
構築ロジックをここに集約する。全サイトがこのファクトリ経由になったため（提案 K）、
スキーマは old_value/new_value に一本化した（旧 old/new エイリアスは撤廃済み）。
source_db は指定された場合のみキーを付与する。
"""


def update_qualifier_action(entry, feature_type, qualifier, old_value, new_value, feature_id=None):
    """updates リストの 1 要素（qualifier 更新）を構築する。"""
    action = {
        "action": "update_qualifier",
        "entry": entry,
        "feature_type": feature_type,
    }
    if feature_id is not None:
        action["feature_id"] = feature_id
    action["qualifier"] = qualifier
    action["old_value"] = old_value
    action["new_value"] = new_value
    return action


def update_qualifier_in_feature_action(entry, feature_type, qualifier, old_value, new_value,
                                       feature_line, feature_id=None):
    """updates リストの 1 要素（**その feature の中だけ**を対象にした qualifier 更新）。

    `update_qualifier` は entry ＋ qualifier 名 ＋ 旧値でしか一致を見ないため、
    `codon_start 1` のように同じ entry の多くの feature が同じ値を持つ qualifier では
    関係の無い行まで書き換わる。`feature_line`（その feature の行番号）を渡し、
    writer 側で「その行から次の feature 行の手前まで」に範囲を絞る。
    """
    action = update_qualifier_action(entry, feature_type, qualifier, old_value, new_value,
                                     feature_id=feature_id)
    action["action"] = "update_qualifier_in_feature"
    action["feature_line"] = feature_line
    return action


def update_location_action(entry, feature_type, old_value, new_value, feature_id=None):
    """updates リストの 1 要素（location 更新）を構築する。"""
    action = {
        "action": "update_location",
        "entry": entry,
        "feature_type": feature_type,
    }
    if feature_id is not None:
        action["feature_id"] = feature_id
    action["old_value"] = old_value
    action["new_value"] = new_value
    return action


def build_proposal(ann_path, entry, feature_type, qualifier, target, target_level,
                   positions, old_value, new_value, rule, updates,
                   message="Value will be fixed.", source_db=None, note=None):
    """autofix proposal 辞書を構築する（スキーマは old_value/new_value に一本化）。"""
    proposal = {
        "ann_path": ann_path,
        "entry": entry,
        "feature_type": feature_type,
        "qualifier": qualifier,
        "target": target,
        "target_level": target_level,
        "positions": positions,
        "old_value": old_value,
        "new_value": new_value,
        "message": message,
        "rule": rule,
        "updates": updates,
    }
    if source_db is not None:
        proposal["source_db"] = source_db
    # note は確認画面に添える補足（例 "codon_start: 1 -> 2"）。source_db は値の出どころ
    # （BioSample の SAMD、Taxonomy の taxid 等）なので別のキーにしてある。
    if note is not None:
        proposal["note"] = note
    return proposal
