"""フェーズ 2 のワーカー: 1 ファイルセット（.ann + FASTA）の検証と autofix 提案の生成。

ProcessPoolExecutor に渡すため、`ValidateTask` と `_validate_single_file_set` は
**モジュールのトップレベル**に置く（pickle 可能である必要がある。クロージャやメソッドにしない）。
結果はメモリで返さず `<tmp>/<ann>.jsonl` に書き捨て、親（orchestrator._validate_files）が読み戻す。
2026-09-15 に apps/ddbj/orchestrator.py から移動（中身は不変）。
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from apps.ddbj.validator import Validator
from apps.ddbj.autofix.proposal import build_proposal, update_qualifier_action, update_location_action
from apps.ddbj.autofix import (
    propose_format_errors, propose_qualifiers_updates, propose_taxonomy_updates,
    propose_transl_table_fixes, propose_pcr_primer_fixes, propose_date_fixes, propose_latlon_fixes,
    propose_geo_loc_name_fixes, propose_culture_collection_fixes,
    propose_partial_location_fixes, propose_hold_date_fixes,
    propose_location_whitespace_fixes
)
from apps.ddbj.rule_modes import get_web_mode_skip_rules
from common.features import get_features


@dataclass(frozen=True)
class ValidateTask:
    """検証ワーカー (_validate_single_file_set) へ渡す入力一式。

    位置引数タプルだと項目追加（biosample 用フィールド追加など）で順序ずれが起きやすいため構造体化。
    ProcessPoolExecutor へ渡すため pickle 可能なモジュールレベル dataclass にしている。
    """
    ann_path: Any
    seq_path: Any
    context: Any
    tax_data: Any
    bs_data: Any
    is_web_mode: Any
    report_out_dir: Any
    tmp_dir_str: Any
    unauthorized_accs: Any
    emit_biosample_tsv: Any
    biosample_sync_common: Any
    biosample_sync_mapping_keys: Any


# ============================================================================
# ワーカー1: 1つのファイルセットに対する検証と Autofix 提案の生成を行う
# ============================================================================
def _validate_single_file_set(task):
    ann_path = task.ann_path
    seq_path = task.seq_path
    context = task.context
    tax_data = task.tax_data
    bs_data = task.bs_data
    is_web_mode = task.is_web_mode
    report_out_dir = task.report_out_dir
    tmp_dir_str = task.tmp_dir_str
    unauthorized_accs = task.unauthorized_accs
    emit_biosample_tsv = task.emit_biosample_tsv
    biosample_sync_common = task.biosample_sync_common
    biosample_sync_mapping_keys = task.biosample_sync_mapping_keys

    from apps.ddbj.preprocessor import preprocess_files
    from apps.ddbj.parser import parse_ddbj_submission
    from apps.ddbj.utils.features import get_features # 追加
    
    ann_lines, fasta_content, pre_warnings = preprocess_files(ann_path, seq_path)
    records, parse_errors, fasta_only_records = parse_ddbj_submission(
        fasta_content=fasta_content, 
        ann_path=ann_path, 
        ann_lines=ann_lines, 
        ddbj_dict=context.ddbj_dict
    )

    context.analyze_records(records)
    validator = Validator(context)

    file_results = []
    file_proposals = []
    file_skipped_autofixes = []
    file_updq_data = []

    file_results.extend(pre_warnings + parse_errors)

    # ====================================================
    # アカウント権限エラーのファイル単位判定
    # ====================================================
    if unauthorized_accs and any(unauthorized_accs.values()):
        for entry_id, record in records.items():
            for feature in get_features(record, "DBLINK"):
                for acc in feature.qualifiers.get("project", []):
                    if acc in unauthorized_accs.get("bioproject", set()):
                        msg = f"BioProject accession is not associated with this account. (Found: '{acc}')"
                        file_results.append({"file": Path(ann_path).name, "full_path": str(ann_path), "rule": "ANN0422", "level": "ERROR", "entry": entry_id, "feature_type": "DBLINK", "target": "project", "message": msg, "line_number": getattr(feature, "line_number", None), "category": "auth"})
                
                for acc in feature.qualifiers.get("biosample", []):
                    if acc in unauthorized_accs.get("biosample", set()):
                        msg = f"BioSample accession is not associated with this account. (Found: '{acc}')"
                        file_results.append({"file": Path(ann_path).name, "full_path": str(ann_path), "rule": "ANN0463", "level": "ERROR", "entry": entry_id, "feature_type": "DBLINK", "target": "biosample", "message": msg, "line_number": getattr(feature, "line_number", None), "category": "auth"})
                
                for acc in feature.qualifiers.get("sequence read archive", []):
                    if acc in unauthorized_accs.get("sra", set()):
                        msg = f"DRR accession is not associated with this account. (Found: '{acc}')"
                        file_results.append({"file": Path(ann_path).name, "full_path": str(ann_path), "rule": "ANN0481", "level": "ERROR", "entry": entry_id, "feature_type": "DBLINK", "target": "sequence read archive", "message": msg, "line_number": getattr(feature, "line_number", None), "category": "auth"})
                        
    val_results = validator.run(records, ann_path, seq_path, ann_lines=ann_lines,
                                fasta_content=fasta_content, fasta_only_records=fasta_only_records)
    file_results.extend(val_results)
    
    for res in val_results:
        if res.get("autofix") and "new_value" in res:
            entry_name = res.get("entry", res.get("entry_id", ""))
            qual_name = res.get("qualifier", "")
            old_v = res.get("old_value")
            new_v = res.get("new_value")
            rule_id = res.get("rule", "ANN0000")
            fix_target = res.get("fix_target", qual_name)
            
            if "updates" in res:
                updates = res["updates"]
            elif fix_target == "location":
                updates = [update_location_action(entry_name, res.get("feature_type", ""), old_v, new_v)]
            else:
                updates = [update_qualifier_action(entry_name, res.get("feature_type", ""), qual_name, old_v, new_v)]

            file_proposals.append(build_proposal(
                ann_path=ann_path,
                entry=entry_name,
                feature_type=res.get("feature_type", ""),
                qualifier=qual_name,
                target=fix_target,
                target_level=res.get("fix_target", "qualifier"),
                positions=[{"entry": entry_name, "feature_id": res.get("line_number", "unknown")}],
                old_value=old_v,
                new_value=new_v,
                rule=rule_id,
                updates=updates,
            ))
                                      
    if tax_data:
        tax_proposals = propose_taxonomy_updates(records, tax_data, ann_path)
        file_proposals.extend(tax_proposals)
        for p in tax_proposals:
            source_str = p.get("source_db", "")
            match_type = source_str.split(", ")[-1] if ", " in source_str else "unknown"
            for pos in p.get("positions", []):
                file_results.append({
                    "file": Path(ann_path).name,
                    "full_path": str(ann_path),
                    "rule": p.get("rule", "ANN1025"),
                    "level": "WARNING",
                    "entry": pos.get("entry", "ALL_ENTRIES"),
                    "feature_type": "source",
                    "target": "organism",
                    "qualifier": "organism",
                    "message": f"The organism name will be corrected to the scientific name in the Taxonomy database. (Found: '{p.get('old')}', Type: '{match_type}')",
                    "line_number": pos.get("feature_id")
                })
                                                
        file_proposals.extend(propose_transl_table_fixes(records, tax_data, ann_path))

    if bs_data:
        unauth_bs = unauthorized_accs.get("biosample", set()) if unauthorized_accs else set()
        # -b 時は biosample_sync.common を突合対象にし（organism 等も網羅）、ann限定属性の追加候補も emit
        sync_attrs = biosample_sync_common if emit_biosample_tsv else None
        props, bs_warnings, skips = propose_qualifiers_updates(
            records, bs_data, ann_path, unauthorized_bs=unauth_bs,
            sync_attrs=sync_attrs, emit_additions=emit_biosample_tsv,
            mapping_keys=biosample_sync_mapping_keys
        )
        file_proposals.extend(props)
        file_skipped_autofixes.extend(skips)
        file_results.extend(bs_warnings)

    from common.insdc_missing import reporting_terms
    missing_reporting_terms_set = reporting_terms()  # 有効 "missing: term" 集合（common 単一ソース）
    date_fixes = propose_date_fixes(records, ann_path, allowed_missing_reporting_terms=missing_reporting_terms_set, existing_proposals=file_proposals)
    file_proposals.extend(date_fixes)

    hold_date_fixes = propose_hold_date_fixes(records, ann_path, existing_proposals=file_proposals)
    file_proposals.extend(hold_date_fixes)
                            
    latlon_fixes = propose_latlon_fixes(records, ann_path, existing_proposals=file_proposals)
    file_proposals.extend(latlon_fixes)

    for p in latlon_fixes:
        if "message" in p:
            file_results.append({
                "file": Path(ann_path).name, "full_path": str(ann_path),
                "rule": p.get("rule"), "level": p.get("level", "WARNING").upper(),
                "entry": p.get("entry"), "feature_type": p.get("feature_type", ""),
                "target": p.get("target"), "qualifier": p.get("target"),
                "message": p.get("message"), "line_number": p["positions"][0]["feature_id"] if p.get("positions") else None
            })
            
    geo_loc_allowed_list = context.cv_terms.get("countries", [])
    if geo_loc_allowed_list:
        geo_loc_fixes = propose_geo_loc_name_fixes(records, ann_path, allowed_values=geo_loc_allowed_list, allowed_missing_reporting_terms=missing_reporting_terms_set, existing_proposals=file_proposals)
        file_proposals.extend(geo_loc_fixes)
                                                         
    if context.institution_codes:
        culture_collection_fixes = propose_culture_collection_fixes(records, ann_path, allowed_map=context.institution_codes, existing_proposals=file_proposals)
        file_proposals.extend(culture_collection_fixes)
        
    pcr_fixes = propose_pcr_primer_fixes(records, ann_path)
    file_proposals.extend(pcr_fixes)

    partial_loc_fixes = propose_partial_location_fixes(records, ann_path, tax_data)
    file_proposals.extend(partial_loc_fixes)

    whitespace_fixes = propose_location_whitespace_fixes(records, ann_path)
    file_proposals.extend(whitespace_fixes)

    format_fixes = propose_format_errors(records, ann_path)
    file_proposals.extend(format_fixes)
                  
    if is_web_mode:
        for p in pcr_fixes:
            acc = p["entry"].split('_')[0]
            current = p["old_value"]
            fixed = p["new_value"]
            # -o オプションがあればそこへ。なければ入力ファイルの親へ。updQ は reports/ 配下に出す
            base_out = Path(report_out_dir) if report_out_dir else Path(ann_path).parent
            out_name = f"{Path(ann_path).stem}.updQ.txt"
            out_path = base_out / "reports" / out_name
            file_updq_data.append((out_path, f">{acc}\tPCR_primers\t{current}\tPCR_primers\t{fixed}\n"))

    # ====================================================
    # メインプロセスでのクロスファイルチェック用にメタデータを収集
    # ====================================================
    file_locus_tags = []

    for entry_id, record in records.items():
        if entry_id == "COMMON":
            continue

        for feature in get_features(record):
            if "locus_tag" in feature.qualifiers:
                for tag in feature.qualifiers["locus_tag"]:
                    file_locus_tags.append({
                        "tag": tag.strip(),
                        "entry": entry_id,
                        "feature_type": feature.type,
                        "line_number": getattr(feature, 'line_number', None)
                    })

    # ====================================================
    # メインプロセスにデータを返さず、専用のテンポラリJSONLに書き捨てる
    # ====================================================
    # -w（NSSS）モードでは所定のルールを適用しない（結果を除外。リストは web_mode_skip_rules.json）
    if is_web_mode:
        web_skip = get_web_mode_skip_rules()
        if web_skip:
            file_results = [r for r in file_results if r.get("rule") not in web_skip]

    tmp_jsonl_path = Path(tmp_dir_str) / f"{Path(ann_path).name}.jsonl"

    with open(tmp_jsonl_path, "w", encoding="utf-8") as f_jsonl:
        def write_record(rec_type, data):
            f_jsonl.write(json.dumps({"type": rec_type, "data": data}) + "\n")
            
        for res in file_results:
            write_record("result", res)
            
        for prop in file_proposals:
            write_record("proposal", prop)
            
        for loc in file_locus_tags:
            write_record("locus_tag", loc)
            
    return {
        "jsonl_path": str(tmp_jsonl_path),
        "skipped_autofixes": file_skipped_autofixes,
        "updq_data": file_updq_data
    }
