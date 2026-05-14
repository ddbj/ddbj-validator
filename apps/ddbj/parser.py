import re
from pathlib import Path
from Bio.SeqFeature import (
    SeqFeature, FeatureLocation, ExactPosition, BeforePosition, AfterPosition,
    CompoundLocation, BetweenPosition, OneOfPosition, WithinPosition
)
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq

class LocationParseError(Exception):
    pass

class LocationRangeError(LocationParseError):
    pass

class LocationPartialDescriptorError(LocationParseError):
    pass

def parse_ddbj_submission(fasta_content, ann_path, ann_lines, ddbj_dict=None):
    """
    FASTAファイルとアノテーション(ANN)ファイルを解析し、SeqRecordオブジェクトのリストを構築する。
    """
    records = {}
    parse_errors = []
    
    ddbj_dict = ddbj_dict or {}
    features_dict = ddbj_dict.get("features", {})
    qualifiers_dict = ddbj_dict.get("qualifiers", {})
    
    # ---------------------------------------------------------
    # 0. メタデータフィールドの抽出
    # ---------------------------------------------------------
    METADATA_FIELDS = set()
    if features_dict:
        for f_name, f_def in features_dict.items():
            if f_def.get("feature_type") == "metadata_field":
                METADATA_FIELDS.add(f_name.upper())

    # ---------------------------------------------------------
    # 1. FASTAのパース
    # ---------------------------------------------------------
    _parse_fasta_blocks(fasta_content, records, parse_errors, ann_path)

    # ---------------------------------------------------------
    # 2. COMMONテンプレートの展開 (遅延パース用タスクの生成)
    # ---------------------------------------------------------
    tasks = _expand_common_template(ann_lines, records, METADATA_FIELDS)

    # ---------------------------------------------------------
    # 3. アノテーションのパース処理 (メインループ)
    # ---------------------------------------------------------
    _parse_annotation_tasks(tasks, records, parse_errors, qualifiers_dict, METADATA_FIELDS, ann_path)

    # ---------------------------------------------------------
    # 4. パース後のロケーション後処理 (ANN2020の遅延チェックなど)
    # ---------------------------------------------------------
    _validate_locations_post_parse(records, parse_errors, ann_path)

    # ---------------------------------------------------------
    # 5. 空エントリの削除
    # ---------------------------------------------------------
    _remove_empty_entries(records)

    return records, parse_errors


# =========================================================
# フェーズ分割された内部ヘルパー関数群
# =========================================================
def _parse_fasta_blocks(fasta_content, records, parse_errors, ann_path):
    """FASTA文字列をパースして SeqRecord を初期化する"""
    if not fasta_content:
        return
        
    data = fasta_content
    if data.startswith('>'):
        data = data[1:]

    for block in data.split('\n>'):
        if not block or block.isspace():
            continue
            
        idx = block.find('\n')
        if idx == -1:
            header = block
            raw_seq = ""
        else:
            header = block[:idx]
            raw_seq = block[idx+1:].lower()

        # ヘッダーから seq_id を抽出 (Auto-cleanup メッセージの entry に使用するため)
        seq_id = header.split(None, 1)[0] if header else "UNKNOWN"
        clean_seq = ""

        if raw_seq:
            # 末尾の正しい '//' を安全に除去（改行や空白が連続していても対応）
            raw_seq = re.sub(r'//\s*$', '', raw_seq)

            # 1. まず、正常なフォーマットである「改行」だけを削除する（ここは警告の対象外）
            seq_no_newlines = re.sub(r'[\r\n]+', '', raw_seq)

            # 2. 不正な文字（タブ、スペース等の空白、ハイフン、途中の //）が含まれているかチェック
            cleanup_pattern = re.compile(r'[ \t\f\v　]|-|//')
            
            if cleanup_pattern.search(seq_no_newlines):
                # 不正な文字が含まれていた場合、それらを削除
                clean_seq = cleanup_pattern.sub('', seq_no_newlines)
                
                # Auto-cleanup の警告（SEQ0085）を parse_errors に追加
                fasta_filename = Path(ann_path).with_suffix('.fasta').name if ann_path else "Sequence File"
                parse_errors.append({
                    "level": "warning",
                    "rule": "SEQ0085",
                    "target": "file/format",
                    "entry": seq_id,
                    "message": "[Auto-cleanup] Invalid characters (spaces, tabs and hyphens) or improperly placed terminators ('//') were automatically removed from the sequence.",
                    "is_cleanup": True,
                    "file": fasta_filename,
                    "category": "sequence"
                })
            else:
                clean_seq = seq_no_newlines

        try:
            # 完全に綺麗な文字列（clean_seq）を Seq オブジェクトに渡す
            record = SeqRecord(Seq(clean_seq), id=seq_id, description=header.strip())
        except UnicodeEncodeError:
            fasta_filename = Path(ann_path).with_suffix('.fasta').name if ann_path else "Sequence File"
            parse_errors.append({
                "level": "FATAL",
                "rule": "ANN0040",
                "target": "sequence",
                "entry": seq_id,
                "message": f"Non-ASCII characters detected in FASTA sequence. Cannot parse the sequence. (File: {fasta_filename})",
                "file": fasta_filename,
                "category": "sequence"
            })
            continue  
        
        record.features_by_type = {}
        record.features_by_locus_tag = {}
        records[seq_id] = record


def _expand_common_template(ann_lines, records, METADATA_FIELDS):
    """COMMONエントリの生物学的フィーチャーを全レコードに展開し、解析タスクのリストを返す"""
    has_common = False
    has_source = False
    has_e_location = False
    
    clean_ann_lines_with_no = []
    for line_no, line in enumerate(ann_lines, 1):
        clean_line = line.rstrip("\r\n")
        if not clean_line or clean_line.isspace():
            continue
        clean_ann_lines_with_no.append((line_no, clean_line))
        
        cols = clean_line.split("\t")
        entry = cols[0].strip() if len(cols) > 0 else ""
        if entry == "COMMON":
            has_common = True
                
        feat_type = cols[1].strip() if len(cols) > 1 else ""
        loc_str = cols[2].strip() if len(cols) > 2 else ""
        
        if feat_type == "source":
            has_source = True
        if loc_str and re.search(r'\bE\b', loc_str, re.IGNORECASE):
            has_e_location = True

    is_template_mode = has_common and has_source and has_e_location
    tasks = []
    
    if is_template_mode:
        common_metadata_tasks = []
        common_bio_feature_tasks = []
        other_tasks = []
        
        current_is_metadata = True 
        current_entry = None
        
        for orig_line_no, clean_line in clean_ann_lines_with_no:
            cols = clean_line.split("\t")
            entry = cols[0].strip() if len(cols) > 0 else ""
            if entry:
                current_entry = entry
                
            feat_type = cols[1].strip() if len(cols) > 1 else ""
            
            if feat_type and feat_type.lower() != "feature":
                feat_type_upper = feat_type.upper()
                if feat_type_upper in METADATA_FIELDS:
                    current_is_metadata = True
                else:
                    current_is_metadata = False
                    
            if current_entry == "COMMON":
                if current_is_metadata:
                    common_metadata_tasks.append((orig_line_no, clean_line))
                else:
                    common_bio_feature_tasks.append((orig_line_no, clean_line))
            else:
                other_tasks.append((orig_line_no, clean_line))
                
        tasks.extend(common_metadata_tasks)
        
        for seq_id, record in records.items():
            if seq_id == "COMMON": continue
            
            for orig_line_no, clean_line in common_bio_feature_tasks:
                cols = clean_line.split("\t")
                if len(cols) > 0:
                    entry_col = cols[0].strip()
                    feat_type_col = cols[1].strip() if len(cols) > 1 else ""
                    
                    if entry_col == "COMMON" or (not entry_col and feat_type_col and feat_type_col.lower() != "feature"):
                        cols[0] = seq_id
                                    
                tasks.append((orig_line_no, "\t".join(cols)))
                
        tasks.extend(other_tasks)
    else:
        tasks = clean_ann_lines_with_no

    return tasks


def _parse_annotation_tasks(tasks, records, parse_errors, qualifiers_dict, METADATA_FIELDS, ann_path):
    """アノテーションの各行をパースして SeqFeature を構築し、レコードに紐付ける"""
    current_entry_id = None
    current_biological_feature = None
    current_metadata_feature = None    

    for line_no, clean_line in tasks:
        cols = clean_line.split("\t")
        
        if len(cols) not in (3, 4, 5):
            parse_errors.append({
                "level": "error", "rule": "ANN0140",
                "entry": current_entry_id or "UNKNOWN",
                "message": f"Invalid column count (Expected 3, 4 or 5, Found {len(cols)}).",
                "file": Path(ann_path).name,
                "full_path": str(ann_path), "category": "annotation"
            })
            continue
                        
        cols = [c.strip() for c in cols]
        
        if len(cols) == 3:
            entry, feat_type, loc_str = cols
            qualifier = ""
            value = ""
        elif len(cols) == 4:
            entry, feat_type, loc_str, qualifier = cols
            value = ""
        else:
            entry, feat_type, loc_str, qualifier, value = cols
            
        if not qualifier and value:
            parse_errors.append({
                "level": "error", "rule": "ANN0190", "target": "file/format",
                "entry": current_entry_id or entry or "UNKNOWN", "line_number": line_no,
                "message": "A qualifier name is missing for the provided value column.",
                "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
            })

        if qualifier:
            q_def = qualifiers_dict.get(qualifier) or {}
            is_value_less = (q_def.get("field_type") == "value-less")
            
            if not is_value_less and not value:
                current_f_type = feat_type
                if not current_f_type:
                    target_feat = current_metadata_feature or current_biological_feature
                    current_f_type = target_feat.type if target_feat else "UNKNOWN"
                    
                parse_errors.append({
                    "level": "error", "rule": "ANN2645", "target": "qualifier",
                    "entry": current_entry_id or entry or "UNKNOWN", 
                    "feature_type": current_f_type,
                    "line_number": line_no,
                    "message": f"Missing value for the qualifier '{qualifier}'.",
                    "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                })
                                            
        if loc_str.lower() == "location" or feat_type.lower() == "feature":
            continue

        original_loc_str = loc_str

        if loc_str and re.search(r'\s', loc_str):
            loc_str = re.sub(r'\s+', '', loc_str)
            parse_errors.append({
                "level": "warning",
                "is_cleanup": True,
                "rule": "ANN2020",
                "target": "location",
                "entry": current_entry_id or entry or "UNKNOWN",
                "feature_type": feat_type or "UNKNOWN",
                "line_number": line_no,
                "message": f"Removed whitespace(s) from location string. (Found: '{original_loc_str}')",
                "file": Path(ann_path).name,
                "full_path": str(ann_path),
                "category": "annotation"
            })
                        
        if entry and entry != current_entry_id:
            current_entry_id = entry
            current_biological_feature = None
            current_metadata_feature = None

        if current_entry_id and current_entry_id not in records:
            record = SeqRecord(Seq(""), id=current_entry_id)
            record.features_by_type = {}
            record.features_by_locus_tag = {}
            records[current_entry_id] = record
        
        # --- 新しいフィーチャーの処理 ---
        if feat_type:
            seq_len = len(records[current_entry_id].seq) if current_entry_id in records else 0
            location = None
            
            try:
                parsable_loc_str = loc_str
                if seq_len > 0 and re.search(r'\bE\b', loc_str, re.IGNORECASE):
                    parsable_loc_str = re.sub(r'\bE\b', str(seq_len), loc_str, flags=re.IGNORECASE)

                if seq_len == 0 and re.search(r'\bE\b', loc_str, re.IGNORECASE):
                    parse_errors.append({
                        "level": "error", "rule": "ANN2020", "target": "location",
                        "entry": current_entry_id or entry or "UNKNOWN",
                        "feature_type": feat_type, "line_number": line_no,
                        "message": f"Invalid location. The corresponding sequence is missing in FASTA. (Found: '{loc_str}')",
                        "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                    })
                else:
                    location = _parse_location_string(parsable_loc_str, seq_length=seq_len)                
                                
            except LocationPartialDescriptorError as e:
                parse_errors.append({
                    "level": "error", "rule": "ANN2050", "target": "location",
                    "entry": current_entry_id or entry or "UNKNOWN",
                    "feature_type": feat_type, "line_number": line_no,
                    "message": str(e),
                    "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                })
            except LocationParseError as e:
                specific_msg = str(e).strip()
                full_msg = f"Invalid location. {specific_msg}" if specific_msg else "Invalid location format."
                parse_errors.append({
                    "level": "error", "rule": "ANN2020", "target": "location",
                    "entry": current_entry_id or entry or "UNKNOWN",
                    "feature_type": feat_type, "line_number": line_no,
                    "message": f"{full_msg} (Found: '{loc_str}')",
                    "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                })
            except Exception:
                parse_errors.append({
                    "level": "error", "rule": "ANN2020", "target": "location",
                    "entry": current_entry_id or entry or "UNKNOWN",
                    "feature_type": feat_type, "line_number": line_no,
                    "message": f"Invalid location format. (Found: '{loc_str}')",
                    "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                })
                                                                
            new_feature = SeqFeature(location=location, type=feat_type, qualifiers={})            
            new_feature.original_location = original_loc_str
            new_feature.line_number = line_no
            new_feature.has_qualifier_on_first_line = bool(qualifier.strip())

            if current_entry_id in records:
                target_record = records[current_entry_id]
                target_record.features.append(new_feature)
                
                if feat_type not in target_record.features_by_type:
                    target_record.features_by_type[feat_type] = []
                target_record.features_by_type[feat_type].append(new_feature)

            feat_type_upper = feat_type.upper()
            
            if feat_type_upper in METADATA_FIELDS:
                current_metadata_feature = new_feature
                if qualifier:
                    current_metadata_feature.qualifiers[qualifier] = [value]
            else:
                current_biological_feature = new_feature
                current_metadata_feature = None
                if qualifier:
                    current_biological_feature.qualifiers[qualifier] = [value]
                    if qualifier == "locus_tag" and current_entry_id in records:
                        tag_val = value.strip()
                        if tag_val not in records[current_entry_id].features_by_locus_tag:
                            records[current_entry_id].features_by_locus_tag[tag_val] = []
                        records[current_entry_id].features_by_locus_tag[tag_val].append(new_feature)

        # --- Qualifierの追加 ---
        elif qualifier:
            target_feature = current_metadata_feature or current_biological_feature
      
            if not target_feature:
                parse_errors.append({
                    "level": "error", "rule": "ANN2650", "target": "file",
                    "entry": current_entry_id or entry or "UNKNOWN",
                    "feature_type": "UNKNOWN",
                    "line_number": line_no,
                    "message": f"Missing feature for the qualifier. (cannot attach qualifier '{qualifier}')",
                    "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                })
            else:
                if qualifier not in target_feature.qualifiers:
                    target_feature.qualifiers[qualifier] = []
                target_feature.qualifiers[qualifier].append(value)
                
                if qualifier == "locus_tag" and current_entry_id in records:
                    tag_val = value.strip()
                    if tag_val not in records[current_entry_id].features_by_locus_tag:
                        records[current_entry_id].features_by_locus_tag[tag_val] = []
                    if target_feature not in records[current_entry_id].features_by_locus_tag[tag_val]:
                        records[current_entry_id].features_by_locus_tag[tag_val].append(target_feature)


def _validate_locations_post_parse(records, parse_errors, ann_path):
    """パース完了後のオブジェクトに対する遅延ロケーション検証 (順序、スリッページ等)"""
    for seq_id, record in records.items():
        for feature in record.features:
            
            if hasattr(feature.location, "_out_of_order_error") or hasattr(feature.location, "_join_diffs"):
                exception_quals = ["artificial_location", "trans_splicing", "circular_RNA"]
                
                if any(q in feature.qualifiers for q in exception_quals):
                    pass
                elif "ribosomal_slippage" in feature.qualifiers:
                    if hasattr(feature.location, "_join_diffs"):
                        for diff in feature.location._join_diffs:
                            if diff in (0, 1, 2, -1, 3):
                                pass
                            elif diff > 3:
                                parse_errors.append({
                                    "level": "warning", "rule": "ANN2022", "target": "location",
                                    "entry": seq_id,
                                    "feature_type": feature.type, "line_number": getattr(feature, 'line_number', 0),
                                    "message": f"Large gap ({diff}, usually -1, 0, 2, 3 bases) for ribosomal_slippage.",
                                    "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                                })
                            elif diff < -1:
                                parse_errors.append({
                                    "level": "warning", "rule": "ANN2022", "target": "location",
                                    "entry": seq_id,
                                    "feature_type": feature.type, "line_number": getattr(feature, 'line_number', 0),
                                    "message": f"Unusual overlap ({diff}, usually -1, 0, 2, 3 bases) for ribosomal_slippage.",
                                    "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                                })
                                
                elif hasattr(feature.location, "_out_of_order_error"):
                    msg = f"Invalid location. {feature.location._out_of_order_error}"
                    if getattr(feature.location, "_suggest_slippage", False):
                        msg += " If this is a ribosomal slippage, please add a '/ribosomal_slippage' qualifier."
                    
                    parse_errors.append({
                        "level": "error", "rule": "ANN2020", "target": "location",
                        "entry": seq_id,
                        "feature_type": feature.type, "line_number": getattr(feature, 'line_number', 0),
                        "message": f"{msg} (Found: '{getattr(feature, 'original_location', '')}')",
                        "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                    })
                    
            if hasattr(feature.location, "_mixed_strands"):
                exception_quals = ["artificial_location", "trans_splicing", "circular_RNA"]
                if not any(q in feature.qualifiers for q in exception_quals):
                    parse_errors.append({
                        "level": "warning", "rule": "ANN2020", "target": "location",
                        "entry": seq_id,
                        "feature_type": feature.type, "line_number": getattr(feature, 'line_number', 0),
                        "message": f"Mixed strands in join() is invalid unless 'trans_splicing' (or similar exceptions) is present. (Found: '{getattr(feature, 'original_location', '')}')",
                        "file": Path(ann_path).name, "full_path": str(ann_path), "category": "annotation"
                    })


def _remove_empty_entries(records):
    """FASTAにのみ存在し、アノテーション情報が全く無いエントリを安全に削除する"""
    empty_entries = [
        seq_id for seq_id, record in records.items()
        if seq_id != "COMMON" and len(record.features) == 0
    ]
    for seq_id in empty_entries:
        del records[seq_id]


# =========================================================
# Location パース用ヘルパー関数 (変更なし)
# =========================================================
def _parse_location_string(loc_str, seq_length=0, default_strand=1):
    if not loc_str: return None
    
    # 外部参照アクセッション（例: AB000001.1:）の数値を誤検知しないよう一時的に除外
    loc_no_acc = re.sub(r'[a-zA-Z0-9_.]+:', '', loc_str)
    
    match = re.search(r'\b(0\d*)\b', loc_no_acc)
    if match:
        matched_val = match.group(1)
        if matched_val == "0":
            raise LocationParseError("Position coordinate cannot be '0' (coordinates must be 1-based).")
        else:
            raise LocationParseError(f"Zero-padded position numbers are not allowed. (Found: '{matched_val}')")

    if "order(" in loc_str:
        raise LocationParseError("The 'order' operator is not supported for DDBJ submissions.")
                
    if loc_str.count("join(") > 1:
        raise LocationParseError("Nested 'join' is not allowed.")
        
    strand = default_strand
    
    if loc_str.startswith("complement(") and loc_str.endswith(")"):
        strand = -1
        loc_str = loc_str[11:-1]
        
    if loc_str.startswith("join(") and loc_str.endswith(")"):
        inner_loc = loc_str[5:-1] 

        parts = [p.strip() for p in inner_loc.split(",")]
        if len(parts) == 1:
            raise LocationParseError("join() with a single element is invalid.")

        for i, part in enumerate(parts):
            if i > 0 and '<' in part:
                raise LocationPartialDescriptorError("Invalid location. Partial operator '<' must only appear at the start of the entire location.")
            if i < len(parts) - 1 and '>' in part:
                raise LocationPartialDescriptorError("Invalid location. Partial operator '>' must only appear at the end of the entire location.")

        explicit_complements = ["complement(" in p for p in parts]
        
        if all(explicit_complements):
            raise LocationParseError("Found complement() inside join(). Use complement(join(...)) instead.")

        locations = []
        for part in parts:
            parsed_loc = _parse_location_string(part, seq_length=seq_length, default_strand=strand)
            locations.append(parsed_loc)
            
        out_of_order_err = None
        suggest_slippage = False
        join_diffs = [] 
        
        local_locations = [loc for loc in locations if getattr(loc, 'ref', None) is None]
        
        seen_intervals = set()
        for loc in local_locations:
            interval = (int(loc.start), int(loc.end), loc.strand)
            if interval in seen_intervals:
                out_of_order_err = f"Duplicated location interval found in join: {int(loc.start) + 1}..{int(loc.end)}"
                break
            seen_intervals.add(interval)

        if not out_of_order_err:
            for i in range(len(local_locations) - 1):
                prev_loc = local_locations[i]
                next_loc = local_locations[i+1]
                
                B_val = int(prev_loc.end)
                C_val = int(next_loc.start) + 1
                
                user_diff = C_val - B_val
                join_diffs.append(user_diff)
                
                if B_val >= C_val:
                    if strand == 1 and seq_length > 0 and B_val == seq_length and C_val == 1:
                        pass
                    else:
                        if user_diff in (0, -1):
                            out_of_order_err = "Overlapping location intervals."
                            suggest_slippage = True
                        else:
                            is_spanning_origin = (seq_length > 0 and B_val > seq_length * 0.5 and C_val < seq_length * 0.5) or (B_val - C_val > 1000)
                            if is_spanning_origin:
                                out_of_order_err = f"The location interval appears to span the origin of a circular sequence improperly. Consider shifting the starting coordinate of the sequence. (Found end {B_val} >= next start {C_val})"
                            else:
                                out_of_order_err = f"Joined segments must be in increasing order. (Found end {B_val} >= next start {C_val})"
                        break
                        
        if strand == -1:
            locations.reverse()
            
        comp_loc = CompoundLocation(locations)
        
        comp_loc._join_diffs = join_diffs
                
        if out_of_order_err:
            comp_loc._out_of_order_error = out_of_order_err
            if suggest_slippage:
                comp_loc._suggest_slippage = True
            
        if any(explicit_complements) and not all(explicit_complements):
            comp_loc._mixed_strands = True
            
        return comp_loc
        
    if "," in loc_str:
        raise LocationParseError(f"Location contains comma but lacks 'join': {loc_str}")
        
    return _parse_single_location(loc_str, seq_length=seq_length, default_strand=strand)
    

def _parse_position(pos_str):
    pos_str = pos_str.strip()
    if pos_str.startswith('<'):
        return BeforePosition(int(pos_str[1:]) - 1)
    elif pos_str.startswith('>'):
        return AfterPosition(int(pos_str[1:]) - 1)
    else:
        return ExactPosition(int(pos_str) - 1)


def _parse_single_location(loc_str, seq_length=None, default_strand=1):
    loc_str = loc_str.strip()
    ref_seq = None
    
    if ':' in loc_str:
        parts = loc_str.split(':', 1)
        ref_seq = parts[0]
        
        accession_pattern = re.compile(
            r'^([A-Z]{1}\d{5}|[A-Z]{2}\d{6}|[A-Z]{2}\d{8}|[A-Z]{4}\d{8,10}|[A-Z]{6}\d{9,11})\.\d+$', 
            re.IGNORECASE
        )
        if not accession_pattern.match(ref_seq):
            raise LocationParseError(f"Invalid remote entry reference format: '{ref_seq}'. Accession with version (e.g., AB000001.1) is required.")
            
        loc_str = parts[1]
        
    for part in loc_str.split('..'):
        part_clean = part.replace('^', '').strip()
        if '<' in part_clean[1:] or '>' in part_clean[1:]:
            raise LocationPartialDescriptorError(f"Invalid location. Partial operators '<' or '>' must only appear at the start or end. (operator placed after position numbers in '{loc_str}')")

    try:
        if '^' in loc_str:
            start_str, end_str = loc_str.split('^')
            s_val = int(start_str)
            e_val = int(end_str)
            
            is_adjacent = (e_val - s_val == 1)
            is_circular = (seq_length and s_val == seq_length and e_val == 1)
            
            if not (is_adjacent or is_circular):
                raise LocationParseError(f"Invalid caret notation '{loc_str}'. Must be n^n+1, or E^1 for circular molecules.")
                
            pos = s_val
            return FeatureLocation(ExactPosition(pos), ExactPosition(pos), strand=default_strand, ref=ref_seq)

        if '...' in loc_str:
            raise LocationParseError("Three or more consecutive dots (e.g., '1...120') are not allowed. Use '..' for ranges.")
                                                
        if '..' not in loc_str and '.' in loc_str:
            raise LocationParseError("Unknown location description with single dot (e.g., '10.12') is not supported.")

        if '..' not in loc_str:
            val = int(loc_str.replace('<', '').replace('>', ''))
            start_pos = _parse_position(loc_str)
            
            if loc_str.startswith('<'):
                end_pos = ExactPosition(val)
            elif loc_str.startswith('>'):
                end_pos = AfterPosition(val)
            else:
                end_pos = ExactPosition(val)
                
            return FeatureLocation(start_pos, end_pos, strand=default_strand, ref=ref_seq)
        
        start_str, end_str = loc_str.split('..')
        
        if start_str.startswith('>'):
            raise LocationParseError("Partial operator '>' cannot be used at the start position of a range.")
        if end_str.startswith('<'):
            raise LocationParseError("Partial operator '<' cannot be used at the end position of a range.")

        start_pos = _parse_position(start_str)
        
        end_val = int(end_str.replace('<', '').replace('>', ''))
        if end_str.startswith('>'):
            end_pos = AfterPosition(end_val)            
        elif end_str.startswith('<'):
            end_pos = BeforePosition(end_val)
        else:
            end_pos = ExactPosition(end_val)
        
        return FeatureLocation(start_pos, end_pos, strand=default_strand, ref=ref_seq)
        
    except ValueError as e:
        if "greater than or equal to start location" in str(e):
            raise LocationRangeError(f"Invalid start and end positions: {e}")
        raise LocationParseError(f"Invalid location coordinates or syntax: {e}")
    except Exception as e:
        if isinstance(e, LocationParseError):
            raise
        raise LocationParseError(f"Failed to parse location: {e}")