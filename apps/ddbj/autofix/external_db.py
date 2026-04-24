import copy
import re
from pathlib import Path
from Bio.SeqRecord import SeqRecord
from Bio.Seq import Seq
from apps.ddbj.utils.features import get_features
from apps.ddbj.db_metadata import get_expected_transl_table

_SAMD_PATTERN = re.compile(r'(SAMD\d+)')

def _extract_samd_from_single_record(record):
    samd_list = []
    for feature in get_features(record, "DBLINK"):
        for vals in feature.qualifiers.values():
            for val in vals:
                match = _SAMD_PATTERN.search(val)
                if match: samd_list.append(match.group(1))
    return samd_list

def propose_qualifiers_updates(records, bs_data, ann_path):
    proposals = []
    skipped_warnings = []
    validation_warnings = []
    
    target_attrs = ["bio_material", "collection_date", "geo_loc_name", "culture_collection",
                    "host", "lat_lon", "sex", "specimen_voucher", "strain", "isolate", "ecotype", 
                    "cultivar", "cell_line"]
    common_samds = []
    if "COMMON" in records:
        common_samds = _extract_samd_from_single_record(records["COMMON"])
    
    for entry_id, record in records.items():
        if entry_id == "COMMON": continue
        entry_samds = _extract_samd_from_single_record(record)
        active_samds = entry_samds if entry_samds else common_samds
        if not active_samds: continue

        valid_samds = [s for s in active_samds if s in bs_data]
        missing_samds = [s for s in active_samds if s not in bs_data]
        
        if missing_samds:
            print(f"[WARN] {entry_id}: BioSample data for {', '.join(missing_samds)} not found in DB.")
        if not valid_samds: continue

        for feature in record.features:
            for attr in target_attrs:
                if attr in feature.qualifiers:
                    ann_val_list = feature.qualifiers[attr]
                    ann_val = ann_val_list[0] if ann_val_list else ""
                    
                    bs_values = set()
                    bs_samd_map = {} 
                    for s in valid_samds:
                        val = bs_data[s].get(attr)
                        if val is not None and str(val).strip() != "":
                            clean_val = str(val).strip()
                            bs_values.add(clean_val)
                            bs_samd_map[clean_val] = s

                    if len(bs_values) == 1:
                        bs_val = bs_values.pop()
                        source_samd = bs_samd_map[bs_val] 
                        
                        if ann_val != bs_val:
                            msg = f"The '{attr}' qualifier value does not match the BioSample attribute value. (ann: '{ann_val}', BioSample: '{bs_val}')"
                            validation_warnings.append({
                                "file": Path(ann_path).name,
                                "full_path": str(ann_path),
                                "entry": entry_id,
                                "rule": "ANN1130",
                                "target": attr,
                                "level": "warning",
                                "message": msg,
                                "feature_type": feature.type,
                                "qualifier": attr,
                                "line_number": getattr(feature, 'line_number', None),
                                "location": getattr(feature, 'original_location', "")
                            })

                            updates = [{
                                "action": "update_qualifier",
                                "entry": entry_id,
                                "feature_type": feature.type,
                                "feature_id": getattr(feature, 'line_number', id(feature)),
                                "qualifier": attr,
                                "old_value": ann_val,
                                "new_value": bs_val
                            }]
                                
                            proposals.append({
                                "ann_path": ann_path,
                                "rule": "ANN1130",
                                "target": attr,
                                "target_level": "qualifier",
                                "old": ann_val, "new": bs_val, "entry": entry_id,
                                "positions": [{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                                "source_db": source_samd, 
                                "updates": updates
                            })
                       
                    elif len(bs_values) > 1:
                        skipped_warnings.append({
                            "ann_path": ann_path, "entry": entry_id, 
                            "attr": attr, "values": bs_values
                        })
                        
        # --- Locus Tag Prefix のチェックと一括提案 ---
        bs_prefixes = set()
        bs_prefix_samd_map = {}
        for s in valid_samds:
            val = bs_data[s].get("locus_tag_prefix")
            if val is not None and str(val).strip() != "":
                clean_val = str(val).strip()
                bs_prefixes.add(clean_val)
                bs_prefix_samd_map[clean_val] = s

        if len(bs_prefixes) == 1:
            bs_prefix = bs_prefixes.pop()
            source_samd = bs_prefix_samd_map[bs_prefix]
            wrong_prefixes = set()

            if hasattr(record, 'features_by_locus_tag') and record.features_by_locus_tag:
                for tag_str, features in record.features_by_locus_tag.items():
                    ann_prefix = tag_str.split("_", 1)[0] if "_" in tag_str else tag_str
                    if ann_prefix and ann_prefix != bs_prefix:
                        wrong_prefixes.add(ann_prefix)
                        
                        for feature in features:
                            msg = f"The 'locus_tag' prefix does not match the BioSample locus_tag_prefix. (ann: '{ann_prefix}', BioSample: '{bs_prefix}')"
                            validation_warnings.append({
                                "file": ann_path,
                                "entry_id": entry_id,
                                "rule": "ANN1130",
                                "target": "locus_tag_prefix",
                                "level": "warning",
                                "message": msg,
                                "feature_type": feature.type,
                                "qualifier": "locus_tag",
                                "line_number": getattr(feature, 'line_number', None),
                                "location": getattr(feature, 'original_location', "")
                            })
            else:
                for feature in record.features:
                    if "locus_tag" in feature.qualifiers:
                        ann_locus_tag = feature.qualifiers["locus_tag"][0]
                        ann_prefix = ann_locus_tag.split("_", 1)[0] if "_" in ann_locus_tag else ann_locus_tag
                        if ann_prefix and ann_prefix != bs_prefix:
                            wrong_prefixes.add(ann_prefix)
                            msg = f"The 'locus_tag' prefix does not match the BioSample locus_tag_prefix. (ann: '{ann_prefix}', BioSample: '{bs_prefix}')"
                            validation_warnings.append({
                                "file": ann_path, "entry_id": entry_id, "rule": "ANN1130",
                                "target": "locus_tag_prefix", "level": "warning", "message": msg,
                                "feature_type": feature.type, "qualifier": "locus_tag",
                                "line_number": getattr(feature, 'line_number', None),
                                "location": getattr(feature, 'original_location', "")
                            })
        
            for wp in wrong_prefixes:
                positions = []
                updates = []
                
                if hasattr(record, 'features_by_locus_tag'):
                    for tag_str, features in record.features_by_locus_tag.items():
                        curr_prefix = tag_str.split("_", 1)[0] if "_" in tag_str else tag_str
                        if curr_prefix == wp:
                            for f in features:
                                positions.append({"entry": entry_id, "feature_id": getattr(f, 'line_number', id(f))})
                                
                                if "_" in tag_str:
                                    _, suffix = tag_str.split("_", 1)
                                    new_tag = f"{bs_prefix}_{suffix}"
                                else:
                                    new_tag = bs_prefix
                                    
                                updates.append({
                                    "action": "update_qualifier",
                                    "entry": entry_id,
                                    "feature_type": f.type,
                                    "feature_id": getattr(f, 'line_number', id(f)),
                                    "qualifier": "locus_tag",
                                    "old_value": tag_str,
                                    "new_value": new_tag
                                })
                else:
                    for f in record.features:
                        if "locus_tag" in f.qualifiers:
                            tags = f.qualifiers["locus_tag"]
                            old_tag = tags[0] if tags else ""
                            curr_prefix = old_tag.split("_", 1)[0] if "_" in old_tag else old_tag
                            
                            if curr_prefix == wp:
                                positions.append({"entry": entry_id, "feature_id": getattr(f, 'line_number', id(f))})
                                
                                if "_" in old_tag:
                                    _, suffix = old_tag.split("_", 1)
                                    new_tag = f"{bs_prefix}_{suffix}"
                                else:
                                    new_tag = bs_prefix
                                    
                                updates.append({
                                    "action": "update_qualifier",
                                    "entry": entry_id,
                                    "feature_type": f.type,
                                    "feature_id": getattr(f, 'line_number', id(f)),
                                    "qualifier": "locus_tag",
                                    "old_value": old_tag,
                                    "new_value": new_tag
                                })

                proposals.append({
                    "ann_path": ann_path, 
                    "rule": "ANN1130", 
                    "target": "locus_tag_prefix",
                    "target_level": "qualifier",
                    "old": wp, "new": bs_prefix, "entry": entry_id,
                    "positions": positions,
                    "source_db": source_samd,
                    "updates": updates
                })
        
        elif len(bs_prefixes) > 1:
            skipped_warnings.append({
                "ann_path": ann_path, "entry": entry_id, 
                "attr": "locus_tag_prefix", "values": bs_prefixes
            })
            
    return proposals, validation_warnings, skipped_warnings
    

def propose_taxonomy_updates(records, tax_data, ann_path):
    proposals = []
    fixable_orgs = {org: data for org, data in tax_data.items() if data["status"] == "fixable"}
    if not fixable_orgs:
        return proposals
        
    for org, data in fixable_orgs.items():
        sci_name = data["scientific_name"]
        tax_id = data.get("tax_id", "unknown")
        match_type = data.get("type", "unknown")
        source_str = f"taxid: {tax_id}, {match_type}"
        
        positions = []
        updates = []
        used_in_records = False
        
        for entry_id, record in records.items():
            for feature in get_features(record, "source"):
                if "organism" in feature.qualifiers:
                    if org in feature.qualifiers["organism"]:
                        used_in_records = True
                        positions.append({"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))})
                        
                        updates.append({
                            "action": "update_qualifier",
                            "entry": entry_id,
                            "feature_type": feature.type,
                            "feature_id": getattr(feature, 'line_number', id(feature)),
                            "qualifier": "organism",
                            "old_value": org,
                            "new_value": sci_name
                        })
                        
        if used_in_records:
            proposals.append({
                "ann_path": ann_path, 
                "rule": "ANN1025",  
                "target": "organism",
                "target_level": "qualifier",
                "old": org, "new": sci_name, "entry": "ALL_ENTRIES",
                "positions": positions,
                "source_db": source_str,
                "updates": updates
            })
            
    return proposals


def propose_transl_table_fixes(records, tax_data, ann_path):
    proposals = []
    common_rec = records.get("COMMON")
    common_sources = get_features(common_rec, "source") if common_rec else []
    
    for entry_id, record in records.items():
        if entry_id == "COMMON": continue
        
        eval_record = SeqRecord(Seq(""), id="dummy")
        record_sources = get_features(record, "source")
        eval_record.features_by_type = {"source": common_sources + record_sources}
        
        table_id = get_expected_transl_table(eval_record, tax_data)
        
        # 0 (不明/組み合わせ不適) の場合は Autofix を提案しない
        if table_id == 0:
            continue
            
        org_name = ""
        organelle = ""
        for feature in eval_record.features_by_type["source"]:
            org_name = feature.qualifiers.get("organism", [""])[0]
            organelle = feature.qualifiers.get("organelle", [""])[0]
            break
                
        sci_name = org_name
        tax_id = "unknown"
        if org_name in tax_data and tax_data[org_name].get("status") in ["valid", "fixable"]:
            sci_name = tax_data[org_name].get("scientific_name", org_name)
            tax_id = tax_data[org_name].get("tax_id", "unknown")
            
        source_parts = []
        if sci_name:
            source_parts.append(sci_name)
        if tax_id != "unknown":
            source_parts.append(f"taxid: {tax_id}")
        if organelle:
            source_parts.append(organelle)
            
        source_db_str = ", ".join(source_parts) if source_parts else "Taxonomy DB"
        
        for feature in get_features(record, "CDS"):
            if "transl_table" not in feature.qualifiers:
                
                # 期待値が 1 (標準表) の場合は、システムのデフォルトで処理されるため Autofix の提案をスキップする
                if table_id == 1:
                    continue

                updates = [{
                    "action": "add_qualifier", 
                    "entry": entry_id,
                    "feature_type": feature.type,
                    "feature_id": getattr(feature, 'line_number', id(feature)),
                    "feature_line": getattr(feature, 'line_number', -1), 
                    "qualifier": "transl_table", 
                    "new_value": str(table_id)
                }]
                
                proposals.append({
                    "ann_path": ann_path, 
                    "rule": "ANN1050",  
                    "target": "transl_table",
                    "target_level": "qualifier",
                    "old": "none", "new": str(table_id), "entry": entry_id,
                    "positions": [{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                    "source_db": source_db_str,
                    "updates": updates
                })
            else:
                ann_table = feature.qualifiers["transl_table"][0]
                if str(ann_table) != str(table_id):
                    updates = [{
                        "action": "update_qualifier",
                        "entry": entry_id,
                        "feature_type": feature.type,
                        "feature_id": getattr(feature, 'line_number', id(feature)),
                        "qualifier": "transl_table", 
                        "old_value": str(ann_table), 
                        "new_value": str(table_id)
                    }]
                    
                    proposals.append({
                        "ann_path": ann_path, 
                        "rule": "ANN1050",  
                        "target": "transl_table",
                        "target_level": "qualifier",
                        "old": str(ann_table), "new": str(table_id), "entry": entry_id,
                        "positions": [{"entry": entry_id, "feature_id": getattr(feature, 'line_number', id(feature))}],
                        "source_db": source_db_str,
                        "updates": updates
                    })
    return proposals