#!/usr/bin/env python3

import sys
import subprocess
import re
import argparse
from pathlib import Path

try:
    from Bio import SeqIO
    HAS_BIOPYTHON = True
except ImportError:
    HAS_BIOPYTHON = False

class Colors:
    OKGREEN = '\033[92m'
    FAILRED = '\033[91m'
    WARNINGYEL = '\033[93m'
    ENDC = '\033[0m'

def extract_feature_expectations(ann_path):
    has_fail = False
    has_pass = False
    
    with open(ann_path, 'r', encoding='utf-8') as f:
        for line in f:
            cols = line.rstrip('\n').split('\t')
            if len(cols) >= 5:
                qualifier = cols[3].strip()
                value = cols[4].strip()
                if qualifier == "note":
                    if re.search(r'\bfail\b', value, re.IGNORECASE):
                        has_fail = True
                    elif re.search(r'\bpass\b', value, re.IGNORECASE):
                        has_pass = True
                        
    if has_fail: return "fail"
    if has_pass: return "pass"
    return None

def extract_entry_expectations(ann_path):
    expectations = {}
    current_entry = None
    
    with open(ann_path, 'r', encoding='utf-8') as f:
        for line in f:
            cols = line.rstrip('\n').split('\t')
            if not cols:
                continue
                
            if cols[0].strip() and cols[0] != "COMMON":
                current_entry = cols[0].strip()
                if current_entry not in expectations:
                    expectations[current_entry] = {}
                    
            if current_entry and len(cols) >= 5:
                qualifier = cols[3].strip()
                value = cols[4].strip()
                
                if qualifier == "note":
                    matches = re.findall(r'([A-Z]{3}\d+)\s+(pass|fail|clean)', value, re.IGNORECASE)
                    for rule_id, status in matches:
                        expectations[current_entry][rule_id.upper()] = status.lower()
                        
    return expectations
    
def parse_details_report(report_path):
    results = {}
    results_by_entry = {}
    current_file = None
    
    with open(report_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            file_match = re.match(r'^\d+\.\s+(\S+)', line)
            if file_match:
                current_file = file_match.group(1).replace('.ann', '').replace('.fasta', '')
                results[current_file] = set()
                results_by_entry[current_file] = {}
                continue
                
            parts = line.split(':')
            if current_file and len(parts) >= 3:
                rule_id = parts[0]
                level = parts[1]
                if re.match(r'^[A-Z0-9]+$', rule_id) and level in ["ERR", "WAR", "FAT", "INFO"]:
                    entry_name = parts[2]
                    
                    results[current_file].add(rule_id)
                    
                    if entry_name not in results_by_entry[current_file]:
                        results_by_entry[current_file][entry_name] = set()
                    results_by_entry[current_file][entry_name].add(rule_id)
                
    return results, results_by_entry

def compare_fasta(fasta_ddbj, fasta_tool, ignore_ids=None):
    """
    2つのアミノ酸FASTAを比較し、一致するかどうかとエラーメッセージを返す。
    '?' が含まれる、または配列が空のシーケンスは比較をスキップし、その旨をメッセージとして返す。
    """
    if ignore_ids is None:
        ignore_ids = set()
        
    if not HAS_BIOPYTHON:
        return False, "Biopython is not installed."
        
    try:
        dict_ddbj = SeqIO.to_dict(SeqIO.parse(fasta_ddbj, "fasta"))
        dict_tool = SeqIO.to_dict(SeqIO.parse(fasta_tool, "fasta"))
    except Exception as e:
        return False, f"Failed to parse FASTA: {e}"

    def should_ignore(seq_id):
        return any(seq_id == ign or seq_id.startswith(f"{ign}.") for ign in ignore_ids)

    ids_ddbj = {i for i in dict_ddbj.keys() if not should_ignore(i)}
    ids_tool = {i for i in dict_tool.keys() if not should_ignore(i)}

    if "ALL" in ignore_ids or (not ids_ddbj and not ids_tool):
        return True, "Skipped (Expected fail entries)"

    only_in_ddbj = ids_ddbj - ids_tool
    only_in_tool = ids_tool - ids_ddbj
    common_ids = ids_ddbj & ids_tool

    error_msgs = []
    skipped_msgs = []
    
    if only_in_ddbj:
        error_msgs.append(f"Missing in current tool: {list(only_in_ddbj)[:3]}")
    if only_in_tool:
        error_msgs.append(f"Unexpected in current tool: {list(only_in_tool)[:3]}")

    mismatch_count = 0
    for seq_id in sorted(common_ids):
        # DDBJ特有の終端記号 '//' や空白を完全に除去して純粋な配列だけにする
        seq_ddbj = str(dict_ddbj[seq_id].seq).replace('/', '').strip()
        seq_tool = str(dict_tool[seq_id].seq).replace('/', '').strip()

        # '?' が含まれている場合はスキップ
        if '?' in seq_ddbj or '?' in seq_tool:
            skipped_msgs.append(f"[{seq_id}] Skipped (Contains '?')")
            continue
            
        # 完全に空（アミノ酸が1文字もない）場合はスキップ
        if len(seq_ddbj) == 0 or len(seq_tool) == 0:
            skipped_msgs.append(f"[{seq_id}] Skipped (Empty sequence)")
            continue

        if seq_ddbj != seq_tool:
            mismatch_count += 1
            if len(seq_ddbj) != len(seq_tool):
                error_msgs.append(f"[{seq_id}] Length mismatch (cleaned) (DDBJ:{len(seq_ddbj)} vs Tool:{len(seq_tool)})")
            
            min_len = min(len(seq_ddbj), len(seq_tool))
            for i in range(min_len):
                if seq_ddbj[i] != seq_tool[i]:
                    start = max(0, i - 10)
                    end = min(min_len, i + 10)
                    ctx_ddbj = f"{seq_ddbj[start:i]}[{seq_ddbj[i]}]{seq_ddbj[i+1:end]}"
                    ctx_tool = f"{seq_tool[start:i]}[{seq_tool[i]}]{seq_tool[i+1:end]}"
                    error_msgs.append(f"[{seq_id}] Diff at {i+1}: DDBJ=..{ctx_ddbj}.. Tool=..{ctx_tool}..")
                    break

    if mismatch_count == 0 and not only_in_ddbj and not only_in_tool:
        success_msg = "Match"
        if skipped_msgs:
            success_msg += f" | {', '.join(skipped_msgs)}"
        return True, success_msg
    else:
        if skipped_msgs:
            error_msgs.extend(skipped_msgs)
        return False, " | ".join(error_msgs)
                        
def run_e2e_tests(target_rule_id=None):
    if not HAS_BIOPYTHON:
        print(f"{Colors.WARNINGYEL}[WARNING] Biopython is not installed. 6000-series amino acid fasta comparisons will fail. Please run 'pip install biopython'.{Colors.ENDC}\n")

    # 1. パス解決の修正 (run_tests.py は apps/ddbj/tests の中にあるため、3階層上がプロジェクトルート)
    tests_dir = Path(__file__).resolve().parent
    project_root = tests_dir.parent.parent.parent
    
    # テストデータは自分自身と同じディレクトリ(tests)内にある
    test_data_dir = tests_dir
    
    # バリデータ起動スクリプトの名前を bsi-validator.sh に変更
    validator_sh = project_root / "bsi-validator.sh"

    if not validator_sh.exists():
        print(f"{Colors.FAILRED}Error: {validator_sh} not found.{Colors.ENDC}")
        sys.exit(1)

    target_dirs = sorted([
        d for d in test_data_dir.glob("*/*")
        if d.is_dir() and any(d.glob("*.ann"))
    ])
    
    target_rules_set = set(target_rule_id.split('-')) if target_rule_id else set()

    if target_rule_id:
        target_dirs = [
            d for d in target_dirs 
            if target_rule_id in d.name or any(r in d.name for r in target_rules_set)
        ]

    if not target_dirs:
        if target_rule_id:
            print(f"No test directories found for rule: {target_rule_id}")
        else:
            print("No test directories found.")
        return
        
    passed_count = 0
    mismatched_count = 0
    errors = []

    msg = f"\nStarting E2E Tests via Shell (Parsing Details Report)"
    if target_rule_id:
        msg += f" for Rule(s): {target_rule_id}...\n"
    else:
        msg += "...\n"
    print(msg)

    for target_dir in target_dirs:
        print(f"Testing directory: {target_dir.relative_to(project_root)}")
        
        # コマンドに "ddbj" サブコマンドを明示的に追加
        cmd = [str(validator_sh), "ddbj", str(target_dir), "-f"]
        result = subprocess.run(cmd, capture_output=True, text=True)
                
        report_path = target_dir / "validation_report_details.txt"
        if not report_path.exists():
            print(f"{Colors.FAILRED}[ERROR]{Colors.ENDC} Details report not generated: {report_path}")
            if result.returncode != 0:
                print(result.stderr)
            continue

        triggered_rules_by_file, triggered_rules_by_entry = parse_details_report(report_path)

        for ann_path in target_dir.glob("*.ann"):
            filename = ann_path.name
            file_stem = ann_path.stem 
            
            parts = filename.split('.')
            is_file_level = len(parts) >= 3 and parts[-2] in ["pass", "fail"]
            is_entries_level = "entries" in parts
            
            file_rule_ids = filename.split('_')[0].split('-')
            
            test_cases = []
            
            # --- 1. ファイルレベルのチェック ---
            if not is_entries_level:
                has_target_rule = any(r in target_rules_set for r in file_rule_ids)
                if target_rule_id and not has_target_rule and target_dir.name != target_rule_id:
                    continue

                expected_result = None
                if target_dir.name in ["SEQ0100", "ANN0170", "ANN0180", "ANN0350", "ANN0800", "ANN0810"]:
                    expected_result = "clean"
                elif is_file_level:
                    expected_result = parts[-2]
                else:
                    expected_result = extract_feature_expectations(ann_path)

                if not expected_result:
                    continue 

                actual_rules = triggered_rules_by_file.get(file_stem, set())
                
                for rule_id in file_rule_ids:
                    if target_rule_id and rule_id not in target_rules_set and target_dir.name != target_rule_id:
                        continue
                        
                    rule_triggered = rule_id in actual_rules
                    order_map = {"pass": 0, "fail": 1, "clean": 2}
                    sort_order = order_map.get(expected_result, 3)

                    test_cases.append({
                        "filename": filename,
                        "file_stem": file_stem,
                        "rule_id": rule_id,
                        "expected_result": expected_result,
                        "actual_rules": actual_rules,
                        "rule_triggered": rule_triggered,
                        "sort_order": sort_order,
                        "type": "file"
                    })

            # --- 2. エントリーレベルのチェック ---
            else:
                entry_expectations = extract_entry_expectations(ann_path)
                file_triggered_entries = triggered_rules_by_entry.get(file_stem, {})

                for entry_name, rules in entry_expectations.items():
                    for rule_id, expected_result in rules.items():
                        
                        if target_rule_id and rule_id not in target_rules_set and target_dir.name != target_rule_id:
                            continue

                        entry_actual_rules = file_triggered_entries.get(entry_name, set())
                        global_rules = file_triggered_entries.get("ALL", set()).union(file_triggered_entries.get("COMMON", set()))
                        rule_triggered = (rule_id in entry_actual_rules) or (rule_id in global_rules)

                        order_map = {"pass": 0, "fail": 1}
                        sort_order = order_map.get(expected_result, 3)

                        test_cases.append({
                            "filename": f"{filename} [{entry_name}]",
                            "file_stem": file_stem,
                            "rule_id": rule_id,
                            "expected_result": expected_result,
                            "actual_rules": entry_actual_rules,
                            "rule_triggered": rule_triggered,
                            "sort_order": sort_order,
                            "type": "entry"
                        })

            # --- 評価フェーズ ---
            test_cases.sort(key=lambda x: (x["sort_order"], x["filename"], x["rule_id"]))

            for tc in test_cases:
                tc_filename = tc["filename"]
                tc_file_stem = tc["file_stem"]
                tc_rule_id = tc["rule_id"]
                tc_expected_result = tc["expected_result"]
                tc_rule_triggered = tc["rule_triggered"]
                
                test_name = f"{tc_filename} (Rule: {tc_rule_id})"
                
                if tc_expected_result == "pass":
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected PASS, but rule triggered.")
                        errors.append(f"{target_dir.name}/{test_name}")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name}")
                        passed_count += 1
                        
                elif tc_expected_result == "fail":
                    if not tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected FAIL, but rule did NOT trigger.")
                        errors.append(f"{target_dir.name}/{test_name}")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name}")
                        passed_count += 1

                elif tc_expected_result == "clean":
                    # --- 既存の clean チェック ---
                    pass

            # --- 3. ANN5270 Autofix (clean) 確認 ---
            if target_dir.name == "ANN5270" or target_rule_id == "ANN5270" or "ANN5270" in file_rule_ids:
                # fail を期待しているテストケースがあるか確認し、なければスキップ
                has_fails = any(tc["expected_result"] == "fail" for tc in test_cases)
                if has_fails:
                    fixed_file_path = target_dir / "fixed" / filename
                    
                    if not fixed_file_path.exists():
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {filename} (Rule: ANN5270 Auto-fix): Expected fixed file, but it is missing.")
                        errors.append(f"{target_dir.name}/{filename} (Fixed file missing for ANN5270)")
                        mismatched_count += 1
                    else:
                        with open(fixed_file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # entriesファイルの場合は、failが期待されるエントリーのテキストのみを抽出する
                        content_to_check = content
                        if is_entries_level:
                            failed_entries = {tc["filename"].split('[')[-1].strip(']') for tc in test_cases if tc["expected_result"] == "fail"}
                            entry_blocks = []
                            current_block = []
                            current_entry_name = None
                            for line in content.splitlines():
                                cols = line.split('\t')
                                if cols and cols[0].strip() and cols[0].strip() != "COMMON":
                                    if current_entry_name and current_entry_name in failed_entries:
                                        entry_blocks.append("\n".join(current_block))
                                    current_block = []
                                    current_entry_name = cols[0].strip()
                                current_block.append(line)
                            if current_entry_name and current_entry_name in failed_entries:
                                entry_blocks.append("\n".join(current_block))
                            content_to_check = "\n".join(entry_blocks)
                        
                        # 抽出したテキストがある場合のみチェックを実行
                        if content_to_check.strip():
                            is_clean_success = True
                            fail_reason = ""
                            unfixed_items = []
                            
                            if re.search(r'CDS\s+41\.\.60', content_to_check):
                                unfixed_items.append("seq1 (CDS 41..60 not changed)")
                            if re.search(r'mRNA\s+61\.\.80', content_to_check):
                                unfixed_items.append("seq2 (mRNA 61..80 not changed)")

                            if not re.search(r'41\.\.>50', content_to_check):
                                unfixed_items.append("seq1 (Expected 41..>50 not found)")
                            if not re.search(r'<71\.\.80', content_to_check):
                                unfixed_items.append("seq2 (Expected <71..80 not found)")
                                
                            if unfixed_items:
                                is_clean_success = False
                                fail_reason = "Autofix verification failed: " + ", ".join(unfixed_items)
                                
                            test_name_autofix = f"{filename} (Rule: ANN5270 Auto-fix)"
                            if is_clean_success:
                                print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_autofix} (Fixed successfully)")
                                passed_count += 1
                            else:
                                print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_autofix}: Expected CLEAN, but {fail_reason}.")
                                errors.append(f"{target_dir.name}/{test_name_autofix} ({fail_reason})")
                                mismatched_count += 1

            # --- 4. 各種 Autofix / Auto-cleanup 確認 ---
            autofix_rules = ["ANN0190", "ANN0345", "ANN1025", "ANN1050", "ANN1130", "ANN1230", "ANN1250", "ANN1270", "ANN2020", "ANN3290", "ANN4100", "ANN4240"]
            rule_names_in_file = [r for r in autofix_rules if r in target_dir.name or r in file_rule_ids]
            
            if rule_names_in_file:
                # fail を期待しているテストケースがあるか確認し、なければスキップ
                has_fails = any(tc["expected_result"] == "fail" for tc in test_cases)
                if has_fails:
                    fixed_file_path = target_dir / "fixed" / filename
                    
                    if not fixed_file_path.exists():
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {filename} (Rule: {','.join(rule_names_in_file)} Auto-fix): Expected fixed file, but it is missing.")
                        errors.append(f"{target_dir.name}/{filename} (Fixed file missing for {','.join(rule_names_in_file)})")
                        mismatched_count += 1
                    else:
                        with open(fixed_file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # 修正: entriesファイルの場合は、failが期待されるエントリーのテキストのみを抽出する
                        content_to_check = content
                        if is_entries_level:
                            failed_entries = {tc["filename"].split('[')[-1].strip(']') for tc in test_cases if tc["expected_result"] == "fail"}
                            entry_blocks = []
                            current_block = []
                            current_entry_name = None
                            for line in content.splitlines():
                                cols = line.split('\t')
                                if cols and cols[0].strip() and cols[0].strip() != "COMMON":
                                    if current_entry_name and current_entry_name in failed_entries:
                                        entry_blocks.append("\n".join(current_block))
                                    current_block = []
                                    current_entry_name = cols[0].strip()
                                current_block.append(line)
                            if current_entry_name and current_entry_name in failed_entries:
                                entry_blocks.append("\n".join(current_block))
                            content_to_check = "\n".join(entry_blocks)
                        
                        # 抽出したテキストがある場合のみチェックを実行
                        if content_to_check.strip():
                            is_clean_success = True
                            fail_reason = ""
                            unfixed_items = []

                            # ANN0190: ヘッダー行 (Entry Feature Location ...) の除去確認
                            if "ANN0190" in rule_names_in_file:
                                # 行頭が Entry で始まり、その後に Feature 等が続く行が「残っていたら」エラーとする
                                if re.search(r'^Entry\s+Feature', content_to_check, re.IGNORECASE | re.MULTILINE):
                                    unfixed_items.append("ANN0190 (Header line not removed)")
                                
                            # ANN0345: 'nature' -> 'Nature' (ANN0345_2.fail.ann のみ確認)
                            if "ANN0345" in rule_names_in_file and filename == "ANN0345_2.fail.ann":
                                if re.search(r'journal\s+nature\b', content_to_check): unfixed_items.append("ANN0345 ('nature' not changed)")
                                if not re.search(r'journal\s+Nature\b', content_to_check): unfixed_items.append("ANN0345 (Expected 'Nature' not found)")                                                            
                            # ANN1025: 'house mouse' -> 'Mus musculus'
                            if "ANN1025" in rule_names_in_file:
                                if re.search(r'organism\s+house mouse', content_to_check): unfixed_items.append("ANN1025 (house mouse not changed)")
                                if not re.search(r'organism\s+Mus musculus', content_to_check): unfixed_items.append("ANN1025 (Expected Mus musculus not found)")
                                    
                            # ANN1050: transl_table '10' -> '1'
                            if "ANN1050" in rule_names_in_file:
                                if re.search(r'transl_table\s+10\b', content_to_check): unfixed_items.append("ANN1050 (transl_table 10 not changed)")
                                if not re.search(r'transl_table\s+1\b', content_to_check): unfixed_items.append("ANN1050 (Expected transl_table 1 not found)")

                            # ANN1130: 2019-01-01 -> 2020-01-01
                            if "ANN1130" in rule_names_in_file:
                                if re.search(r'collection_date\s+2019-01-01', content_to_check): unfixed_items.append("ANN1130 (2019-01-01 not changed)")
                                if not re.search(r'collection_date\s+2020-01-01', content_to_check): unfixed_items.append("ANN1130 (Expected 2020-01-01 not found)")

                            # ANN1230: 2020/01/01 -> 2020-01-01
                            if "ANN1230" in rule_names_in_file:
                                if re.search(r'collection_date\s+2020/01/01', content_to_check): unfixed_items.append("ANN1230 (2020/01/01 not changed)")
                                if not re.search(r'collection_date\s+2020-01-01', content_to_check): unfixed_items.append("ANN1230 (Expected 2020-01-01 not found)")

                            # ANN1250: japan: -> Japan:
                            if "ANN1250" in rule_names_in_file:
                                if re.search(r'geo_loc_name\s+japan:', content_to_check): unfixed_items.append("ANN1250 ('japan:' not changed)")
                                if not re.search(r'geo_loc_name\s+Japan:', content_to_check): unfixed_items.append("ANN1250 (Expected 'Japan:' not found)")

                            # ANN1270: 35.11897899999 -> 35.11897899
                            if "ANN1270" in rule_names_in_file:
                                if re.search(r'lat_lon\s+35\.11897899999', content_to_check): unfixed_items.append("ANN1270 (Rounding not applied)")
                                if not re.search(r'lat_lon\s+35\.11897899 N', content_to_check): unfixed_items.append("ANN1270 (Expected rounded lat_lon not found)")

                            # ANN2020: join(30..40, 50..100) -> join(30..40,50..100)
                            if "ANN2020" in rule_names_in_file:
                                if re.search(r'join\(30\.\.40,\s+50\.\.100\)', content_to_check): unfixed_items.append("ANN2020 (Space in join not removed)")
                                if not re.search(r'join\(30\.\.40,50\.\.100\)', content_to_check): unfixed_items.append("ANN2020 (Expected joined string not found)")

                            # ANN3290: 大文字小文字のAutofix (例: genomic dna -> genomic DNA)
                            if "ANN3290" in rule_names_in_file:
                                if re.search(r'mol_type\s+genomic dna\b', content_to_check):
                                    unfixed_items.append("ANN3290 ('genomic dna' not changed)")
                                if not re.search(r'mol_type\s+genomic DNA\b', content_to_check):
                                    unfixed_items.append("ANN3290 (Expected 'genomic DNA' not found)")
                                    
                            # ANN4100: DDBJ: -> INSD:
                            if "ANN4100" in rule_names_in_file:
                                if re.search(r'inference\s+similar to DNA sequence:DDBJ:', content_to_check): unfixed_items.append("ANN4100 ('DDBJ:' not changed)")
                                if not re.search(r'inference\s+similar to DNA sequence:INSD:', content_to_check): unfixed_items.append("ANN4100 (Expected 'INSD:' not found)")

                            # ANN4240: <2..100 -> <1..100, 10..>119 -> 10..>120 etc.
                            if "ANN4240" in rule_names_in_file:
                                if re.search(r'<2\.\.100', content_to_check) or re.search(r'<3\.\.100', content_to_check): unfixed_items.append("ANN4240 (<2..100 or <3..100 not changed)")
                                if re.search(r'10\.\.>119\b', content_to_check) or re.search(r'10\.\.>99\b', content_to_check): unfixed_items.append("ANN4240 (10..>119 or 10..>99 not changed)")
                                if re.search(r'<202\.\.290', content_to_check): unfixed_items.append("ANN4240 (<202..290 not changed)")
                                
                            if unfixed_items:
                                is_clean_success = False
                                fail_reason = "Autofix verification failed: " + ", ".join(unfixed_items)
                                
                            test_name_autofix = f"{filename} (Rule: {','.join(rule_names_in_file)} Auto-fix)"
                            if is_clean_success:
                                print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_autofix} (Fixed successfully)")
                                passed_count += 1
                            else:
                                print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_autofix}: Expected CLEAN, but {fail_reason}.")
                                errors.append(f"{target_dir.name}/{test_name_autofix} ({fail_reason})")
                                mismatched_count += 1
                                                                                                                                            
            # --- 4. 6000番台翻訳結果 (AXS6030等) の DDBJツール比較 ---
            is_6000_series = target_dir.parent.name == "6000-6999" or any(re.search(r'6\d{3}', r) for r in file_rule_ids) and not any("6820" in r for r in file_rule_ids)
            
            if is_6000_series:
                fasta_path = ann_path.with_suffix('.fasta')
                aa_dir = target_dir / "aa"
                
                current_faa_path = aa_dir / f"AA_{file_stem}.faa"
                ddbj_faa_path = aa_dir / f"AA_{file_stem}.tc.faa"
                
                if fasta_path.exists():
                    aa_dir.mkdir(exist_ok=True)
                    tc_cmd = ["transChecker.sh", "-x", str(ann_path), "-s", str(fasta_path), "-o", str(ddbj_faa_path)]
                    
                    try:
                        # check=True を外し、エラー終了コードでも処理を継続させる
                        tc_result = subprocess.run(tc_cmd, capture_output=True, text=True)
                        
                        # ファイルが生成されていなければエラーの詳細を表示してスキップ
                        if not ddbj_faa_path.exists():
                            print(f"  [{Colors.WARNINGYEL}WARNING{Colors.ENDC}] transChecker.sh failed to generate .tc.faa for {filename}.")
                            print(f"    [Exit Code]: {tc_result.returncode}")
                            if tc_result.stderr:
                                print(f"    [STDERR]: {tc_result.stderr.strip()}")
                            elif tc_result.stdout:
                                print(f"    [STDOUT]: {tc_result.stdout.strip()}")
                            continue

                    except FileNotFoundError:
                        print(f"  [{Colors.FAILRED}ERROR{Colors.ENDC}] transChecker.sh not found in PATH.")
                        continue
                    except Exception as e:
                        print(f"  [{Colors.FAILRED}ERROR{Colors.ENDC}] Unexpected error running transChecker.sh: {e}")
                        continue

                    test_name_trans = f"{filename} (Translation FASTA Match)"

                    if not current_faa_path.exists():
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_trans}: Current tool's .faa output is missing ({current_faa_path.name})")
                        errors.append(f"{target_dir.name}/{test_name_trans} (Current tool .faa missing)")
                        mismatched_count += 1
                    else:
                        # 両方のFASTAが存在する場合は比較を実行
                        is_match, result_msg = compare_fasta(str(ddbj_faa_path), str(current_faa_path))
                        
                        if is_match:
                            # 成功時にも result_msg (スキップ情報など) を画面に出力する
                            print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_trans} - {result_msg}")
                            passed_count += 1
                        else:
                            print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_trans}: {result_msg}")
                            errors.append(f"{target_dir.name}/{test_name_trans} ({result_msg})")
                            mismatched_count += 1
                                                        
    print("\n" + "="*50)
    print(f"E2E Test Summary: {Colors.OKGREEN}{passed_count} Matched{Colors.ENDC}, {Colors.FAILRED}{mismatched_count} Mismatched{Colors.ENDC}")
    if errors:
        print("Mismatched Tests:")
        for e in errors:
            print(f"  - {e}")
    print("="*50)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run E2E tests for seq_validator.")
    parser.add_argument("rule_id", nargs="?", default=None, help="Target Rule ID to test (e.g. ANN0350)")
    args = parser.parse_args()

    run_e2e_tests(target_rule_id=args.rule_id)