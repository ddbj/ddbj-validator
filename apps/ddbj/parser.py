import re
from pathlib import Path
from Bio.SeqFeature import (
    SeqFeature, FeatureLocation, ExactPosition, BeforePosition, AfterPosition,
    CompoundLocation, BetweenPosition, OneOfPosition, WithinPosition
)
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq

from apps.ddbj.location_parser import (
    LocationParseError, LocationRangeError, LocationPartialDescriptorError,
    _parse_location_string, _parse_single_location, _parse_position,
)


def _parse_error(ann_path, rule, message, *, entry, level="error",
                 target=None, feature_type=None, line_number=None, is_cleanup=False):
    """
    パースエラー dict を共通フォーマットで構築する（file / full_path / category の定型を集約）。
    任意フィールド（target / feature_type / line_number / is_cleanup）は指定時のみ付与する。
    """
    err = {"level": level, "rule": rule}
    if is_cleanup:
        err["is_cleanup"] = True
    if target is not None:
        err["target"] = target
    err["entry"] = entry
    if feature_type is not None:
        err["feature_type"] = feature_type
    if line_number is not None:
        err["line_number"] = line_number
    err["message"] = message
    err["file"] = Path(ann_path).name
    err["full_path"] = str(ann_path)
    err["category"] = "annotation"
    return err


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
    _validate_locations_post_parse(records, parse_errors, ann_path, features_dict)

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


def _split_annotation_columns(clean_line, line_no, current_entry_id,
                              current_metadata_feature, current_biological_feature,
                              qualifiers_dict, ann_path, parse_errors):
    """1 行を列分割・検証し (entry, feat_type, loc_str, qualifier, value) を返す。

    列数が不正な場合は parse_errors に記録して None を返す（呼び出し側で continue）。
    qualifier の値欠落（ANN0190 / ANN2645）もここで検出する。
    """
    cols = clean_line.split("\t")

    if len(cols) not in (3, 4, 5):
        parse_errors.append(_parse_error(
            ann_path, "ANN0140",
            f"Invalid column count (Expected 3, 4 or 5, Found {len(cols)}).",
            entry=current_entry_id or "UNKNOWN"))
        return None

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
        parse_errors.append(_parse_error(
            ann_path, "ANN0190",
            "A qualifier name is missing for the provided value column.",
            entry=current_entry_id or entry or "UNKNOWN", target="file/format", line_number=line_no))

    if qualifier:
        q_def = qualifiers_dict.get(qualifier) or {}
        is_value_less = (q_def.get("field_type") == "value-less")

        if not is_value_less and not value:
            current_f_type = feat_type
            if not current_f_type:
                target_feat = current_metadata_feature or current_biological_feature
                current_f_type = target_feat.type if target_feat else "UNKNOWN"

            parse_errors.append(_parse_error(
                ann_path, "ANN2645",
                f"Missing value for the qualifier '{qualifier}'.",
                entry=current_entry_id or entry or "UNKNOWN", target="qualifier",
                feature_type=current_f_type, line_number=line_no))

    return entry, feat_type, loc_str, qualifier, value


def _resolve_feature_location(loc_str, feat_type, seq_len, line_no, err_entry, ann_path, parse_errors):
    """location 文字列を SeqFeature の location に変換する。

    失敗時は対応する ANN ルールを parse_errors に記録し、None を返す。
    """
    location = None
    try:
        parsable_loc_str = loc_str
        if seq_len > 0 and re.search(r'\bE\b', loc_str, re.IGNORECASE):
            parsable_loc_str = re.sub(r'\bE\b', str(seq_len), loc_str, flags=re.IGNORECASE)

        if seq_len == 0 and re.search(r'\bE\b', loc_str, re.IGNORECASE):
            parse_errors.append(_parse_error(
                ann_path, "ANN2020",
                f"Invalid location. The corresponding sequence is missing in FASTA. (Found: '{loc_str}')",
                entry=err_entry, target="location",
                feature_type=feat_type, line_number=line_no))
        else:
            location = _parse_location_string(parsable_loc_str, seq_length=seq_len)

    except LocationPartialDescriptorError as e:
        parse_errors.append(_parse_error(
            ann_path, "ANN2050", str(e),
            entry=err_entry, target="location",
            feature_type=feat_type, line_number=line_no))
    except LocationParseError as e:
        specific_msg = str(e).strip()
        full_msg = f"Invalid location. {specific_msg}" if specific_msg else "Invalid location format."
        parse_errors.append(_parse_error(
            ann_path, "ANN2020", f"{full_msg} (Found: '{loc_str}')",
            entry=err_entry, target="location",
            feature_type=feat_type, line_number=line_no))
    except Exception:
        parse_errors.append(_parse_error(
            ann_path, "ANN2020", f"Invalid location format. (Found: '{loc_str}')",
            entry=err_entry, target="location",
            feature_type=feat_type, line_number=line_no))
    return location


def _register_new_feature(records, current_entry_id, feat_type, location, original_loc_str,
                          line_no, qualifier, value, METADATA_FIELDS, current_biological_feature):
    """新しいフィーチャーを生成してレコードに登録する。

    METADATA フィールドか生物学的フィーチャーかで現在の文脈を切り替え、
    更新後の (current_metadata_feature, current_biological_feature) を返す。
    """
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
        return current_metadata_feature, current_biological_feature

    current_biological_feature = new_feature
    current_metadata_feature = None
    if qualifier:
        current_biological_feature.qualifiers[qualifier] = [value]
        if qualifier == "locus_tag" and current_entry_id in records:
            tag_val = value.strip()
            if tag_val not in records[current_entry_id].features_by_locus_tag:
                records[current_entry_id].features_by_locus_tag[tag_val] = []
            records[current_entry_id].features_by_locus_tag[tag_val].append(new_feature)
    return current_metadata_feature, current_biological_feature


def _attach_qualifier_to_feature(records, current_entry_id, current_metadata_feature,
                                 current_biological_feature, qualifier, value, line_no,
                                 entry, ann_path, parse_errors):
    """qualifier のみの行を、直前のフィーチャーに追加する。

    対象フィーチャーが無ければ ANN2650 を parse_errors に記録する。
    """
    target_feature = current_metadata_feature or current_biological_feature

    if not target_feature:
        parse_errors.append(_parse_error(
            ann_path, "ANN2650",
            f"Missing feature for the qualifier. (cannot attach qualifier '{qualifier}')",
            entry=current_entry_id or entry or "UNKNOWN", target="file",
            feature_type="UNKNOWN", line_number=line_no))
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


def _parse_annotation_tasks(tasks, records, parse_errors, qualifiers_dict, METADATA_FIELDS, ann_path):
    """アノテーションの各行をパースして SeqFeature を構築し、レコードに紐付ける"""
    current_entry_id = None
    current_biological_feature = None
    current_metadata_feature = None

    for line_no, clean_line in tasks:
        parsed = _split_annotation_columns(
            clean_line, line_no, current_entry_id,
            current_metadata_feature, current_biological_feature,
            qualifiers_dict, ann_path, parse_errors)
        if parsed is None:
            continue
        entry, feat_type, loc_str, qualifier, value = parsed

        if loc_str.lower() == "location" or feat_type.lower() == "feature":
            continue

        original_loc_str = loc_str

        if loc_str and re.search(r'\s', loc_str):
            loc_str = re.sub(r'\s+', '', loc_str)
            parse_errors.append(_parse_error(
                ann_path, "ANN2020",
                f"Removed whitespace(s) from location string. (Found: '{original_loc_str}')",
                entry=current_entry_id or entry or "UNKNOWN", level="warning", is_cleanup=True,
                target="location", feature_type=feat_type or "UNKNOWN", line_number=line_no))

        if entry and entry != current_entry_id:
            current_entry_id = entry
            current_biological_feature = None
            current_metadata_feature = None

        if current_entry_id and current_entry_id not in records:
            record = SeqRecord(Seq(""), id=current_entry_id)
            record.features_by_type = {}
            record.features_by_locus_tag = {}
            records[current_entry_id] = record

        err_entry = current_entry_id or entry or "UNKNOWN"

        # --- 新しいフィーチャーの処理 ---
        if feat_type:
            seq_len = len(records[current_entry_id].seq) if current_entry_id in records else 0
            location = _resolve_feature_location(
                loc_str, feat_type, seq_len, line_no, err_entry, ann_path, parse_errors)

            current_metadata_feature, current_biological_feature = _register_new_feature(
                records, current_entry_id, feat_type, location, original_loc_str,
                line_no, qualifier, value, METADATA_FIELDS, current_biological_feature)

        # --- Qualifier の追加 ---
        elif qualifier:
            _attach_qualifier_to_feature(
                records, current_entry_id, current_metadata_feature, current_biological_feature,
                qualifier, value, line_no, entry, ann_path, parse_errors)


def _feature_allows_qualifier(features_dict, feature_type, qualifier):
    """
    definitions.json の feature 定義上、指定の feature_type にその qualifier を
    記載できるかどうかを返す。
    判定対象は mandatory_qualifiers（dict）と optional_qualifiers（list）のみとする。
    """
    f_def = features_dict.get(feature_type)
    if not f_def:
        return False

    # mandatory_qualifiers は dict（キーが qualifier 名）
    if qualifier in f_def.get("mandatory_qualifiers", {}):
        return True
    # optional_qualifiers は qualifier 名の list
    if qualifier in f_def.get("optional_qualifiers", []):
        return True
    return False


def _validate_locations_post_parse(records, parse_errors, ann_path, features_dict=None):
    """パース完了後のオブジェクトに対する遅延ロケーション検証 (順序、スリッページ等)"""
    features_dict = features_dict or {}
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
                                parse_errors.append(_parse_error(
                                    ann_path, "ANN2022",
                                    f"Large gap ({diff}, usually -1, 0, 2, 3 bases) for ribosomal_slippage.",
                                    entry=seq_id, level="warning", target="location",
                                    feature_type=feature.type, line_number=getattr(feature, 'line_number', 0)))
                            elif diff < -1:
                                parse_errors.append(_parse_error(
                                    ann_path, "ANN2022",
                                    f"Unusual overlap ({diff}, usually -1, 0, 2, 3 bases) for ribosomal_slippage.",
                                    entry=seq_id, level="warning", target="location",
                                    feature_type=feature.type, line_number=getattr(feature, 'line_number', 0)))
                                
                elif hasattr(feature.location, "_out_of_order_error"):
                    msg = f"Invalid location. {feature.location._out_of_order_error}"
                    # ribosomal_slippage を記載できる feature（definitions.json 上で許可）の場合のみ、
                    # スリッページの案内文言を付ける。
                    # 現状は CDS のみだが、将来 JSON 側で許可 feature が増えれば自動的に追従する。
                    # （例: mat_peptide のような記載不可 feature には付けない）
                    if getattr(feature.location, "_suggest_slippage", False) and \
                            _feature_allows_qualifier(features_dict, feature.type, "ribosomal_slippage"):
                        msg += " If this is a ribosomal slippage, please add a '/ribosomal_slippage' qualifier."
                    
                    parse_errors.append(_parse_error(
                        ann_path, "ANN2020",
                        f"{msg} (Found: '{getattr(feature, 'original_location', '')}')",
                        entry=seq_id, target="location",
                        feature_type=feature.type, line_number=getattr(feature, 'line_number', 0)))
                    
            if hasattr(feature.location, "_mixed_strands"):
                exception_quals = ["artificial_location", "trans_splicing", "circular_RNA"]
                if not any(q in feature.qualifiers for q in exception_quals):
                    parse_errors.append(_parse_error(
                        ann_path, "ANN2020",
                        f"Mixed strands in join() is invalid unless 'trans_splicing' (or similar exceptions) is present. (Found: '{getattr(feature, 'original_location', '')}')",
                        entry=seq_id, level="warning", target="location",
                        feature_type=feature.type, line_number=getattr(feature, 'line_number', 0)))


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
