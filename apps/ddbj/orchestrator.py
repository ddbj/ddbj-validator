import re
import shutil
import json
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor

from Bio.Data import CodonTable
from Bio.Seq import Seq
from Bio.SeqFeature import BeforePosition, AfterPosition

from apps.ddbj.preprocessor import preprocess_files, ANN_EXTENSIONS
from apps.ddbj.parser import parse_ddbj_submission
from apps.ddbj.validator import Validator
from common.db_manager import DatabaseManager
from apps.ddbj.db_metadata import (
    get_samds_from_records, get_projects_from_records, get_drrs_from_records, 
    fetch_biosample_data, fetch_biosample_submitters, fetch_biosample_smp_ids,
    fetch_bp_psubs, fetch_dra_refs, fetch_prjdb_by_psub, fetch_samd_by_smp_id,
    fetch_dra_library_metadata, fetch_drr_status, get_journals_from_records,
    fast_extract_db_keys
)
from common.db_taxonomy import fetch_taxonomy_data
from apps.ddbj.db_metadata import get_expected_transl_table, get_organisms_from_records
from apps.ddbj.autofix import (
    propose_format_errors, propose_qualifiers_updates, propose_taxonomy_updates, 
    propose_transl_table_fixes, review_and_approve_proposals, apply_proposals,
    propose_pcr_primer_fixes, propose_date_fixes, propose_latlon_fixes, 
    propose_geo_loc_name_fixes, propose_culture_collection_fixes, 
    propose_partial_location_fixes, propose_hold_date_fixes,
    propose_location_whitespace_fixes
)
from apps.ddbj.reporter import ValidationReporter
from apps.ddbj.context import ValidationContext
from common.ncbi_api import filter_target_accessions, check_ncbi_public_status
from apps.ddbj.utils.translation import get_cds_translation_params, get_insdc_translation
from apps.ddbj.utils.features import get_features


# ============================================================================
# ワーカー1: 1つのファイルセットに対する検証と Autofix 提案の生成を行う
# ============================================================================
def _validate_single_file_set(args):
    (
        ann_path, seq_path, context, tax_data, bs_data, is_web_mode, report_out_dir, tmp_dir_str
    ) = args

    from apps.ddbj.preprocessor import preprocess_files
    from apps.ddbj.parser import parse_ddbj_submission
    
    ann_lines, fasta_content, pre_warnings = preprocess_files(ann_path, seq_path)
    records, parse_errors = parse_ddbj_submission(
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

    val_results = validator.run(records, ann_path, seq_path, ann_lines=ann_lines, fasta_content=fasta_content)
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
            else:
                if fix_target == "location":
                    updates = [{"action": "update_location", "entry": entry_name, "feature_type": res.get("feature_type", ""), "old_value": old_v, "new_value": new_v}]
                else:
                    updates = [{"action": "update_qualifier", "entry": entry_name, "feature_type": res.get("feature_type", ""), "qualifier": qual_name, "old_value": old_v, "new_value": new_v}]

            file_proposals.append({
                "ann_path": ann_path,
                "entry": entry_name,
                "feature_type": res.get("feature_type", ""),
                "qualifier": qual_name,
                "target": fix_target,
                "target_level": res.get("fix_target", "qualifier"), 
                "positions": [{"entry": entry_name, "feature_id": res.get("line_number", "unknown")}],
                "old_value": old_v,
                "new_value": new_v,
                "old": old_v,
                "new": new_v,
                "message": res.get("message", "Value will be fixed."),
                "rule": rule_id,
                "updates": updates
            })
                                     
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
        props, bs_warnings, skips = propose_qualifiers_updates(records, bs_data, ann_path)
        file_proposals.extend(props)
        file_skipped_autofixes.extend(skips)
        file_results.extend(bs_warnings)

    missing_reporting_terms_set = {m.lower() for m in context.cv_terms.get("missing_reporting_terms", [])}
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
            current = p["old"]
            fixed = p["new"]
            # -o オプションがあればそこへ。なければ入力ファイルの親へ
            base_out = Path(report_out_dir) if report_out_dir else Path(ann_path).parent
            out_name = f"{Path(ann_path).stem}.updQ.txt"
            out_path = base_out / out_name
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

# ============================================================================
# ワーカー2: Autofix 適用とファイル生成を行う
# ============================================================================
def _apply_autofix_worker(args):
    # report_out_dir を引数で受け取る
    ann_path, seq_path, file_updates, tax_data, cv_terms, report_out_dir = args
    
    from apps.ddbj.preprocessor import preprocess_files
    from apps.ddbj.parser import parse_ddbj_submission
    
    ann_lines, fasta_content, _ = preprocess_files(ann_path, seq_path)
    records, _ = parse_ddbj_submission(fasta_content, ann_path, ann_lines, {})
    
    # -o オプションがあればそこへ。なければ入力ファイルの親へ
    base_out_dir = Path(report_out_dir) if report_out_dir else Path(ann_path).parent
    
    fixed_dir = base_out_dir / "fixed"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    
    fixed_fasta = fixed_dir / Path(seq_path).name 
    fast_copy_and_fix_fasta(fasta_content, fixed_fasta)
                
    original_ann_name = Path(ann_path).name
    for ext in ANN_EXTENSIONS:
        if original_ann_name.endswith(ext):
            original_ann_name = original_ann_name[:-len(ext)] + ".ann"
            break
    else:
        original_ann_name = Path(ann_path).with_suffix(".ann").name
        
    fixed_ann = fixed_dir / original_ann_name
    
    if file_updates:
        write_autofix_to_file(ann_lines, file_updates, fixed_ann)
    else:
        write_clean_ann(ann_lines, fixed_ann)

    aa_dir = base_out_dir / "aa"
    base_name = original_ann_name[:-4] if original_ann_name.endswith('.ann') else Path(original_ann_name).stem
    aa_fasta_path = aa_dir / f"AA_{base_name}.faa"
    
    is_aa_written = write_aa_fasta(records, aa_fasta_path, tax_data, cv_terms)
    
    msgs = []
    if file_updates:
        msgs.append(f"  => Auto-fixed ANN saved to: {fixed_ann}")
    else:
        msgs.append(f"  => Cleaned ANN saved to: {fixed_ann}")
    msgs.append(f"  => Cleaned FASTA saved to: {fixed_fasta}")
    if is_aa_written:
        msgs.append(f"  => Translated AA FASTA saved to: {aa_fasta_path}")
        
    return "\n".join(msgs)
    
    
def write_autofix_to_file(ann_lines, updates, out_path):
    current_entry = ""
    update_count = 0
    pending_new_features = [u for u in updates if u.get("action") == "add_feature"]
    
    with open(out_path, "w", encoding="utf-8", newline="\n") as fout:
        for line_no_0, line in enumerate(ann_lines):
            line_no = line_no_0 + 1
            clean_line = line.rstrip("\r\n")

            if not clean_line or clean_line.isspace():
                continue

            cols = clean_line.split("\t")
            
            if len(cols) > 0 and cols[0].strip():
                new_entry = cols[0].strip()
                
                if current_entry and new_entry != current_entry:
                    for u in list(pending_new_features):
                        if u.get("entry") == current_entry:
                            fout.write(f"\t{u.get('feature_type', '')}\t\t{u.get('qualifier', '')}\t{u.get('new_value', '')}\n")
                            update_count += 1
                            pending_new_features.remove(u)
                            
                current_entry = new_entry
                
            active_entry = current_entry

            if len(cols) < 3:
                fout.write(line + "\n")
                continue
                                
            entry = cols[0]
            feat_type = cols[1]
            loc_str = cols[2]
            qualifier = cols[3] if len(cols) > 3 else ""
            value = cols[4] if len(cols) > 4 else ""
            
            line_modified = False

            for u in updates:
                target_entry = str(u.get("entry", "")).strip()
                
                is_target_match = (
                    target_entry == active_entry or 
                    target_entry == "ALL_ENTRIES" or 
                    active_entry in ("", "COMMON")
                )

                if is_target_match:
                    action = u.get("action", "")
                    
                    if action == "update_location":
                        if feat_type.strip() == str(u.get("feature_type", "")).strip() and loc_str.strip().replace(" ", "") == str(u.get("old_value", "")).strip().replace(" ", ""):
                            cols[2] = str(u["new_value"])
                            loc_str = cols[2]
                            line_modified = True
                            update_count += 1
                            
                    elif action == "update_qualifier":
                        q_file = qualifier.strip()
                        q_target = str(u.get("qualifier", "")).strip()
                        v_file = str(value).strip()
                        v_target = str(u.get("old_value", "")).strip()

                        if q_target == q_file and v_file == v_target:
                            if len(cols) == 3:
                                cols.extend([str(u["qualifier"]), str(u["new_value"])])
                            elif len(cols) == 4:
                                cols.append(str(u["new_value"]))
                            else:
                                cols[4] = str(u["new_value"])
                                
                            qualifier = cols[3] if len(cols) > 3 else ""
                            value = cols[4] if len(cols) > 4 else ""
                            line_modified = True
                            update_count += 1
                                        
            if line_modified:
                fout.write("\t".join(cols) + "\n")
            else:
                fout.write(line + "\n")

            for u in updates:
                if u.get("action") == "add_qualifier" and u.get("feature_line") == line_no:
                    fout.write(f"\t\t\t{u['qualifier']}\t{u['new_value']}\n")
                    update_count += 1
                    
        for u in pending_new_features:
            if u.get("entry") == current_entry or current_entry == "":
                fout.write(f"\t{u.get('feature_type', '')}\t\t{u.get('qualifier', '')}\t{u.get('new_value', '')}\n")
                update_count += 1

    return update_count > 0
    
def write_clean_ann(ann_lines, out_path):
    with open(out_path, "w", encoding="utf-8", newline="\n") as fout:
        for line in ann_lines:
            clean_line = line.rstrip("\r\n")

            if not clean_line or clean_line.isspace():
                continue
                
            cols = clean_line.split("\t")
            if len(cols) not in (3, 4, 5):
                continue
            fout.write(line + "\n")

def write_aa_fasta(records, out_path, tax_data=None, cv_terms=None):
    has_output = False
    out_lines = []

    for entry_id, record in records.items():
        if entry_id == "COMMON":
            continue

        cds_serial = 1
        default_table_id = get_expected_transl_table(record, tax_data) if tax_data else 1

        for feature in get_features(record, "CDS"):
            if any(q in feature.qualifiers for q in ("pseudo", "pseudogene", "exception")):
                cds_serial += 1
                continue

            table_id, codon_start = get_cds_translation_params(feature, default_table_id)
            aa_seq = get_insdc_translation(feature, record, table_id, codon_start, cv_terms)

            if aa_seq:
                loc_str = getattr(feature, 'original_location', str(feature.location))
                header = f">{entry_id}.{cds_serial} {loc_str}"
                
                seq_lines = [aa_seq[i:i+60] for i in range(0, len(aa_seq), 60)]
                
                out_lines.append(header)
                out_lines.extend(seq_lines)
                out_lines.append("//")
                
                has_output = True
            
            cds_serial += 1

    if has_output:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8", newline="\n") as fout:
            fout.write("\n".join(out_lines) + "\n")
        return True
        
    return False    
                                        
def fast_copy_and_fix_fasta(fasta_content, dst_fasta_path):
    data = fast_fasta_content = fasta_content

    if data.startswith('>'):
        data = data[1:]

    blocks = data.split('\n>')
    
    with open(dst_fasta_path, 'w', encoding='utf-8', newline='\n') as f:
        for block in blocks:
            if not block or block.isspace():
                continue
                
            idx = block.find('\n')
            if idx == -1:
                f.write(f">{block}\n//\n")
            else:
                header = block[:idx]
                seq_str = block[idx+1:].lower()
                clean_seq = seq_str.rstrip()
                
                if clean_seq.endswith('//'):
                    clean_seq = clean_seq[:-2].rstrip()
                
                clean_seq += '\n//'
                f.write(f">{header}\n{clean_seq}\n")


class ValidatorPipeline:
    def __init__(self, pairs, report_out_dir, is_web_mode, force_fix, jobs=1, skip_db=False, skip_ncbi=False, skip_auth=False):
        self.pairs = pairs
        self.report_out_dir = report_out_dir
        self.is_web_mode = is_web_mode
        self.force_fix = force_fix
        self.jobs = jobs
        
        self.skip_db = skip_db
        self.skip_ncbi = skip_ncbi
        self.skip_auth = skip_auth
        
        self.all_interactive_proposals = []
        self.all_skipped_autofixes = []
        self.auto_updates_by_file = defaultdict(list)
        self.updq_data = defaultdict(list)
        self.tax_data = {}
        self.bs_data = {}
        self.cv_terms = {}

    def run_validation(self):
        """フェーズ1: ファイルの検証と Autofix 提案の収集"""
        all_samds, all_projects, all_drrs, all_organisms, all_journals = set(), set(), set(), set(), set()
        ncbi_check_prjs, ncbi_check_sams, ncbi_check_sras = set(), set() , set()
        
        bp_psubs, dra_refs, tax_data, bs_data = {}, {}, {}, {}
        bs_submitters, bs_smp_ids, psub_to_prjdb, smp_id_to_samd = {}, {}, {}, {}
        dra_lib_meta = {}
        drr_status = {}
        ncbi_private_accs = set() 
        
        # 1. 高速並列スキャン
        if not self.skip_db or not self.skip_ncbi:
            if self.skip_db and not self.skip_ncbi:
                print("\nScanning annotation files for NCBI API queries...")
            else:
                print("\nScanning annotation files for DB/API queries...")
                
            with ProcessPoolExecutor(max_workers=self.jobs) as executor:
                futures = [executor.submit(fast_extract_db_keys, ann, seq) for ann, seq in self.pairs]
                for future in futures:
                    res = future.result()
                    all_samds.update(res["samds"])
                    all_projects.update(res["projects"])
                    all_drrs.update(res["drrs"])
                    all_organisms.update(res["organisms"])
                    all_journals.update(res["journals"])
                    ncbi_check_prjs.update(res["ncbi_check_prjs"])
                    ncbi_check_sams.update(res["ncbi_check_sams"])
                    ncbi_check_sras.update(res["ncbi_check_sras"])

            # --- 2. データベース情報の取得 (内部DBへのアクセス) ---
            if not self.skip_db:
                db_manager = DatabaseManager()
                try:
                    if all_organisms or all_samds or all_projects or all_drrs:
                        print("\nChecking Internal DB...")

                    if all_organisms:
                        lbl = "organism" if len(all_organisms) == 1 else "organisms"
                        print(f"[Taxonomy DB] Checking {len(all_organisms)} {lbl}...")
                        tax_data = fetch_taxonomy_data(db_manager.get_tax_conn(), list(all_organisms))
                        
                    if all_projects:
                        lbl = "project" if len(all_projects) == 1 else "projects"
                        print(f"[BioProject DB] Checking {len(all_projects)} {lbl}...")
                        bp_psubs = fetch_bp_psubs(db_manager.get_bp_conn(), list(all_projects))

                    if all_samds:
                        samd_list = list(all_samds)
                        lbl = "sample" if len(samd_list) == 1 else "samples"
                        print(f"[BioSample DB] Checking {len(samd_list)} {lbl}...")
                        bs_data = fetch_biosample_data(db_manager.get_bs_conn(), samd_list)
                        bs_submitters = fetch_biosample_submitters(db_manager.get_bs_conn(), samd_list)
                        bs_smp_ids = fetch_biosample_smp_ids(db_manager.get_bs_conn(), samd_list)

                    if all_drrs:
                        lbl = "DRA Run" if len(all_drrs) == 1 else "DRA Runs"
                        print(f"[DRA DB] Checking {len(all_drrs)} {lbl}...")
                        dra_refs = fetch_dra_refs(db_manager.get_dra_conn(), list(all_drrs))
                        dra_lib_meta = fetch_dra_library_metadata(db_manager.get_dra_conn(), list(all_drrs))
                        drr_status = fetch_drr_status(db_manager.get_dra_conn(), list(all_drrs))
                        
                        if dra_refs:
                            dra_psubs, dra_smps = set(), set()
                            for refs in dra_refs.values():
                                for r in refs:
                                    if r.startswith("PSUB"): dra_psubs.add(r)
                                    elif r.isdigit(): dra_smps.add(int(r))
                            
                            if dra_psubs:
                                psub_to_prjdb = fetch_prjdb_by_psub(db_manager.get_bp_conn(), list(dra_psubs))
                            if dra_smps:
                                smp_id_to_samd = fetch_samd_by_smp_id(db_manager.get_bs_conn(), list(dra_smps))
                except Exception as e:
                    print(f"[ERROR] Database connection failed: {e}")
                    print(f"\n[ ERROR ] Database connection failed: {e}")
                    print("[ For users ] ")
                    print("="*80)
                    print("Please append:")
                    print("   -n (or --ncbi-api) : Use public NCBI API for taxonomy/accession checks (Recommended)")
                    print("   -l (or --local)    : Run offline (skips all DB/API dependent checks)")
                    print("="*80 + "\n")
                finally:
                    db_manager.close_all()
            else:
                print()
                if not self.skip_ncbi:
                    print("[ NCBI API ] Public NCBI API will be used for taxonomy-dependent rules and NCBI/EBI accessions checks.")
                print("[ SKIP ] Internal DB queries skipped. DB-dependent rules will be skipped.")
                
            # --- 3. NCBI APIへのアクセス ---
            if not self.skip_ncbi:
                if ncbi_check_prjs or ncbi_check_sams or ncbi_check_sras or (self.skip_db and all_organisms):
                    print("\nChecking NCBI API...")

                if ncbi_check_prjs:
                    lbl = "BioProject" if len(ncbi_check_prjs) == 1 else "BioProjects"
                    print(f"[NCBI API] Checking {len(ncbi_check_prjs)} {lbl}...")
                    res = check_ncbi_public_status("bioproject", list(ncbi_check_prjs))
                    ncbi_private_accs.update(res.get("private", []))

                if ncbi_check_sams:
                    lbl = "BioSample" if len(ncbi_check_sams) == 1 else "BioSamples"
                    print(f"[NCBI API] Checking {len(ncbi_check_sams)} {lbl}...")
                    res = check_ncbi_public_status("biosample", list(ncbi_check_sams))
                    ncbi_private_accs.update(res.get("private", []))

                if ncbi_check_sras:
                    lbl = "SRA Run" if len(ncbi_check_sras) == 1 else "SRA Runs"
                    print(f"[NCBI API] Checking {len(ncbi_check_sras)} {lbl}...")
                    res = check_ncbi_public_status("sra", list(ncbi_check_sras))
                    ncbi_private_accs.update(res.get("private", []))
                # DBスキップ時のみ NCBI API から Taxonomy を代替取得
                if self.skip_db and all_organisms:
                    lbl = "organism" if len(all_organisms) == 1 else "organisms"
                    print(f"[NCBI Taxonomy API] Checking {len(all_organisms)} {lbl}...")
                    from common.db_taxonomy import fetch_taxonomy_from_ncbi
                    tax_data = fetch_taxonomy_from_ncbi(list(all_organisms))                    
            else:
                print("\n[ SKIP ] NCBI API queries skipped. API- and taxonomy-dependent rules will be skipped.")
                
        else:
            print("\n[ SKIP ] DB and NCBI API queries skipped. DB-, API- and taxonomy-dependent rules will be skipped.")
            print("Tip: Use '-n' to enable taxonomy-dependent checks via NCBI API.")

        # --- Context の初期化 (共通ルート) ---
        context = ValidationContext(
            is_curator_mode=not self.skip_db,  # skip_db の場合はキュレーター権限オフ扱い
            is_web_mode=self.is_web_mode,
            skip_db=self.skip_db,
            skip_ncbi=self.skip_ncbi,
            skip_auth=self.skip_auth,
            bp_psubs=bp_psubs,
            dra_refs=dra_refs,
            drr_status=drr_status,
            tax_data=tax_data,
            bs_data=bs_data,
            bs_submitters=bs_submitters,
            bs_smp_ids=bs_smp_ids,
            psub_to_prjdb=psub_to_prjdb,
            smp_id_to_samd=smp_id_to_samd,
            dra_lib_meta=dra_lib_meta,
            ncbi_private_accs=ncbi_private_accs  
        )
        
        # valid_journals の追加取得
        if not self.skip_db and all_journals:
            db_manager = DatabaseManager()
            try:
                context.load_valid_journals(list(all_journals), db_manager.get_tax_conn())
            except Exception:
                pass
            finally:
                db_manager.close_all()

        self.tax_data = tax_data
        self.bs_data = bs_data
            
        auto_updates_by_file = defaultdict(list)
        updq_data = defaultdict(list)
                
        # 4. 個別ファイルの検証 (並列処理)
        # 出力先が指定されていればそこに、なければ今まで通り .val_tmp を作成
        base_tmp_dir = Path(self.report_out_dir) if self.report_out_dir else Path(self.pairs[0][0]).parent
        self.tmp_dir = base_tmp_dir / ".val_tmp"
        self.tmp_dir.mkdir(parents=True, exist_ok=True)

        tasks = []
        for ann_path, seq_path in self.pairs:
            tasks.append((ann_path, seq_path, context, self.tax_data, self.bs_data, self.is_web_mode, self.report_out_dir, str(self.tmp_dir)))
            
        jsonl_paths = []
        with ProcessPoolExecutor(max_workers=self.jobs) as executor:
            actual_workers = min(executor._max_workers, len(tasks))
            num_sets = len(self.pairs)
            
            p_label = "process" if actual_workers == 1 else "processes"
            f_label = "file set" if num_sets == 1 else "file sets"
            
            print(f"\nRunning validations for {num_sets} {f_label} in {actual_workers} {p_label}...\n")
            
            for output in executor.map(_validate_single_file_set, tasks):
                jsonl_paths.append(output["jsonl_path"])
                self.all_skipped_autofixes.extend(output["skipped_autofixes"])
                
                for out_path, line in output["updq_data"]:
                    updq_data[out_path].append(line)

        # 5. JSONL からメタデータと提案を読み出してクロスチェック
        cross_locus_tags = defaultdict(list)
        all_interactive_proposals = []
        
        for j_path in jsonl_paths:
            with open(j_path, "r", encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    r_type = rec["type"]
                    data = rec["data"]
                    if r_type == "locus_tag":
                        data["file"] = j_path
                        cross_locus_tags[data["tag"]].append(data)
                    elif r_type == "proposal":
                        all_interactive_proposals.append(data)

        # クロスファイル（Submission全体）のユニークチェック
        cross_file_results = []

        for tag, locs in cross_locus_tags.items():
            # エントリー名とファイル名の組み合わせでユニークにする
            unique_occurrences = set([f"{o['entry']} in {Path(o['file']).name.replace('.jsonl', '')}" for o in locs])
            
            # 異なるエントリー（または異なるファイル）にまたがって存在する場合のみエラーとする
            if len(unique_occurrences) > 1:
                details = ", ".join(sorted(list(unique_occurrences)))
                msg = f"Duplicate locus_tag found across the submission. (Found: '{tag}' in {details})"
                cross_file_results.append({
                    "file": "Submission (across files)", "full_path": "", "rule": "ANN2520",
                    "level": "ERROR", "entry": "ALL_ENTRIES", "feature_type": "locus_tag", "target": "locus_tag", "message": msg
                })
                                
        # クロスファイルのチェック結果も専用の JSONL に書き出して先頭に追加
        if cross_file_results:
            cross_jsonl = self.tmp_dir / "Submission_Cross_File.jsonl"
            with open(cross_jsonl, "w", encoding="utf-8") as f:
                for res in cross_file_results:
                    f.write(json.dumps({"type": "result", "data": res}) + "\n")
            jsonl_paths.insert(0, str(cross_jsonl))

        # 後続フェーズのために状態を保存
        self.all_interactive_proposals = all_interactive_proposals
        self.auto_updates_by_file = auto_updates_by_file
        self.updq_data = updq_data
        self.cv_terms = context.cv_terms
        
        return jsonl_paths

    def cleanup_tmp_dir(self):
        """テンポラリディレクトリのお掃除"""
        if hasattr(self, 'tmp_dir') and self.tmp_dir and self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def run_autofix(self):
        """フェーズ2 & 3: Autofix 提案のレビューとファイルへの適用"""
        if self.all_skipped_autofixes:
            print("\n=== Auto-Fix Skipped (Mixed BioSample Values) ===")
            skip_summary = defaultdict(lambda: defaultdict(list))
            
            for skip in self.all_skipped_autofixes:
                val_str = "{" + ", ".join(repr(v) for v in sorted(skip["values"])) + "}"
                skip_summary[skip["ann_path"]][skip["attr"]].append((skip["entry"], val_str))
                
            for path_str, attrs in sorted(skip_summary.items()):
                print(f"\n[ {Path(path_str).name} ]")
                for attr, entries in sorted(attrs.items()):
                    first_val_str = entries[0][1] 
                    e_len = len(entries)
                    e_label = "entry" if e_len == 1 else "entries"
                    print(f"  {e_len} {e_label}: BioSample values differ for '{attr}': {first_val_str}")
            print() 

        for p in self.all_interactive_proposals:
            old_val = p.get("old_value") if p.get("old_value") is not None else p.get("old")
            new_val = p.get("new_value") if p.get("new_value") is not None else p.get("new")
            
            p["old_value"] = old_val
            p["old"] = old_val
            p["new_value"] = new_val
            p["new"] = new_val
            
            if "rule" not in p or not p["rule"]:
                p["rule"] = "UNKNOWN"
                
            if "target" not in p:
                p["target"] = p.get("qualifier", "feature")
            
        # out_dir を渡して、提案サマリーを同じ場所に出力させる
        approved_proposals = review_and_approve_proposals(self.all_interactive_proposals, self.force_fix, out_dir=self.report_out_dir)
        
        approved_by_file = defaultdict(list)
        if approved_proposals:
            for p in approved_proposals:  
                approved_by_file[p["ann_path"]].append(p)

        # 並列で Autofix を適用して出力
        if approved_proposals or not self.all_interactive_proposals:
            print("\n=== File Cleanup & Auto-Fix ===")
        else:
            print("\n=== File Cleanup (No auto-fix) ===")

        autofix_tasks = []
        for ann_path, seq_path in self.pairs:
            file_updates = self.auto_updates_by_file[ann_path]
            
            if approved_proposals and approved_by_file[ann_path]:
                interactive_updates = apply_proposals(approved_by_file[ann_path])
                file_updates.extend(interactive_updates)
                
            # report_out_dir を引数に追加
            autofix_tasks.append((ann_path, seq_path, file_updates, self.tax_data, self.cv_terms, self.report_out_dir))

        with ProcessPoolExecutor(max_workers=self.jobs) as executor:
            for msg in executor.map(_apply_autofix_worker, autofix_tasks):
                print(msg)
                
        if self.is_web_mode and self.updq_data:
            print("\n[NSSS Mode] Exporting DB update files...")
            for out_path, lines in self.updq_data.items():
                with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                    f.writelines(lines)
                print(f"  => DB update TSV saved to: {out_path}")