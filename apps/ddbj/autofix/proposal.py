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
                   message="Value will be fixed.", source_db=None):
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
    return proposal
