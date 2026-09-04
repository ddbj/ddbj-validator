def get_features(record, feature_type=None):
    """
    SeqRecordから指定された型のフィーチャーのリストを安全かつ高速に取得する共通関数。
    """
    if not record:
        return []
        
    if not feature_type:
        return record.features
        
    # Parserで構築した高速な辞書インデックスがあればそれを利用する
    if hasattr(record, 'features_by_type'):
        return record.features_by_type.get(feature_type, [])
        
    # インデックスがない場合のフォールバック（通常のリスト検索）
    return [f for f in record.features if f.type == feature_type]

def is_pseudogene(feature):
    """pseudogene（/pseudo または /pseudogene 付き）のフィーチャーか。

    pseudogene は翻訳されないため、翻訳に関わる検証・autofix（transl_table の要求や
    アミノ酸翻訳）の対象から除外する。
    """
    return "pseudo" in feature.qualifiers or "pseudogene" in feature.qualifiers
