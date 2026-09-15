"""SeqRecord（ddbj パーサ出力）のフィーチャー走査ユーティリティ。

もとは apps/ddbj/utils/features.py と apps/ddbj/db_metadata.py にあったが、
common/db_taxonomy.py（biosample / bioproject も使う）が apps.ddbj を import する逆依存になっていたため
common へ移した。ddbj 側の旧モジュールは互換の再エクスポートだけを残す。
"""
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

def get_organisms_from_records(records):
    """
    レコード内の source フィーチャーから organism と metagenome_source を抽出する。
    """
    organisms = set()
    for record in records.values():
        for feature in get_features(record, "source"):
            for org in feature.qualifiers.get("organism", []):
                organisms.add(org.strip())
            for org in feature.qualifiers.get("metagenome_source", []):
                organisms.add(org.strip())
    return list(organisms)


def get_expected_transl_table(record, tax_data):
    """
    学名とオルガネラから期待される transl_table を返す。
    見つからない場合や組み合わせが不適当な場合は 0 を返す。
    """
    
    for feature in get_features(record, "source"):
        org = feature.qualifiers.get("organism", [""])[0]
        organelle = feature.qualifiers.get("organelle", [""])[0].strip().lower()

        if org not in tax_data or tax_data[org]["status"] == "not_found":
            return 0

        if org in tax_data and tax_data[org]["status"] in ["valid", "fixable"]:
            t_data = tax_data[org]

            # オルガネラごとの条件分岐
            if organelle in ["mitochondrion", "mitochondrion:kinetoplast", "hydrogenosome"]:
                return t_data.get("mi_code", 0)
            elif organelle.startswith("plastid") or organelle == "chromatophore":
                return t_data.get("pl_code", 0)
            elif organelle == "nucleomorph" or not organelle:
                return t_data.get("gen_code", 0)
            else:
                # その他のオルガネラが来た場合は核のコードをデフォルトとするか、0とする
                return t_data.get("gen_code", 0)
                
    return 0
        
