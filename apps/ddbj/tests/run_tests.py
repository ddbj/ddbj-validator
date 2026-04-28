#!/usr/bin/env python3

import sys
import subprocess
import re
import argparse
from pathlib import Path

# ==============================================================================
# プロジェクトルートをPythonのパスに追加 (モジュールインポートエラー回避)
# ==============================================================================
tests_dir = Path(__file__).resolve().parent
project_root = tests_dir.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from Bio import SeqIO
    HAS_BIOPYTHON = True
except ImportError:
    HAS_BIOPYTHON = False

# ==============================================================================
# LOCAL時にスキップされるべきルールの動的取得
# ==============================================================================
def get_local_skipped_rules():
    """
    Validatorを初期化して、requires_rdb=True または requires_network=True
    が設定されているルールと、そのサブルールをすべて抽出してセットで返す。
    """
    try:
        from apps.ddbj.validator import Validator
        from apps.ddbj.context import ValidationContext
        val = Validator(ValidationContext(skip_db=False, skip_ncbi=False))
        skipped_rules = set()
        for r in val.active_rules:
            if getattr(r, 'requires_rdb', False) or getattr(r, 'requires_network', False):
                skipped_rules.add(r.rule_id)
                # サブルール (ANN0500〜やANN1430等) も展開して追加
                if hasattr(r, 'sub_rules'):
                    skipped_rules.update(r.sub_rules)
        return skipped_rules
    except Exception as e:
        print(f"Warning: Failed to fetch local skipped rules: {e}")
        return set()

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
            
            file_match = re.match(r'^\d+\.\s+(.+)', line)
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
        seq_ddbj = str(dict_ddbj[seq_id].seq).replace('/', '').strip()
        seq_tool = str(dict_tool[seq_id].seq).replace('/', '').strip()

        if '?' in seq_ddbj or '?' in seq_tool:
            skipped_msgs.append(f"[{seq_id}] Skipped (Contains '?')")
            continue
            
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
                        
def run_e2e_tests(target_rule_id=None, is_local=False):
    if not HAS_BIOPYTHON:
        print(f"{Colors.WARNINGYEL}[WARNING] Biopython is not installed. 6000-series amino acid fasta comparisons will fail.{Colors.ENDC}\n")

    # LOCAL時にスキップされるべきルールの取得
    local_skipped_rules = get_local_skipped_rules()

    validator_sh = project_root / "bsi-validator.sh"

    if not validator_sh.exists():
        print(f"{Colors.FAILRED}Error: {validator_sh} not found.{Colors.ENDC}")
        sys.exit(1)

    target_dirs = sorted([
        d for d in tests_dir.glob("*/*")
        if d.is_dir() and any(d.glob("*.ann"))
    ])
    
    target_rules_set = set(target_rule_id.split('-')) if target_rule_id else set()

    if target_rule_id:
        target_dirs = [
            d for d in target_dirs 
            if target_rule_id in d.name or any(r in d.name for r in target_rules_set)
        ]

    passed_count = 0
    mismatched_count = 0
    errors = []
    
    # LOCAL専用のスキップ集計
    skipped_count = 0
    not_skipped_errors = []

    if not target_dirs:
        return {"passed": 0, "mismatched": 0, "errors": [], "skipped": 0, "not_skipped_errors": []}

    msg = f"\nStarting E2E Tests via Shell"
    if target_rule_id: msg += f" for Rule(s): {target_rule_id}"
    if is_local: msg += f" [{Colors.WARNINGYEL}LOCAL MODE{Colors.ENDC}]"
    print(f"{msg}...")

    for target_dir in target_dirs:
        print(f"Testing directory: {target_dir.relative_to(project_root)}")
        
        cmd = [str(validator_sh), "ddbj", str(target_dir), "-f"]
        if is_local:
            cmd.append("--local")
            
        result = subprocess.run(cmd, capture_output=True, text=True)
                
        report_path = target_dir / "validation_report_details.txt"
        if not report_path.exists():
            print(f"{Colors.FAILRED}[ERROR]{Colors.ENDC} Details report not generated: {report_path}")
            continue

        triggered_rules_by_file, triggered_rules_by_entry = parse_details_report(report_path)

        for ann_path in target_dir.glob("*.ann"):
            filename = ann_path.name
            file_stem = ann_path.stem 

            if file_stem.endswith("_sub"):
                continue
                            
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

                if not expected_result: continue 

                actual_rules = triggered_rules_by_file.get(file_stem, set())
                
                for rule_id in file_rule_ids:
                    if target_rule_id and rule_id not in target_rules_set and target_dir.name != target_rule_id:
                        continue
                        
                    rule_triggered = rule_id in actual_rules
                    order_map = {"pass": 0, "fail": 1, "clean": 2}
                    sort_order = order_map.get(expected_result, 3)

                    test_cases.append({
                        "filename": filename, "file_stem": file_stem, "rule_id": rule_id,
                        "expected_result": expected_result, "actual_rules": actual_rules,
                        "rule_triggered": rule_triggered, "sort_order": sort_order, "type": "file"
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
                            "filename": f"{filename} [{entry_name}]", "file_stem": file_stem, "rule_id": rule_id,
                            "expected_result": expected_result, "actual_rules": entry_actual_rules,
                            "rule_triggered": rule_triggered, "sort_order": sort_order, "type": "entry"
                        })

            # --- 評価フェーズ ---
            test_cases.sort(key=lambda x: (x["sort_order"], x["filename"], x["rule_id"]))

            for tc in test_cases:
                tc_filename = tc["filename"]
                tc_rule_id = tc["rule_id"]
                tc_expected_result = tc["expected_result"]
                tc_rule_triggered = tc["rule_triggered"]
                test_name = f"{tc_filename} (Rule: {tc_rule_id})"

                # ★ LOCALモード時の特別評価
                if is_local and tc_rule_id in local_skipped_rules:
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}NOT SKIPPED{Colors.ENDC}] {test_name}: Triggered in LOCAL mode (It should be skipped!).")
                        not_skipped_errors.append(f"{target_dir.name}/{test_name} (Triggered in local mode)")
                    else:
                        print(f"  [{Colors.OKGREEN}Skipped{Colors.ENDC}]        {test_name} (Expectedly skipped in local mode)")
                        skipped_count += 1
                    continue
                
                # 通常の評価
                if tc_expected_result == "pass":
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected PASS, but rule triggered.")
                        errors.append(f"{target_dir.name}/{test_name} (Expected PASS)")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name}")
                        passed_count += 1
                        
                elif tc_expected_result == "fail":
                    if not tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected FAIL, but rule did NOT trigger.")
                        errors.append(f"{target_dir.name}/{test_name} (Expected FAIL)")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name}")
                        passed_count += 1

            # --- 3. Autofix (ANN5270など) の確認 ---
            if target_dir.name == "ANN5270" or target_rule_id == "ANN5270" or "ANN5270" in file_rule_ids:
                if any(tc["expected_result"] == "fail" for tc in test_cases):
                    fixed_file_path = target_dir / "fixed" / filename
                    test_name_autofix = f"{filename} (Rule: ANN5270 Auto-fix)"
                    
                    if not fixed_file_path.exists():
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_autofix}: Expected fixed file, but it is missing.")
                        errors.append(f"{target_dir.name}/{test_name_autofix} (File missing)")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_autofix} (Fixed successfully)")
                        passed_count += 1

            # --- 4. 6000番台翻訳結果の DDBJツール比較 ---
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
                        subprocess.run(tc_cmd, capture_output=True, text=True)
                        if not ddbj_faa_path.exists(): continue
                    except Exception:
                        continue

                    test_name_trans = f"{filename} (Translation FASTA Match)"
                    if not current_faa_path.exists():
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_trans}: Current tool's .faa missing")
                        errors.append(f"{target_dir.name}/{test_name_trans} (.faa missing)")
                        mismatched_count += 1
                    else:
                        is_match, result_msg = compare_fasta(str(ddbj_faa_path), str(current_faa_path))
                        if is_match:
                            print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_trans} - {result_msg}")
                            passed_count += 1
                        else:
                            print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_trans}: {result_msg}")
                            errors.append(f"{target_dir.name}/{test_name_trans} ({result_msg})")
                            mismatched_count += 1

        # --- 5. Submission (across files) レベルのチェック ---
        submission_group = "Submission (across files)"
        actual_cross_rules = triggered_rules_by_file.get(submission_group, set())
        cross_target_rules = [r for r in target_dir.name.split('-') if r in ["ANN0120", "ANN2520"]]
        
        for crule in cross_target_rules:
            if target_rule_id and crule not in target_rules_set and target_dir.name != target_rule_id: continue
                
            has_fails = any("fail" in p.name or "_sub" in p.name for p in target_dir.glob("*.ann"))
            expected_result = "fail" if has_fails else "pass"
            rule_triggered = crule in actual_cross_rules
            test_name = f"{submission_group} (Rule: {crule})"
            
            if expected_result == "fail":
                if not rule_triggered:
                    print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected FAIL, but rule did NOT trigger.")
                    errors.append(f"{target_dir.name}/{test_name}")
                    mismatched_count += 1
                else:
                    print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name}")
                    passed_count += 1
            elif expected_result == "pass":
                if rule_triggered:
                    print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected PASS, but rule triggered.")
                    errors.append(f"{target_dir.name}/{test_name}")
                    mismatched_count += 1
                else:
                    print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name}")
                    passed_count += 1

    return {
        "passed": passed_count,
        "mismatched": mismatched_count,
        "errors": errors,
        "skipped": skipped_count,
        "not_skipped_errors": not_skipped_errors
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run E2E tests for seq_validator.")
    parser.add_argument("rule_id", nargs="?", default=None, help="Target Rule ID to test (e.g. ANN0350)")
    args = parser.parse_args()

    print(f"{Colors.OKGREEN}============================================================{Colors.ENDC}")
    print(f"{Colors.OKGREEN}  PHASE 1: ONLINE MODE TESTING (Standard Pass/Fail Check)   {Colors.ENDC}")
    print(f"{Colors.OKGREEN}============================================================{Colors.ENDC}")
    res_online = run_e2e_tests(target_rule_id=args.rule_id, is_local=False)

    print(f"\n{Colors.WARNINGYEL}============================================================{Colors.ENDC}")
    print(f"{Colors.WARNINGYEL}  PHASE 2: LOCAL MODE TESTING (Skip Verification)           {Colors.ENDC}")
    print(f"{Colors.WARNINGYEL}============================================================{Colors.ENDC}")
    res_local = run_e2e_tests(target_rule_id=args.rule_id, is_local=True)

    # =========================================================
    # 最終結果のサマリー出力
    # =========================================================
    print("\n" + "="*70)
    print(f" {Colors.OKGREEN}★ FINAL E2E TEST SUMMARY ★{Colors.ENDC} ")
    print("="*70)
    
    print(f"\n{Colors.OKGREEN}[ ONLINE MODE RESULTS ]{Colors.ENDC}")
    print(f"  Matched:    {res_online['passed']}")
    print(f"  Mismatched: {Colors.FAILRED if res_online['mismatched'] > 0 else Colors.OKGREEN}{res_online['mismatched']}{Colors.ENDC}")
    if res_online['errors']:
        for e in res_online['errors']:
            print(f"    - {e}")

    print(f"\n{Colors.WARNINGYEL}[ LOCAL MODE RESULTS ]{Colors.ENDC}")
    print(f"  Matched (Normal Rules): {res_local['passed']}")
    print(f"  Mismatched:             {Colors.FAILRED if res_local['mismatched'] > 0 else Colors.OKGREEN}{res_local['mismatched']}{Colors.ENDC}")
    if res_local['errors']:
        for e in res_local['errors']:
            print(f"    - {e}")
            
    print(f"\n  Expectedly Skipped:     {Colors.OKGREEN}{res_local['skipped']}{Colors.ENDC} (DB/Network dependent rules)")
    print(f"  Not Skipped (Error!):   {Colors.FAILRED if len(res_local['not_skipped_errors']) > 0 else Colors.OKGREEN}{len(res_local['not_skipped_errors'])}{Colors.ENDC}")
    if res_local['not_skipped_errors']:
        for e in res_local['not_skipped_errors']:
            print(f"    - {e}")
            
    print("="*70 + "\n")