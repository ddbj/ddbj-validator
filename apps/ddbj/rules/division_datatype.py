import re
from collections import defaultdict
from common.rules.base import BaseRule

def get_active_divisions(records, ddbj_dict, tax_data):
    """
    ファイル内の Datatype Division と Taxonomic Division を分離して取得する
    基本的には context.active_datatypes や context.active_divisions を直接利用推奨。
    """
    divisions = {
        "datatype": set(),
        "taxonomic": set()
    }
    common_rec = records.get("COMMON")
    div_rules = ddbj_dict.get("divisions", {})
    
    # 1. ANNに記載されている DIVISION を取得
    if common_rec:
        for feat in common_rec.features:
            if feat.type == "DIVISION":
                for div in feat.qualifiers.get("division", []):
                    div_upper = div.strip().upper()
                    
                    # JSONの div_type に基づいて振り分け
                    div_type = div_rules.get(div_upper, {}).get("div_type")
                    if div_type == "datatype":
                        divisions["datatype"].add(div_upper)
                    elif div_type == "tax":
                        divisions["taxonomic"].add(div_upper)
                    else:
                        # 定義がない場合は安全のため両方に登録
                        divisions["datatype"].add(div_upper)
                        divisions["taxonomic"].add(div_upper)
                        
    # 2. DATATYPE のルールから required_division を取得 (Datatype Division)
    if not divisions["datatype"]:
        type_rules = ddbj_dict.get("datatypes", {})
        if common_rec:
            for feat in common_rec.features:
                if feat.type == "DATATYPE":
                    for dt in feat.qualifiers.get("type", []):
                        dt_upper = dt.strip().upper()
                        req_div = type_rules.get(dt_upper, {}).get("required_division")
                        if req_div:
                            divisions["datatype"].add(req_div.strip().upper())
                            
    # 3. Taxonomy DB (organism) から Division を取得 (Taxonomic Division)
    for record in records.values():
        for feat in record.features:
            if feat.type == "source":
                # environmental_sample がある場合は強制的に ENV (datatype) を付与
                if "environmental_sample" in feat.qualifiers:
                    divisions["datatype"].add("ENV")
                    
                for org in feat.qualifiers.get("organism", []):
                    org_clean = org.strip()
                    t_data = tax_data.get(org_clean, {})
                    tax_div = t_data.get("division")
                    if tax_div:
                        divisions["taxonomic"].add(tax_div.strip().upper())
                        
    return divisions

class DIV_TYPE_STATIC_VALIDATOR(BaseRule):
    rule_id = "DIV_TYPE_STATIC_MASTER"
    target = "file"
    description = "Static validation for DATATYPE rules based on JSON profiles"
    requires_rdb = False
    is_file_level = True

    def __init__(self, ddbj_dict=None):
        pass

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        if not records:
            return results

        type_rules = context.ddbj_dict.get("datatypes", {})

        # ---------------------------------------------------
        # 1. COMMONからタグを抽出 (DATATYPE のみを起点とする)
        # ---------------------------------------------------
        active_tags = context.active_datatypes
        common_rec = records.get("COMMON")

        # DATATYPE の指定がなければ静的検証はスキップ (後続のANN0640で検知させる)
        if not active_tags:
            return results 

        # ---------------------------------------------------
        # 2. タグに基づいてルールを合成（継承の解決）
        # ---------------------------------------------------
        compiled_rule = {
            "required_division": None,
            "required_tagset_id": None,
            "required_keywords": [], 
            "allow_empty_keywords": False,
            "required_qualifiers": set(),
            "recommended_qualifiers": set(),
            "required_st_comments": set(),
            "required_dblinks": set(),
            "unsupported_qualifiers": set()
        }

        expanded_tags = set(active_tags)
        for tag in active_tags:
            rule_def = type_rules.get(tag, {})
            for parent in rule_def.get("inherits", []):
                expanded_tags.add(parent)

        for tag in sorted(expanded_tags):
            rule_def = type_rules.get(tag, {})
            
            if rule_def.get("required_division"):
                compiled_rule["required_division"] = rule_def["required_division"]

            if rule_def.get("required_tagset_id"):
                compiled_rule["required_tagset_id"] = rule_def["required_tagset_id"]
                
            if rule_def.get("allow_empty_keywords"):
                compiled_rule["allow_empty_keywords"] = True
                                
            if rule_def.get("required_keywords"):
                for kw_group in rule_def["required_keywords"]:
                    if kw_group not in compiled_rule["required_keywords"]:
                        compiled_rule["required_keywords"].append(kw_group)
                
            compiled_rule["required_qualifiers"].update(rule_def.get("required_qualifiers", []))
            compiled_rule["recommended_qualifiers"].update(rule_def.get("recommended_qualifiers", []))
            compiled_rule["required_st_comments"].update(rule_def.get("required_st_comments", []))
            compiled_rule["required_dblinks"].update(rule_def.get("required_dblinks", []))
            compiled_rule["unsupported_qualifiers"].update(rule_def.get("unsupported_qualifiers", []))
            
        # ---------------------------------------------------
        # 3. 合成されたルールの検証 (レベルはすべて FATAL)
        # ---------------------------------------------------
        # --- (A) 必須DIVISIONのチェック ---
        req_div = compiled_rule["required_division"]
        
        # 一意に決まるDatatype Divisionのリスト
        UNIQUE_DIVISIONS = {"TSA", "ENV", "EST", "GSS", "HTG", "HTC", "TLS", "MAG", "MGA", "CON", "STS", "SYN"}

        if req_div and common_rec:
            existing_divs = context.active_divisions
            
            if req_div not in existing_divs:
                tags_str = ", ".join(sorted(active_tags))
                
                if req_div in UNIQUE_DIVISIONS:
                    # COMMONの中に既存の DIVISION フィーチャーがあるかチェック
                    existing_div_feats = self.get_features(common_rec, "DIVISION")
                    
                    if existing_div_feats:
                        # ==========================================
                        # 既存がある場合：値を「上書き」する Autofix
                        # ==========================================
                        target_feat = existing_div_feats[0]
                        old_divs = target_feat.qualifiers.get("division", [])
                        old_val = old_divs[0] if old_divs else ""
                        
                        msg = f"DIVISION '{req_div}' is required for DATATYPE '{tags_str}'. Existing value '{old_val}' will be overwritten."
                        
                        updates = [{
                            "action": "update_qualifier", 
                            "entry": "COMMON", 
                            "feature_type": "DIVISION",
                            "feature_id": getattr(target_feat, 'line_number', id(target_feat)),
                            "qualifier": "division", 
                            "old_value": old_val, 
                            "new_value": req_div
                        }]
                        
                        res = self.feature_result(
                            common_rec, target_feat, msg, level="warning", qualifier="division",
                            autofix=True, fix_target="qualifier", old_value=old_val, new_value=req_div, updates=updates
                        )
                        res["rule"] = "ANN0641"
                        results.append(res)
                        
                    else:
                        # ==========================================
                        # 既存がない場合：新規フィーチャーを「追加」する Autofix
                        # ==========================================
                        msg = f"DIVISION '{req_div}' is required for DATATYPE '{tags_str}'."
                        
                        updates = [{
                            "entry": "COMMON", 
                            "action": "add_feature", 
                            "feature_type": "DIVISION", 
                            "qualifier": "division",
                            "new_value": req_div
                        }]
                        
                        res = self.format_result(
                            entry_id="COMMON", message=msg, level="warning", feature_type="DIVISION",
                            autofix=True, fix_target="feature", old_value="", new_value=f"DIVISION\t\tdivision\t{req_div}", updates=updates
                        )
                        res["rule"] = "ANN0641"
                        results.append(res)
                        
                else:
                    # 一意に決まらない場合は従来の Fatal エラー
                    msg = f"DIVISION '{req_div}' is required for DATATYPE '{tags_str}'."
                    res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="DIVISION")
                    res["rule"] = "ANN0641"
                    results.append(res)
                                    
        # --- (B) 必須キーワードのチェック ---
        req_kws = compiled_rule["required_keywords"]
        allow_empty = compiled_rule["allow_empty_keywords"]
        if req_kws and common_rec:
            existing_keywords = set()
            for feat in self.get_features(common_rec, "KEYWORD"):
                existing_keywords.update(feat.qualifiers.get("keyword", []))
            
            if allow_empty and not existing_keywords:
                pass 
            else:
                missing_kw_groups = []
                for or_group in req_kws:
                    if not any(kw in existing_keywords for kw in or_group):
                        or_group_str = " or ".join([f"'{kw}'" for kw in or_group])
                        missing_kw_groups.append(or_group_str)
                        
                if missing_kw_groups:
                    tags_str = ", ".join(active_tags)
                    combined_missing = " AND ".join([f"({g})" if " or " in g else g for g in missing_kw_groups])
                    msg = f"Missing required keyword(s): {combined_missing} (required for DATATYPE {tags_str})"
                    
                    if allow_empty:
                        msg += " OR no keyword at all"
                        
                    res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="KEYWORD")
                    res["rule"], res["target"] = "ANN0630", "KEYWORD"
                    results.append(res)

        # ---------------------------------------------------
        # 必須 tagset_id のチェック (ANN0905)
        # ---------------------------------------------------
        req_tagset = compiled_rule["required_tagset_id"]
        if req_tagset and common_rec:
            found_tagset = None
            for feat in self.get_features(common_rec, "ST_COMMENT"):
                if "tagset_id" in feat.qualifiers:
                    found_tagset = feat.qualifiers["tagset_id"][0].strip()
                    break
                    
            if not found_tagset:
                tags_str = ", ".join(active_tags)
                msg = f"tagset_id qualifier is required for DATATYPE '{tags_str}' (Expected: '{req_tagset}')."
                res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="ST_COMMENT", qualifier="tagset_id")
                res["rule"], res["target"] = "ANN0905", "ST_COMMENT"
                results.append(res)
            elif found_tagset != req_tagset:
                tags_str = ", ".join(active_tags)
                msg = f"Invalid tagset_id '{found_tagset}' for DATATYPE '{tags_str}'. Expected: '{req_tagset}'."
                res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="ST_COMMENT", qualifier="tagset_id")
                res["rule"], res["target"] = "ANN0905", "ST_COMMENT"
                results.append(res)
                    
        # --- (C) 必須ST_COMMENTのチェック ---
        req_stcs = compiled_rule["required_st_comments"]
        if req_stcs and common_rec:
            existing_stcs = set()
            for feat in self.get_features(common_rec, "ST_COMMENT"):
                existing_stcs.update(feat.qualifiers.keys())
            
            missing_stcs = [stc for stc in req_stcs if stc not in existing_stcs]
            if missing_stcs:
                tags_str = ", ".join(active_tags)
                msg = f"Missing required structured comment(s): {', '.join(missing_stcs)} (required for DATATYPE {tags_str})"
                res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="ST_COMMENT")
                res["rule"], res["target"] = "ANN4003", "ST_COMMENT"
                results.append(res)

        # ---------------------------------------------------
        # 必須DBLINKのチェック
        # ---------------------------------------------------
        req_dblinks = compiled_rule["required_dblinks"]
        if req_dblinks and common_rec:
            existing_dblink_texts = set()
            # COMMON内の DBLINK 疑似フィーチャーを取得
            for feat in self.get_features(common_rec, "DBLINK"):
                # QualifierのKey (例: sequence_read_archive) と Value (例: SRR...) の両方を検索対象にする
                for k, vals in feat.qualifiers.items():
                    existing_dblink_texts.add(k.strip().lower())
                    for v in vals:
                        existing_dblink_texts.add(v.strip().lower())
            
            missing_dblinks = []
            for req_db in req_dblinks:
                # "Sequence Read Archive" が "sequence_read_archive" キーなどにマッチするよう空白とアンダースコアを同一視
                req_db_normalized = req_db
                
                # キー名に含まれているか、値の部分文字列として含まれているかを判定
                has_dblink = any(
                    req_db == ex_db or req_db_normalized == ex_db
                    for ex_db in existing_dblink_texts
                )
                if not has_dblink:
                    missing_dblinks.append(req_db)
                    
            if missing_dblinks:
                tags_str = ", ".join(active_tags)
                msg = f"Missing required DBLINK(s): {', '.join(missing_dblinks)} (required for DATATYPE {tags_str})"
                res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="DBLINK")
                res["rule"], res["target"] = "ANN0910", "DBLINK"
                results.append(res)
                        
        # --- (D) sourceフィーチャーの Qualifier チェック ---
        req_quals = compiled_rule["required_qualifiers"]
        rec_quals = compiled_rule["recommended_qualifiers"]
        unsupported_quals = compiled_rule["unsupported_qualifiers"]
        
        if req_quals or rec_quals or unsupported_quals:
            tags_str = ", ".join(active_tags)
            for entry_id, record in records.items():
                if entry_id == "COMMON": continue
                
                source_feats = self.get_features(record, "source")
                if not source_feats: continue
                
                source_quals = set()
                for feat in source_feats:
                    source_quals.update(feat.qualifiers.keys())
                
                if not source_quals: continue
                
                # 必須 (FATAL)
                missing_req = [rq for rq in req_quals if rq not in source_quals]
                if missing_req:
                    msg = f"Missing required qualifier(s) in source: {', '.join(missing_req)} (required for DATATYPE {tags_str})"
                    res = self.feature_result(record, source_feats[0], msg, level="error")
                    res["rule"], res["target"] = "ANN4004", "source"
                    results.append(res)
                    
                # 推奨
                missing_rec = [rq for rq in rec_quals if rq not in source_quals]
                if missing_rec:
                    msg = f"Missing recommended qualifier(s) in source: {', '.join(missing_rec)} (required for DATATYPE {tags_str}). If these are not appropriate, please ignore this message."
                    res = self.feature_result(record, source_feats[0], msg, level="warning")
                    res["rule"], res["target"] = "ANN4005", "source"
                    results.append(res)

                # 禁止Qualifier (unsupported_qualifiers) のチェック
                for feat in source_feats:
                    for iq in unsupported_quals:
                        if iq in feat.qualifiers:
                            err_info = DIVISION_QUALIFIER_VALIDATOR.QUAL_ERRORS.get(
                                iq, 
                                {"rule_id": "ANNXXXX", "msg": f"The '{iq}' qualifier is not permitted for DATATYPE '{tags_str}'."}
                            )
                            res = self.feature_result(record, feat, err_info["msg"], level="error", qualifier=iq)
                            res["rule"], res["target"] = err_info["rule_id"], "source"
                            results.append(res)
                    
        return results

class ANN0640(BaseRule):
    rule_id = "ANN0640"
    alternate_id = "JP1015"
    target = "DATATYPE"
    description = "Keyword or Division requires specific DATATYPE/type."
    requires_rdb = False
    is_file_level = True

    def __init__(self, ddbj_dict=None):
        self.keyword_to_datatypes = defaultdict(set)
        self.division_to_datatypes = defaultdict(set)
        self.is_initialized = False

    def _initialize_dict(self, context):
        if self.is_initialized:
            return
            
        type_rules = context.ddbj_dict.get("datatypes", {})
        
        # ---------------------------------------------------
        # JSONから「キーワード/DIVISION -> 要求されるDATATYPE」の逆引き辞書を自動生成
        # ---------------------------------------------------
        for dt, rule in type_rules.items():
            dt_exact = dt
            
            for kw_group in rule.get("required_keywords", []):
                for kw in kw_group:
                    self.keyword_to_datatypes[kw].add(dt_exact)
            
            req_div = rule.get("required_division")
            if req_div:
                self.division_to_datatypes[req_div].add(dt_exact)
                
        self.is_initialized = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        self._initialize_dict(context)
        
        results = []
        common_rec = records.get("COMMON")
        if not common_rec:
            return results

        # 1. 実際に記述されている DATATYPE を収集 (context から利用)
        existing_datatypes = context.active_datatypes

        # 2. KEYWORD や DIVISION を走査し、DATATYPE の入力を促す (FATAL)
        # --- KEYWORD -> DATATYPE チェック ---
        for feat in self.get_features(common_rec, "KEYWORD"):
            for kw in feat.qualifiers.get("keyword", []):
                if kw in self.keyword_to_datatypes:
                    required_dts = self.keyword_to_datatypes[kw]
                    if not any(dt in existing_datatypes for dt in required_dts):
                        req_dts_str = " or ".join(sorted(required_dts))
                        msg = f'Keyword "{kw}" requires DATATYPE/type "{req_dts_str}".'
                        res = self.feature_result(common_rec, feat, msg, level="error", qualifier="keyword")
                        res["rule"] = self.rule_id
                        res["target"] = "KEYWORD"
                        results.append(res)
                        
        # --- DIVISION -> DATATYPE チェック ---
        for feat in self.get_features(common_rec, "DIVISION"):
            for div in feat.qualifiers.get("division", []):
                if div in self.division_to_datatypes:
                    required_dts = self.division_to_datatypes[div]
                    if not any(dt in existing_datatypes for dt in required_dts):
                        req_dts_str = " or ".join(sorted(required_dts))
                        msg = f'DIVISION "{div}" requires DATATYPE/type "{req_dts_str}".'
                        res = self.feature_result(common_rec, feat, msg, level="error", qualifier="division")
                        res["rule"] = "ANN0641" # DIVISION 起点のエラー
                        res["target"] = "DIVISION"
                        results.append(res)

        return results

class DIV_TYPE_DYNAMIC_VALIDATOR(BaseRule):
    rule_id = "DIV_TYPE_DYNAMIC_MASTER"
    target = "file"
    description = "Dynamic validation for specific DIVISION and DATATYPE edge cases"
    requires_rdb = False
    is_file_level = True

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        if not records:
            return results

        common_rec = records.get("COMMON")
        if not common_rec:
            return results

        existing_keywords = set()
        kw_feat_ref = None
        for feat in self.get_features(common_rec, "KEYWORD"):
            if not kw_feat_ref: kw_feat_ref = feat
            existing_keywords.update(feat.qualifiers.get("keyword", []))

        # [特例 A] HTC_FLI の矛盾チェック
        if "HTC_FLI" in existing_keywords and "HTC" not in existing_keywords:
            msg = "Keyword 'HTC_FLI' requires 'HTC' to be present"
            if kw_feat_ref:
                res = self.feature_result(common_rec, kw_feat_ref, msg, level="error", qualifier="keyword")
            else:
                res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="KEYWORD")
            res["rule"], res["target"] = "ANN0640", "KEYWORD"
            results.append(res)

        # [特例 B] EST の 3'-EST コメント必須チェック
        if "3'-end sequence (3'-EST)" in existing_keywords:
            valid_comments = [
                "3'-EST sequences are presented as anti-sense strand.",
                "3'-EST sequences are presented as sense strand.",
                "3’-EST sequences are presented as anti-sense strand.",
                "3’-EST sequences are presented as sense strand."
            ]
            has_required_comment = False
            for feat in self.get_features(common_rec, "COMMENT"):
                comment_text = str(feat.qualifiers) 
                if any(req_text in comment_text for req_text in valid_comments):
                    has_required_comment = True
                    break
            
            if not has_required_comment:
                msg = "Keyword '3'-end sequence (3'-EST)' requires a specific strand direction statement in COMMENT"
                res = self.format_result(entry_id="COMMON", message=msg, level="error", feature_type="COMMENT")
                res["rule"], res["target"] = "ANN4011", "COMMENT"
                results.append(res)
                
        return results
        
class DIVISION_QUALIFIER_VALIDATOR(BaseRule):
    rule_id = "DIVISION_QUALIFIER_MASTER"
    target = "source"
    description = "Validate unsupported qualifiers based on taxonomic division"
    requires_rdb = True  
    is_file_level = True

    QUAL_ERRORS = {
        "dev_stage": {"rule_id": "ANN1430", "msg": "The dev_stage and tissue_type qualifiers are not permitted for VRL, PHG, BCT, or ENV division entries."},
        "tissue_type": {"rule_id": "ANN1430", "msg": "The dev_stage and tissue_type qualifiers are not permitted for VRL, PHG, BCT, or ENV division entries."},
        "germline": {"rule_id": "ANN1440", "msg": "The germline and rearranged qualifiers are not permitted for VRL, PHG, BCT, PLN, or ENV division entries."},
        "rearranged": {"rule_id": "ANN1440", "msg": "The germline and rearranged qualifiers are not permitted for VRL, PHG, BCT, PLN, or ENV division entries."}
    }

    def __init__(self, ddbj_dict=None, tax_data=None):
        pass

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        
        division_rules = context.ddbj_dict.get("divisions")
        
        if not division_rules:
            return results

        for entry_id, record in records.items():
            for feature in self.get_features(record, "source"):
                orgs = feature.qualifiers.get("organism", [])
                org_name = orgs[0].strip() if orgs else None
                
                # Taxonomy DB から division (例: PLN, BCT) を取得
                tax_div = context.tax_data.get(org_name, {}).get("division") if org_name else None

                if not tax_div:
                    continue
                    
                tax_div_upper = tax_div.strip().upper()
                unsupported = division_rules.get(tax_div_upper, {}).get("unsupported_qualifiers", [])

                for q_name in feature.qualifiers:
                    if q_name in unsupported:
                        err_info = self.QUAL_ERRORS.get(
                            q_name, 
                            {"rule_id": "ANNXXXX", "msg": f"The '{q_name}' qualifier is not permitted for {tax_div_upper} division entries."}
                        )
                        msg = f"{err_info['msg']} (organism: '{org_name}', taxonomic division: '{tax_div_upper}')"
                        res = self.feature_result(record, feature, msg, level="warning", qualifier=q_name)
                        res["rule"] = err_info["rule_id"]
                        res["target"] = "source"
                        results.append(res)
                        
        return results