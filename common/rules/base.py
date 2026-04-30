class BaseRule:
    # クラス変数（デフォルト値）
    rule_id = "UNKNOWN"
    alternate_id = "-"
    target = ""
    description = ""
    requires_rdb = False
    requires_network = False
    requires_auth = False
    is_file_level = False
    is_submission_level = False   
    internal_ignore = True
    
    def validate(self, record, context):
        """
        各ルールで必ず上書き（オーバーライド）するメソッド。
        エラーがなければ空のリストを返す。
        """
        raise NotImplementedError("This method must be overridden in subclasses")

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        """
        ファイル単位で一括評価するルールでオーバーライドする
        """
        raise NotImplementedError("This method must be overridden in subclasses for file level rules")

    def validate_submission(self, parsed_files, context):
        """
        全提出ファイル群を横断して評価する
        """
        raise NotImplementedError("This method must be overridden in subclasses for submission level rules")

    # ==============================================================
    # インデックスを利用したフィーチャー取得メソッド
    # ==============================================================
    def get_features(self, record, feature_type=None):
        """
        指定されたタイプのフィーチャーを取得する。
        """
        if feature_type is None:
            return record.features
            
        if hasattr(record, 'features_by_type'):
            return record.features_by_type.get(feature_type, [])
        else:
            # フォールバック (万が一インデックスが無い場合)
            return [f for f in record.features if f.type == feature_type]

    def get_features_by_locus_tag(self, record, locus_tag):
        """
        指定された locus_tag を持つフィーチャーを取得する。
        """
        if hasattr(record, 'features_by_locus_tag'):
            return record.features_by_locus_tag.get(locus_tag, [])
        else:
            return [f for f in record.features if locus_tag in f.qualifiers.get("locus_tag", [])]

    # ==============================================================
    # 既存の format_result をラップし、フィーチャーから自動でメタデータを取るメソッド
    # ==============================================================
    def feature_result(self, record, feature, message, level="error", qualifier="", **kwargs):
        """
        フィーチャーオブジェクトを渡すだけで、line_numberやlocationを自動補完して結果を生成する
        """
        return self.format_result(
            entry_id=record.id,
            message=message,
            level=level,
            feature_type=feature.type,
            qualifier=qualifier,
            location=getattr(feature, 'original_location', ""),
            line_number=getattr(feature, 'line_number', None),
            **kwargs  # 受け取った任意の追加引数(autofix等)を下へ流す
        )

    def format_result(self, entry_id, message, level="warning", feature_type="", location="", qualifier="", line_number=None, **kwargs):
        """
        エラー結果のフォーマットを統一するためのヘルパーメソッド
        """
        res = {
            "level": level,
            "rule": self.rule_id,
            "target": self.target,
            "entry": entry_id,
            "feature_type": feature_type,
            "location": location,
            "qualifier": qualifier,
            "line_number": line_number,
            "message": message,
            "internal_ignore": self.internal_ignore
        }
        res.update(kwargs)  # 受け取った任意の追加引数(autofix等)を辞書にマージ
        return res