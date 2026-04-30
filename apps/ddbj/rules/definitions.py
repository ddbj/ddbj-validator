import re
from common.rules.base import BaseRule
from apps.ddbj.rules.division_datatype import get_active_divisions

class ANN_DICT_VALIDATOR(BaseRule):
    """
    JSON辞書に基づくマスターバリデーター
    必須、重複、許容値、不正な組み合わせ、相互排他、依存関係、データ型、正規表現書式、配置場所(field_place)、
    および【値に依存する相互排他・依存関係】をすべて一括チェック。
    """
    rule_id = "ANN_DICT_MASTER"
    target = "ALL_FEATURES"
    description = "Dictionary-driven feature and qualifier validation"
    requires_rdb = False
    is_file_level = True  

    def __init__(self, ddbj_dict=None, cv_terms=None, tax_data=None):
        pass

    def validate_file(self, records, context, ann_path=None, seq_path=None):
        results = []
        ddbj_dict = context.ddbj_dict or {"features": {}, "qualifiers": {}}
        cv_terms = context.cv_terms or {}
        tax_data = context.tax_data or {}
        
        features_dict = ddbj_dict.get("features", {})
        qualifiers_dict = ddbj_dict.get("qualifiers", {})
        
        # COMMON のフィーチャー数を事前にカウント
        common_counts, active_datatypes = self._get_common_stats(records)

        active_divisions_dict = get_active_divisions(records, ddbj_dict, tax_data)
        active_dt_divisions = active_divisions_dict.get("datatype", set())

        # =========================================================================
        # ファイル全体での unique_values 記録用辞書 (COMMONとENTRY跨ぎを検知するため)
        # =========================================================================
        global_seen_unique_values = {}

        # ファイル内の全エントリをループ
        for entry_id, record in records.items():
            local_counts = self._count_local_features(record)

            # =========================================================================
            # エントリー単位の unique_values 記録用辞書 (BioProject等の重複検知用)
            # =========================================================================
            entry_seen_unique_values = {}

            # エントリー単位の Feature チェック (必須、シングルトンなど)
            results.extend(self._check_entry_features(
                entry_id, record, local_counts, common_counts, features_dict, ddbj_dict
            ))

            # Qualifier / Metadata Field 単位のチェック
            for feature in self.get_features(record):
                dict_key = feature.type
                f_def = features_dict.get(dict_key)
                
                if not f_def:
                    continue
                    
                # field_place に基づくチェック
                results.extend(self._check_field_place(
                    entry_id, record, feature, f_def, common_counts
                ))

                # Qualifierの必須・シングルトン・いずれか必須チェック
                results.extend(self._check_qualifier_requirements(
                    entry_id, record, feature, f_def
                ))

                # Qualifierの詳細検証 (存在許可、重複値、許容値、型、フォーマット等)
                # 修正: global_seen_unique_values と entry_seen_unique_values の両方を渡す
                results.extend(self._check_qualifiers_details(
                    entry_id, record, feature, f_def, qualifiers_dict, 
                    active_datatypes, active_dt_divisions, ddbj_dict, cv_terms, tax_data,
                    global_seen_unique_values, entry_seen_unique_values
                ))

                # 相互排他と依存関係のチェック
                results.extend(self._check_exclusions_and_dependencies(
                    entry_id, record, feature, ddbj_dict
                ))

        return results
        
    def _get_common_stats(self, records):
        common_counts = {}
        active_datatypes = set()
        if "COMMON" in records:
            for feature in self.get_features(records["COMMON"]):
                f_type = feature.type
                common_counts[f_type] = common_counts.get(f_type, 0) + 1

            for feature in self.get_features(records["COMMON"], "DATATYPE"):
                types = feature.qualifiers.get("type", [])
                for dt in types:
                    active_datatypes.add(dt.strip().upper())
        return common_counts, active_datatypes

    def _count_local_features(self, record):
        local_counts = {}
        for feature in self.get_features(record):
            f_type = feature.type
            local_counts[f_type] = local_counts.get(f_type, 0) + 1
        return local_counts

    def _check_entry_features(self, entry_id, record, local_counts, common_counts, features_dict, ddbj_dict):
        results = []
        # singleton_feature の検証
        for f_type_def, f_def in features_dict.items():
            sing_rule = f_def.get("singleton_feature")
            if sing_rule:
                sing_clean = f_type_def
                if local_counts.get(sing_clean, 0) > 1:
                    msg = sing_rule.get("message", f"More than one {f_type_def} is not allowed.")
                    res = self.format_result(entry_id=entry_id, message=msg, level=sing_rule.get("level", "error").lower(), feature_type=f_type_def)
                    res["rule"] = sing_rule.get("rule_id", "ANN0645"); res["target"] = f_type_def
                    results.append(res)

        # エントリー単位の必須 Feature チェック
        if entry_id != "COMMON":
            total_counts = dict(common_counts)
            for k, v in local_counts.items():
                total_counts[k] = total_counts.get(k, 0) + v

            mandatory_features = ddbj_dict.get("entries", {}).get("mandatory_features", {})
            for req_feat, rule_info in mandatory_features.items():
                req_clean = req_feat.strip()
                if total_counts.get(req_clean, 0) == 0:
                    res = self.format_result(entry_id=entry_id, message=rule_info.get("message"), level=rule_info.get("level", "error").lower(), feature_type=req_feat)
                    res["rule"] = rule_info.get("rule_id", "ANN0225"); res["target"] = "feature"
                    results.append(res)

            singleton_features = ddbj_dict.get("entries", {}).get("singleton_features", {})
            for sing_feat, rule_info in singleton_features.items():
                sing_clean = sing_feat
                if local_counts.get(sing_clean, 0) > 1:
                    res = self.format_result(entry_id=entry_id, message=rule_info.get("message"), level=rule_info.get("level", "warning").lower(), feature_type=sing_feat)
                    res["rule"] = rule_info.get("rule_id", "ANN2690"); res["target"] = "feature"
                    results.append(res)
        return results

    def _check_field_place(self, entry_id, record, feature, f_def, common_counts):
        results = []
        f_type = feature.type
        if entry_id != "COMMON" and f_def.get("feature_type") == "metadata_field":
            field_place = f_def.get("field_place", [])
            allow_both_sections = f_def.get("allow_both_sections", False)

            if "COMMON" in field_place and "ENTRY" not in field_place:
                res = self.feature_result(record, feature, "Should be described in the COMMON section.", level="fatal")
                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                res["rule"] = "ANN0600"; res["target"] = f_type; results.append(res)
                
            elif "COMMON" in field_place and "ENTRY" in field_place:
                if not allow_both_sections and common_counts.get(f_type, 0) > 0:
                    msg = f"Duplicate in the COMMON and ENTRY sections. ({f_type} is found in both COMMON and {entry_id})"
                    res = self.feature_result(record, feature, msg, level="fatal")
                    res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                    res["rule"] = "ANN0610"; res["target"] = f_type; results.append(res)
        return results

    def _check_qualifier_requirements(self, entry_id, record, feature, f_def):
        results = []
        f_type = feature.type
        for req_qual, rule_info in f_def.get("mandatory_qualifiers", {}).items():
            if req_qual not in feature.qualifiers:
                msg = rule_info.get("message", f"'{req_qual}' is required.")
                res = self.feature_result(record, feature, msg, level=rule_info.get("level", "error").lower(), qualifier=req_qual, internal_ignore=rule_info.get("internal_ignore", True))
                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                res["rule"] = rule_info.get("rule_id", "UNKNOWN_RULE"); res["target"] = f_type; results.append(res)

        for sing_qual, rule_info in f_def.get("singleton_qualifiers", {}).items():
            if sing_qual in feature.qualifiers and len(feature.qualifiers[sing_qual]) > 1:
                msg = rule_info.get("message", f"Duplicated '{sing_qual}'.")
                res = self.feature_result(record, feature, msg, level=rule_info.get("level", "error").lower(), qualifier=sing_qual, internal_ignore=rule_info.get("internal_ignore", True))
                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                res["rule"] = rule_info.get("rule_id", "UNKNOWN_RULE"); res["target"] = f_type; results.append(res)

        for rule in f_def.get("either_one_mandatory_qualifiers", []):
            choices = rule.get("choices", [])
            if not choices: continue
            has_any = any(choice in feature.qualifiers for choice in choices)
            if not has_any:
                msg = rule.get("message", f"At least one of {choices} is required for '{f_type}' feature.")
                qualifier_label = ", ".join(choices)
                res = self.feature_result(record, feature, msg, level=rule.get("level", "error").lower(), qualifier=qualifier_label, internal_ignore=rule.get("internal_ignore", True))
                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                res["rule"] = rule.get("rule_id", "ANN0000"); res["target"] = f_type; results.append(res)
        return results

    # 引数の末尾に entry_seen_unique_values を追加
    def _check_qualifiers_details(self, entry_id, record, feature, f_def, qualifiers_dict, 
                                  active_datatypes, active_dt_divisions, ddbj_dict, cv_terms, tax_data, 
                                  global_seen_unique_values, entry_seen_unique_values):
        results = []
        f_type = feature.type
        historical_countries = {c.lower() for c in cv_terms.get("historical_countries", [])}
        missing_reporting_terms = {m.lower() for m in cv_terms.get("missing_reporting_terms", [])}

        allowed_quals = set(f_def.get("mandatory_qualifiers", {}).keys())
        allowed_quals.update(f_def.get("optional_qualifiers", []))
        allowed_quals.update(f_def.get("singleton_qualifiers", {}).keys())

        for q_name, q_values in feature.qualifiers.items():
            if q_name not in allowed_quals:
                msg = f"'{q_name}' qualifier can NOT be used for '{f_type}' feature."
                res = self.feature_result(record, feature, msg, level="error", qualifier=q_name, internal_ignore=True)
                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                res["rule"] = "ANN3040"; res["target"] = f_type; results.append(res)
                continue

            # Datatype ルールに基づく invalid_moltype / required_moltype チェック
            if f_type == "source" and q_name == "mol_type":
                datatype_rules = ddbj_dict.get("datatypes", {})
                for active_dt in active_datatypes:
                    dt_rule = datatype_rules.get(active_dt)
                    if not dt_rule: continue
                    
                    ignore_flag = dt_rule.get("internal_ignore", True)
                    
                    # 1. invalid_moltype チェック
                    invalid_moltypes = dt_rule.get("invalid_moltype", [])
                    for invalid_m in invalid_moltypes:
                        for m_val in q_values:
                            if invalid_m == m_val:
                                rule_id = dt_rule.get("invalid_moltype_rule_id", "ANN0580" if active_dt == "TSA" else "ANN0570")
                                msg = dt_rule.get("invalid_moltype_message", f"{active_dt} entries should not be mol_type {invalid_m}.")
                                res = self.feature_result(record, feature, msg, level="error", qualifier=q_name, internal_ignore=ignore_flag)
                                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                                res["rule"] = rule_id; res["target"] = "sequence"; results.append(res)
                                
                    # 2. required_moltype チェック
                    required_moltypes = dt_rule.get("required_moltype", [])
                    if required_moltypes:
                        allowed_set = set(required_moltypes)
                        if active_dt == "WGS":
                            msg_base = f"The mol_type must be a valid genome assembly sequence type. Accepted values are: {', '.join(required_moltypes)}."
                        else:
                            msg_base = f"The mol_type must be a valid {active_dt} sequence type. Accepted values are: {', '.join(required_moltypes)}."

                        for m_val in q_values:
                            if m_val not in allowed_set:
                                msg = f"{msg_base} (Found: '{m_val}')"
                                rule_id = dt_rule.get("required_moltype_rule_id", "ANN0575")
                                res = self.feature_result(record, feature, msg, level="error", qualifier=q_name, internal_ignore=ignore_flag)
                                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                                res["rule"] = rule_id; res["target"] = "mol_type"; results.append(res)

            q_def = qualifiers_dict.get(q_name) or {}
            
            # =====================================================================
            # 1. 系統(Taxonomy)に基づく特例 Qualifier チェック (ANN1430, 1440, 1450, 1460)
            # =====================================================================
            if f_type == "source" and q_name in ["dev_stage", "tissue_type", "germline", "rearranged", "proviral", "macronuclear"]:
                orgs = feature.qualifiers.get("organism", [])
                org_name = orgs[0].strip() if orgs else None
                tax_info = tax_data.get(org_name, {}) if org_name else {}
                
                lineage = tax_info.get("lineage", "")
                tax_group = tax_info.get("tax_group", "other")
                
                is_valid = True
                rule_id = ""
                msg = ""

                if q_name in ["dev_stage", "tissue_type"]:
                    if tax_group in ["virus", "prokaryote", "environmental"]:
                        is_valid = False
                        rule_id = "ANN1430"
                        msg = f"The '{q_name}' qualifier is not permitted for viral, prokaryotic, or environmental entries. (organism: '{org_name}')"
                        
                elif q_name in ["germline", "rearranged"]:
                    if "Craniata" not in lineage:
                        is_valid = False
                        rule_id = "ANN1440"
                        msg = f"The '{q_name}' qualifier is restricted to Craniata entries. (organism: '{org_name}')"
                        
                elif q_name == "proviral":
                    if tax_group != "virus":
                        is_valid = False
                        rule_id = "ANN1450"
                        msg = f"The '{q_name}' qualifier is restricted to viral entries. (organism: '{org_name}')"
                        
                elif q_name == "macronuclear":
                    if "Ciliophora" not in lineage:
                        is_valid = False
                        rule_id = "ANN1460"
                        msg = f"The '{q_name}' qualifier is restricted to Ciliophora entries. (organism: '{org_name}')"

                if not is_valid:
                    res = self.feature_result(record, feature, msg, level="warning", qualifier=q_name)
                    res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                    res["rule"] = rule_id
                    res["target"] = f_type
                    results.append(res)
                    
            # =====================================================================
            # 2. Datatype / Division 依存の一般的な Qualifier 許可チェック
            # =====================================================================
            else:
                allowed_divs = q_def.get("allowed_divisions")
                if allowed_divs:
                    rule_id = q_def.get("division_rule_id", "ANN0000")
                    allowed_set = set(allowed_divs)
                    
                    if active_dt_divisions:
                        if not active_dt_divisions.intersection(allowed_set):
                            divs_str = ", ".join(sorted(allowed_set))
                            active_divs_str = ", ".join(sorted(active_dt_divisions))
                            msg = f"The '{q_name}' qualifier is restricted to {divs_str} division entries. (current division: '{active_divs_str}')"
                            res = self.feature_result(record, feature, msg, level="error", qualifier=q_name)
                            res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                            res["rule"] = rule_id
                            res["target"] = f_type
                            results.append(res)
                                                                                                                                                    
            # 重複値チェック
            if q_def.get("unique_values"):
                unique_rule = q_def.get("unique_rule", {})
                rule_id = unique_rule.get("rule_id", "ANN0000")
                level = unique_rule.get("level", "error").lower()
                base_msg = unique_rule.get("message", f"Duplicate value in '{q_name}'.")
                ignore_flag = unique_rule.get("internal_ignore", True)
                
                values_to_check = q_values if isinstance(q_values, list) else [q_values]
                
                # デフォルトを 'global' とし、JSONで "unique_scope" が指定された場合に従う
                unique_scope = q_def.get("unique_scope", "global")
                
                if unique_scope == "feature":
                    # フィーチャー単位の場合は毎回空のセットで初期化する
                    seen_values = set()
                elif unique_scope == "entry":
                    # エントリー単位の場合は、そのエントリー専用の辞書を使う
                    if q_name not in entry_seen_unique_values:
                        entry_seen_unique_values[q_name] = set()
                    seen_values = entry_seen_unique_values[q_name]
                else:
                    # global（デフォルト）の場合はファイル全体で管理している辞書を使用する
                    if q_name not in global_seen_unique_values:
                        global_seen_unique_values[q_name] = set()
                    seen_values = global_seen_unique_values[q_name]
                
                for val in values_to_check:
                    val_str = str(val)
                    if val_str in seen_values:
                        msg = f"{base_msg} (Found: '{val_str}')"
                        res = self.feature_result(record, feature, msg, level=level, qualifier=q_name, internal_ignore=ignore_flag)
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = rule_id; res["target"] = f_type
                        results.append(res)
                    else:
                        seen_values.add(val_str)
                                                                        
            # 許容値 (allowed_values) の動的生成と検証
            allowed = q_def.get("allowed_values", [])
            rule_info = q_def.get("value_rule", {})
            
            if q_name == "division":
                allowed = list(ddbj_dict.get("divisions", {}).keys())
                if not rule_info:
                    rule_info = {"rule_id": "ANN3290", "level": "error", "message": "Value not defined in controlled values 'division'."}
            elif f_type.upper() == "DATATYPE" and q_name == "type":
                allowed = list(ddbj_dict.get("datatypes", {}).keys())
                if not rule_info:
                    rule_info = {"rule_id": "ANN3290", "level": "error", "message": "Value not defined in controlled values 'type'."}

            if allowed:
                for val in q_values:
                    is_valid = False
                    custom_msg = None 
                    suggested_fix = None  # Autofix候補を保持する変数
                    
                    if q_name == "inference":
                        parts = val.split(":")
                        type_part = parts[1] if len(parts) >= 2 and parts[0] in {"COORDINATES", "DESCRIPTION", "EXISTENCE"} else parts[0]
                        if type_part.replace(" (same species)", "").strip() in allowed: is_valid = True
                        
                    elif q_name == "geo_loc_name":
                        val_lower = val.lower()
                        if val_lower.startswith("missing:"):
                            if val_lower in missing_reporting_terms: is_valid = True
                        else:
                            country_part = val.split(":")[0].strip()
                            if country_part in allowed: 
                                is_valid = True
                            elif country_part.lower() in historical_countries:
                                is_valid = True
                                
                    elif q_name == "mobile_element_type":
                        parts = str(val).split(":", 1)
                        m_type = parts[0].strip()
                        m_name = parts[1].strip() if len(parts) > 1 else ""
                        
                        if m_type in allowed:
                            if m_type == "other" and not m_name:
                                custom_msg = "Value 'other' requires a mobile_element_name (e.g., 'other:name')."
                                is_valid = False
                            else:
                                is_valid = True

                    elif q_name == "satellite":
                        s_type = re.split(r'[:\s]', str(val).strip(), 1)[0]
                        if s_type in allowed:
                            is_valid = True
                                                                                                                                                                                                                                                                
                    else:
                        # 通常のCVチェック。完全一致しない場合は大文字小文字を無視してチェック
                        str_val = str(val)
                        allowed_strs = [str(a) for a in allowed]
                        
                        if str_val in allowed_strs:
                            is_valid = True
                        else:
                            val_lower = str_val.lower()
                            for a_str in allowed_strs:
                                if a_str.lower() == val_lower:
                                    # 大文字小文字の違いだけであればAutofix対象とする
                                    suggested_fix = a_str
                                    custom_msg = f"{rule_info.get('message', '')}"
                                    break
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                
                    if not is_valid:
                        base_msg = custom_msg if custom_msg else rule_info.get('message', '')
                        msg = f"{base_msg} (Found: '{val}')".strip()
                        
                        res = self.feature_result(record, feature, msg, level=rule_info.get("level", "warning").lower(), qualifier=q_name)
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = rule_info.get("rule_id", "ANN3290"); res["target"] = f_type
                        
                        # Autofixが可能な場合はメタデータを付与
                        if suggested_fix:
                            res["autofix"] = True
                            res["fix_target"] = "qualifier"
                            res["old_value"] = str(val)
                            res["new_value"] = suggested_fix
                            
                        results.append(res)
                        
            if not q_def:
                continue

            # =====================================================================
            # 値の型(value-less)、フォーマット(正規表現)、最大長の検証
            # =====================================================================
            field_type = q_def.get("field_type")
            for val in q_values:
                # 旧 qual_phi (値を持たないフラグ) のチェック
                if field_type == "value-less" and val != "":
                    res = self.feature_result(record, feature, f"Invalid format: '{q_name}' takes no value (Found: '{val}')", level="error", qualifier=q_name)
                    res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                    res["rule"] = "ANN0185"; res["target"] = f_type
                    results.append(res)

            # replace 固有の塩基配列チェック (空文字許容、cv_terms参照)
            if q_name == "replace":
                allowed_bases = set(cv_terms.get("nucleic_acids", []))
                for val in q_values:
                    val_str = str(val)
                    # 空文字 (deletion) は許容
                    if val_str == "":
                        continue
                    
                    # 許可されていない文字が含まれているかチェック (小文字のみ許容)
                    invalid_chars = set(val_str) - allowed_bases
                    if invalid_chars:
                        msg = f"Invalid nucleotide codes in the 'replace' qualifier. Only lower-case IUPAC nucleotide codes (or an empty value) are allowed. (Found: '{val_str}')"
                        res = self.feature_result(record, feature, msg, level="error", qualifier=q_name)
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = "ANN0185"; res["target"] = f_type
                        results.append(res)

            # ^\d+$ 等のフォーマットチェック
            pattern_str = q_def.get("format_pattern")
            if pattern_str:
                pattern = re.compile(pattern_str)
                fmt_rule = q_def.get("format_rule", {})
                rule_id = fmt_rule.get("rule_id", "ANN0185")
                level = fmt_rule.get("level", "error").lower()
                base_msg = fmt_rule.get("message", f"Invalid format for '{q_name}'.")
                ignore_flag = fmt_rule.get("internal_ignore", True)
                
                for val in q_values:
                    if q_name in ("collection_date", "geo_loc_name") and val.lower() in missing_reporting_terms:
                        continue
                        
                    if val != "" and not pattern.match(val):
                        msg = f"{base_msg} (Found: '{val}')"
                        res = self.feature_result(record, feature, msg, level=level, qualifier=q_name, internal_ignore=ignore_flag)
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = rule_id; res["target"] = f_type
                        results.append(res)
                                                
            # 最大長チェック
            max_len = q_def.get("max_length")

            if max_len is not None:
                length_rule = q_def.get("length_rule", {})
                rule_id = length_rule.get("rule_id", "ANN3100")
                level = length_rule.get("level", "error").lower() 
                base_msg = length_rule.get("message", f"Maximum length for '{q_name}' is {max_len:,} characters.")
                ignore_flag = length_rule.get("internal_ignore", True)
                
                values_to_check = q_values if isinstance(q_values, list) else [q_values]
                
                for val in values_to_check:
                    val_str = str(val) 
                    if len(val_str) > max_len: 
                        msg = f"{base_msg} (Found: {len(val_str):,} chars)"
                        res = self.feature_result(record, feature, msg, level=level, qualifier=q_name, internal_ignore=ignore_flag)
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = rule_id; res["target"] = f_type
                        results.append(res)
                        
        return results

    def _check_exclusions_and_dependencies(self, entry_id, record, feature, ddbj_dict):
        results = []
        f_type = feature.type
        mutual_exclusions = ddbj_dict.get("rules", {}).get("mutual_exclusions", [])
        dependencies = ddbj_dict.get("rules", {}).get("required_dependencies", [])
        value_mutual_exclusions = ddbj_dict.get("rules", {}).get("value_mutual_exclusions", [])
        value_dependencies = ddbj_dict.get("rules", {}).get("value_dependencies", [])

        # シンプルな相互排他と依存関係のチェック
        for rule in mutual_exclusions:
            q1 = rule.get("qualifier_1"); q2 = rule.get("qualifier_2")
            if q1 in feature.qualifiers and q2 in feature.qualifiers:
                res = self.feature_result(record, feature, rule.get("message"), level=rule.get("level", "error").lower(), qualifier=q1, internal_ignore=rule.get("internal_ignore", True))
                res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                res["rule"] = rule.get("rule_id", "ANN3150"); res["target"] = f_type; results.append(res)

        for rule in dependencies:
            q_present = rule.get("if_present")
            q_required = rule.get("requires")
            
            if q_present in feature.qualifiers:
                if isinstance(q_required, list):
                    if not any(req in feature.qualifiers for req in q_required):
                        res = self.feature_result(record, feature, rule.get("message"), level=rule.get("level", "error").lower(), qualifier=q_present, internal_ignore=rule.get("internal_ignore", True))
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = rule.get("rule_id", "ANN3110"); res["target"] = f_type; results.append(res)
                else:
                    if q_required not in feature.qualifiers:
                        res = self.feature_result(record, feature, rule.get("message"), level=rule.get("level", "error").lower(), qualifier=q_present, internal_ignore=rule.get("internal_ignore", True))
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = rule.get("rule_id", "ANN3110"); res["target"] = f_type; results.append(res)
                        
        # 値(Value)に依存する相互排他チェック
        for rule in value_mutual_exclusions:
            q1 = rule.get("qualifier_1")
            v1 = rule.get("value_1")
            q2 = rule.get("qualifier_2")
            
            if q1 in feature.qualifiers and q2 in feature.qualifiers:
                if any(str(val) == v1 for val in feature.qualifiers[q1]):
                    res = self.feature_result(record, feature, rule.get("message"), level=rule.get("level", "error").lower(), qualifier=q2, internal_ignore=rule.get("internal_ignore", True))
                    res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                    res["rule"] = rule.get("rule_id", "ANN3160"); res["target"] = f_type
                    results.append(res)

        # 値(Value)に依存する必須依存チェック
        for rule in value_dependencies:
            q1 = rule.get("qualifier_1")
            v1 = rule.get("value_1")
            q_req = rule.get("requires")
            
            if q1 in feature.qualifiers:
                if any(str(val) == v1 for val in feature.qualifiers[q1]):
                    is_missing = False
                    if isinstance(q_req, list):
                        if not any(req in feature.qualifiers for req in q_req):
                            is_missing = True
                    else:
                        if q_req not in feature.qualifiers:
                            is_missing = True
                            
                    if is_missing:
                        res = self.feature_result(record, feature, rule.get("message"), level=rule.get("level", "error").lower(), qualifier=q1, internal_ignore=rule.get("internal_ignore", True))
                        res["entry"] = getattr(feature, 'original_entry_id', entry_id)
                        res["rule"] = rule.get("rule_id", "ANN3165"); res["target"] = f_type
                        results.append(res)

        return results        