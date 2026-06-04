import re
from Bio.SeqFeature import BeforePosition, AfterPosition
from apps.ddbj.utils.features import get_features
from apps.ddbj.autofix.proposal import build_proposal, update_qualifier_action, update_location_action

from common.format import (
    _INSDC_DATE_PATTERN,
    fix_insdc_date,
    fix_insdc_lat_lon
)

# --- 定数と正規表現 ---
_VALID_METHOD_PATTERN = re.compile(r"^.+?\s+v\.\s+\S.*$", re.IGNORECASE)
# ツール名と、数字から始まるバージョン文字列（ピリオド・ハイフン・英字含む）を抽出
# 区切りとして「1つ以上の空白」または「v, ver, version（前後の空白許容）」を要求
_FIX_METHOD_PATTERN = re.compile(r"^(.*?)(?:\s+|[\s]*(?:v\.?|version|ver\.?))[\s]*([0-9][\d\.a-zA-Z-]*)$", re.IGNORECASE)
_FWD_SEQ_PATTERN = re.compile(r'(fwd_seq:\s*)([A-Za-z]+)')
_REV_SEQ_PATTERN = re.compile(r'(rev_seq:\s*)([A-Za-z]+)')
_COV_NUMERIC_PATTERN = re.compile(r'^(\d+(?:\.\d+)?)$')
_HOLD_DATE_SALVAGE_PATTERN = re.compile(r"^(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])$")

# ==========================================
# 共通ロジック
# ==========================================
def _propose_mapping_fixes(records, ann_path, target_qualifier, allowed_map, existing_proposals=None, match_prefix=False, missing_terms_map=None, rule_id="UNKNOWN"):
    existing_proposals = existing_proposals or []
    missing_terms_map = missing_terms_map or {}
    bs_targets = {(pos["entry"], pos["feature_id"]) for p in existing_proposals if p["target"] == target_qualifier for pos in p.get("positions", [])}
    
    proposals = []
    for entry_id, record in records.items():
        for feature in get_features(record):
            if target_qualifier in feature.qualifiers:
                feat_id = getattr(feature, 'line_number', id(feature))
                if (entry_id, feat_id) in bs_targets:
                    continue
                    
                vals = feature.qualifiers[target_qualifier]
                for i, val in enumerate(vals):
                    val_str = str(val).strip()
                    fixed_val = None
                    val_lower = val_str.lower()
                    
                    val_norm = val_lower.replace(" ", "")
                    
                    if val_norm in missing_terms_map:
                        if val_str != missing_terms_map[val_norm]:
                            fixed_val = missing_terms_map[val_norm]
                    else:
                        if match_prefix and ':' in val_str:
                            prefix, sep, suffix = val_str.partition(':')
                            prefix_lower = prefix.strip().lower()
                            if prefix_lower in allowed_map:
                                fixed_prefix = allowed_map[prefix_lower]
                                if prefix != fixed_prefix:
                                    fixed_val = val_str.replace(prefix, fixed_prefix, 1)
                        else:
                            if val_lower in allowed_map and allowed_map[val_lower] != val_str:
                                fixed_val = allowed_map[val_lower]

                    if fixed_val and fixed_val != val_str:
                        updates = [update_qualifier_action(entry_id, feature.type, target_qualifier, val_str, fixed_val, feature_id=feat_id)]

                        proposals.append(build_proposal(
                            ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                            qualifier=target_qualifier, target=target_qualifier, target_level="qualifier",
                            positions=[{"entry": entry_id, "feature_id": feat_id}],
                            old_value=val_str, new_value=fixed_val, rule=rule_id,
                            updates=updates, source_db=""
                        ))
    return proposals


def propose_geo_loc_name_fixes(records, ann_path, allowed_values, allowed_missing_reporting_terms=None, existing_proposals=None):
    allowed_map = {v.lower(): v for v in allowed_values}
    missing_terms_map = {m.lower().replace(" ", ""): m.lower() for m in (allowed_missing_reporting_terms or [])}
    return _propose_mapping_fixes(records, ann_path, "geo_loc_name", allowed_map, existing_proposals, match_prefix=True, missing_terms_map=missing_terms_map, rule_id="ANN1250")


def propose_culture_collection_fixes(records, ann_path, allowed_map, existing_proposals=None):
    return _propose_mapping_fixes(records, ann_path, "culture_collection", allowed_map, existing_proposals, match_prefix=True, rule_id="ANN1290")


def propose_format_errors(records, ann_path):
    proposals = []
    
    for entry_id, record in records.items():
        for feature in get_features(record, "ST_COMMENT"):
            
            # --- Assembly Method の Autofix ---
            if "Assembly Method" in feature.qualifiers:
                methods = feature.qualifiers["Assembly Method"]
                for i, method in enumerate(methods):
                    val_str = str(method).strip()
                    parts = [p.strip() for p in val_str.split(";") if p.strip()]

                    is_valid = True
                    can_autofix = True
                    fixed_parts = []

                    for part in parts:
                        if _VALID_METHOD_PATTERN.match(part):
                            fixed_parts.append(part)
                        else:
                            is_valid = False
                            match = _FIX_METHOD_PATTERN.match(part)
                            if match:
                                software = match.group(1).strip()
                                version = match.group(2).strip()
                                if software and version:
                                    fixed_parts.append(f"{software} v. {version}")
                                else:
                                    can_autofix = False
                                    fixed_parts.append(part)
                            else:
                                can_autofix = False
                                fixed_parts.append(part)

                    if not is_valid and can_autofix:
                        suggested = "; ".join(fixed_parts)
                        if suggested != val_str:
                            updates = [update_qualifier_action(entry_id, feature.type, "Assembly Method", val_str, suggested, feature_id=getattr(feature, 'line_number', id(feature)))]

                            proposals.append(build_proposal(
                                ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                                qualifier="Assembly Method", target="Assembly Method", target_level="field",
                                positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                                old_value=val_str, new_value=suggested, rule="ANN0800",
                                updates=updates, source_db=""
                            ))
            
            # --- Genome Coverage の Autofix (既存のまま) ---
            if "Genome Coverage" in feature.qualifiers:
                coverages = feature.qualifiers["Genome Coverage"]
                for i, cov in enumerate(coverages):
                    match = _COV_NUMERIC_PATTERN.match(cov.strip())
                    if match:
                        suggested = f"{match.group(1)}x" 
                        
                        updates = [update_qualifier_action(entry_id, feature.type, "Genome Coverage", cov, suggested, feature_id=getattr(feature, 'line_number', id(feature)))]

                        proposals.append(build_proposal(
                            ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                            qualifier="Genome Coverage", target="Genome Coverage", target_level="field",
                            positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                            old_value=cov, new_value=suggested, rule="ANN0810",
                            updates=updates, source_db=""
                        ))
    
    return proposals

# ==========================================
# Location / PCR Primers の Autofix 提案処理
# ==========================================
def propose_location_overlap_fixes(records, ann_path):
    """
    assembly_gap と CDS/mRNA の location に重複がある場合、
    自動でトリミングした location 文字列を提案する。
    """
    proposals = []
    for entry_id, record in records.items():
        gaps = get_features(record, "assembly_gap")
        targets = get_features(record, "CDS") + get_features(record, "mRNA")
        
        for target in targets:
            original_loc_str = getattr(target, "original_location", None)
            
            if not original_loc_str or not target.location:
                continue
                
            T_start_1b = target.location.start + 1
            T_end_1b = target.location.end
            
            new_loc_str = original_loc_str
            match_found = False
            
            for gap in gaps:
                if not gap.location:
                    continue
                    
                G_start_1b = gap.location.start + 1
                G_end_1b = gap.location.end
                
                if G_start_1b <= T_start_1b <= G_end_1b < T_end_1b:
                    new_start = G_end_1b + 1
                    old_str_pattern = r"(<|>)?\b" + str(T_start_1b) + r"\b"
                    new_str_repl = f"<{new_start}"
                    new_loc_str = re.sub(old_str_pattern, new_str_repl, new_loc_str, count=1)
                    match_found = True
                    
                elif T_start_1b < G_start_1b <= T_end_1b <= G_end_1b:
                    new_end = G_start_1b - 1
                    old_str_pattern = r"(<|>)?\b" + str(T_end_1b) + r"\b"
                    new_str_repl = f">{new_end}"
                    new_loc_str = re.sub(old_str_pattern, new_str_repl, new_loc_str, count=1)
                    match_found = True
                    
            if match_found and new_loc_str != original_loc_str:
                updates = [update_location_action(entry_id, target.type, original_loc_str, new_loc_str, feature_id=getattr(target, 'line_number', id(target)))]

                proposals.append(build_proposal(
                    ann_path=ann_path, entry=entry_id, feature_type=target.type,
                    qualifier=None, target="location", target_level="location",
                    positions=[{"entry": entry_id, "feature_id": getattr(target, 'line_number', id(target))}],
                    old_value=original_loc_str, new_value=new_loc_str, rule="LOCATION_OVERLAP",
                    updates=updates, source_db=""
                ))
                
    return proposals
    
def propose_pcr_primer_fixes(records, ann_path):
    """
    PCR_primers の fwd_seq/rev_seq の塩基配列部分を小文字にフォーマットする提案。
    """
    proposals = []
    for entry_id, record in records.items():
        for feature in get_features(record):
            if "PCR_primers" in feature.qualifiers:
                old_vals = feature.qualifiers["PCR_primers"]
                for i, val in enumerate(old_vals):
                    new_val = _FWD_SEQ_PATTERN.sub(
                        lambda m: m.group(1) + m.group(2).lower(), 
                        val
                    )
                    new_val = _REV_SEQ_PATTERN.sub(
                        lambda m: m.group(1) + m.group(2).lower(), 
                        new_val
                    )
                    if new_val != val:
                        updates = [update_qualifier_action(entry_id, feature.type, "PCR_primers", val, new_val, feature_id=getattr(feature, 'line_number', id(feature)))]

                        proposals.append(build_proposal(
                            ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                            qualifier="PCR_primers", target="PCR_primers", target_level="qualifier",
                            positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                            old_value=val, new_value=new_val, rule="PCR_PRIMER_FORMAT",
                            updates=updates, source_db=""
                        ))
                        
    return proposals    

# ==========================================
# 日付の Auto-fix ロジック
# ==========================================
def propose_date_fixes(records, ann_path, allowed_missing_reporting_terms=None, existing_proposals=None):
    """
    日付の書式を自動補正する提案を作成する。
    ただし、BioSample等ですでに上書き提案が存在する場合は競合を避けるためスキップする。
    """
    existing_proposals = existing_proposals or []
    allowed_missing_reporting_terms = allowed_missing_reporting_terms or set()
    
    normalized_missing_map = {m.lower().replace(" ", ""): m.lower() for m in allowed_missing_reporting_terms}
    
    bs_targets = set()
    for p in existing_proposals:
        if p["target"] == "collection_date":
            for pos in p.get("positions", []):
                bs_targets.add((pos["entry"], pos["feature_id"]))

    proposals = []
    for entry_id, record in records.items():
        for feature in get_features(record):
            if "collection_date" in feature.qualifiers:
                feat_id = getattr(feature, 'line_number', id(feature))
                
                if (entry_id, feat_id) in bs_targets:
                    continue
                    
                dates = feature.qualifiers["collection_date"]
                for i, date_val in enumerate(dates):
                    val_str = str(date_val).strip()
                    val_norm = val_str.lower().replace(" ", "")
                    
                    if val_norm in normalized_missing_map:
                        fixed_val = normalized_missing_map[val_norm]
                        if val_str != fixed_val:
                            updates = [update_qualifier_action(entry_id, feature.type, "collection_date", val_str, fixed_val, feature_id=feat_id)]

                            proposals.append(build_proposal(
                                ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                                qualifier="collection_date", target="collection_date", target_level="qualifier",
                                positions=[{"entry": entry_id, "feature_id": feat_id}],
                                old_value=val_str, new_value=fixed_val, rule="ANN1230",
                                updates=updates, source_db=""
                            ))
                        continue

                    if not _INSDC_DATE_PATTERN.match(val_str):
                        fixed_date = fix_insdc_date(val_str)
                        
                        if fixed_date and fixed_date != val_str and _INSDC_DATE_PATTERN.match(fixed_date):
                            updates = [update_qualifier_action(entry_id, feature.type, "collection_date", val_str, fixed_date, feature_id=feat_id)]

                            proposals.append(build_proposal(
                                ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                                qualifier="collection_date", target="collection_date", target_level="qualifier",
                                positions=[{"entry": entry_id, "feature_id": feat_id}],
                                old_value=val_str, new_value=fixed_date, rule="ANN1230",
                                updates=updates, source_db=""
                            ))
    return proposals

def propose_latlon_fixes(records, ann_path, existing_proposals=None):
    """
    lat_lon の書式を自動補正する提案を作成する。
    BioSample等ですでに上書き提案が存在する場合はスキップ。
    """
    existing_proposals = existing_proposals or []
    bs_targets = set()
    for p in existing_proposals:
        if p["target"] == "lat_lon":
            for pos in p.get("positions", []):
                bs_targets.add((pos["entry"], pos["feature_id"]))

    proposals = []
    for entry_id, record in records.items():
        for feature in get_features(record):
            if "lat_lon" in feature.qualifiers:
                feat_id = getattr(feature, 'line_number', id(feature))
                
                if (entry_id, feat_id) in bs_targets:
                    continue
                    
                latlons = feature.qualifiers["lat_lon"]
                for i, val in enumerate(latlons):
                    fixed_val = fix_insdc_lat_lon(val)
                    
                    if fixed_val and fixed_val != val:
                        updates = [update_qualifier_action(entry_id, feature.type, "lat_lon", val, fixed_val, feature_id=feat_id)]

                        proposals.append(build_proposal(
                            ann_path=ann_path, entry=entry_id, feature_type=getattr(feature, 'type', ''),
                            qualifier="lat_lon", target="lat_lon", target_level="qualifier",
                            positions=[{"entry": entry_id, "feature_id": feat_id}],
                            old_value=val, new_value=fixed_val, rule="ANN1270",
                            updates=updates, source_db="",
                            message=f"The 'lat_lon' value exceeds the maximum of 8 decimal places. (Found: '{val}')"
                        ))

    return proposals
    
def propose_partial_location_fixes(records, ann_path, tax_data):
    """
    原核生物のCDSにおいて、末端やgapから1〜2塩基離れた partial な location を
    末端やgapの境界ぴったりまで伸ばす(partialのまま)提案を作成する (例: <2 -> <1)
    """
    proposals = []
    tax_data = tax_data or {}

    for entry_id, record in records.items():
        if entry_id == "COMMON":
            continue

        # 原核生物(Archaea, Bacteria)であるかを判定
        is_prokaryote = False
        for feature in get_features(record, "source"):
            for org in feature.qualifiers.get("organism", []):
                if tax_data.get(org.strip(), {}).get("tax_group") == "prokaryote":
                    is_prokaryote = True
                    break
            if is_prokaryote:
                break
        
        if not is_prokaryote:
            continue

        # gap および assembly_gap のゲノム座標を収集
        gaps = []
        for gap_type in ("gap", "assembly_gap"):
            for feature in get_features(record, gap_type):
                if feature.location:
                    gaps.append((int(feature.location.start), int(feature.location.end)))

        seq_len = len(record.seq)

        # CDS をピンポイントで取得
        for feature in get_features(record, "CDS"):
            if not feature.location:
                continue

            is_left_partial = isinstance(feature.location.start, BeforePosition)
            is_right_partial = isinstance(feature.location.end, AfterPosition)

            if not (is_left_partial or is_right_partial):
                continue

            start_val = int(feature.location.start)
            end_val = int(feature.location.end)
            
            original_loc_str = getattr(feature, 'original_location', str(feature.location))
            new_loc_str = original_loc_str
            fix_needed = False

            # 左端（<）の補正：距離が 1 or 2 の場合のみ境界ぴったりに伸ばす
            if is_left_partial:
                if 0 < start_val <= 2:  # 先頭から1〜2塩基のズレ (<2, <3)
                    new_loc_str = re.sub(rf"<{start_val + 1}\b", "<1", new_loc_str)
                    fix_needed = True
                else:
                    for g_start, g_end in gaps:
                        diff = start_val - g_end
                        if 0 < diff <= 2:  # ギャップ終端から1〜2塩基のズレ
                            new_loc_str = re.sub(rf"<{start_val + 1}\b", f"<{g_end + 1}", new_loc_str)
                            fix_needed = True
                            break

            # 右端（>）の補正：距離が 1 or 2 の場合のみ境界ぴったりに伸ばす
            if is_right_partial:
                if 0 < (seq_len - end_val) <= 2:  # 末端から1〜2塩基のズレ
                    new_loc_str = re.sub(rf">{end_val}\b", f">{seq_len}", new_loc_str)
                    fix_needed = True
                else:
                    for g_start, g_end in gaps:
                        diff = g_start - end_val
                        if 0 < diff <= 2:  # ギャップ始端から1〜2塩基のズレ
                            new_loc_str = re.sub(rf">{end_val}\b", f">{g_start}", new_loc_str)
                            fix_needed = True
                            break

            if fix_needed and new_loc_str != original_loc_str:
                updates = [update_location_action(entry_id, feature.type, original_loc_str, new_loc_str, feature_id=getattr(feature, 'line_number', id(feature)))]

                proposals.append(build_proposal(
                    ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                    qualifier=None, target="location", target_level="location",
                    positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                    old_value=original_loc_str, new_value=new_loc_str, rule="ANN4240",
                    updates=updates, source_db=""
                ))

    return proposals    

    
def propose_hold_date_fixes(records, ann_path, existing_proposals=None):
    """
    hold_date の YYYY-MM-DD または YYYY/MM/DD (20XX年のみ) を 
    YYYYMMDD (半角数字8桁) 形式に補正する提案を作成する。
    """
    existing_proposals = existing_proposals or []
    bs_targets = {
        (pos["entry"], pos["feature_id"]) 
        for p in existing_proposals if p["target"] == "hold_date" 
        for pos in p.get("positions", [])
    }

    proposals = []
    for entry_id, record in records.items():
        for feature in get_features(record):
            if "hold_date" in feature.qualifiers:
                feat_id = getattr(feature, 'line_number', id(feature))
                
                if (entry_id, feat_id) in bs_targets:
                    continue
                    
                dates = feature.qualifiers["hold_date"]
                for i, date_val in enumerate(dates):
                    val_str = str(date_val).strip()
                    
                    # サルベージパターン (20XX-MM-DD または 20XX/MM/DD) にマッチするか確認
                    match = _HOLD_DATE_SALVAGE_PATTERN.match(val_str)
                    if match:
                        # ハイフン・スラッシュを抜いた YYYYMMDD を生成
                        fixed_date = f"{match.group(1)}{match.group(2)}{match.group(3)}"
                        
                        if fixed_date != val_str:
                            updates = [update_qualifier_action(entry_id, feature.type, "hold_date", val_str, fixed_date, feature_id=feat_id)]

                            proposals.append(build_proposal(
                                ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                                qualifier="hold_date", target="hold_date", target_level="qualifier",
                                positions=[{"entry": entry_id, "feature_id": feat_id}],
                                old_value=val_str, new_value=fixed_date,
                                rule="ANN0185",  # hold_dateフォーマットエラーのRule ID
                                updates=updates, source_db=""
                            ))
    return proposals

    
def propose_location_whitespace_fixes(records, ann_path):
    """
    Location 文字列に含まれる空白(スペースやタブ)を自動除去する提案を作成。
    """
    proposals = []
    for entry_id, record in records.items():
        for feature in get_features(record):
            original_loc_str = getattr(feature, 'original_location', None)
            
            if not original_loc_str:
                continue
                
            # 空白（スペース、タブなど）が含まれているかチェック
            if re.search(r'\s', original_loc_str):
                new_loc_str = re.sub(r'\s+', '', original_loc_str)
                
                updates = [update_location_action(entry_id, feature.type, original_loc_str, new_loc_str, feature_id=getattr(feature, 'line_number', id(feature)))]

                proposals.append(build_proposal(
                    ann_path=ann_path, entry=entry_id, feature_type=feature.type,
                    qualifier=None, target="location", target_level="location",
                    positions=[{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                    old_value=original_loc_str, new_value=new_loc_str,
                    rule="ANN2020",  # 空白除去（AUTO-CLEANUP）のルールID
                    updates=updates, source_db=""
                ))
                
    return proposals