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
# モード時にスキップされるべきルールの動的取得 ＋ ハードコード除外設定
# ==============================================================================
def get_skipped_rules(skip_db=False, skip_ncbi=False, skip_auth=False):
    skipped_rules = set()
    
    # --- 1. 動的取得 (既存ロジック) ---
    try:
        from apps.ddbj.validator import Validator
        from apps.ddbj.context import ValidationContext
        val = Validator(ValidationContext(skip_db=False, skip_ncbi=False, skip_auth=False))
        for r in val.active_rules:
            # マスタークラス（または単一ルール）がスキップ条件に合致するか判定
            should_skip = (skip_db and getattr(r, 'requires_rdb', False)) or \
                          (skip_ncbi and getattr(r, 'requires_network', False)) or \
                          (skip_auth and (getattr(r, 'requires_auth', False) or getattr(r, 'auth_required', False)))
            
            if should_skip:
                skipped_rules.add(r.rule_id)
                if hasattr(r, 'sub_rules') and isinstance(r.sub_rules, list):
                    skipped_rules.update(r.sub_rules)
                    
    except Exception as e:
        print(f"Warning: Failed to fetch skipped rules dynamically: {e}")

    # --- 2. ハードコードによる強制除外ロジック ---
    
    # [A] RDB必須ルール (Localモード、NCBI APIモードの両方でスキップ)
    if skip_db:
        # DRA/BioSample等DB必須ルール
        rdb_hardcoded = [
            "ANN0500", "ANN0510", "ANN0520", "ANN0530", "ANN0540", "ANN0550", 
            "ANN1130"
        ]
        skipped_rules.update(rdb_hardcoded)
        
    # [B] Taxonomy / ネットワーク必須ルール 
    # (NCBI APIが使えない Localモード のみスキップ。NCBI APIモードではスキップしない)
    if skip_ncbi:
        tax_hardcoded = [
            "ANN1025", 
            "ANN1430", "ANN1440", "ANN1450", "ANN1460", 
            "ANN1810", 
            "ANN4210", "ANN4240"
        ]
        skipped_rules.update(tax_hardcoded)
        
    return skipped_rules

class Colors:
    OKGREEN = '\033[92m'
    OKCYAN = '\033[96m'
    OKBLUE = '\033[94m'
    FAILRED = '\033[91m'
    WARNINGYEL = '\033[93m'
    ENDC = '\033[0m'

# ==============================================================================
# 期待値の抽出関数群
# ==============================================================================
def extract_feature_expectations(ann_path):
    with open(ann_path, 'r', encoding='utf-8') as f:
        for line in f:
            cols = line.rstrip('\n').split('\t')
            if len(cols) >= 5:
                qualifier = cols[3].strip()
                value = cols[4].strip()
                if qualifier == "note":
                    if re.search(r'\bfail\b', value, re.IGNORECASE): return "fail"
                    if re.search(r'\bautofix\b', value, re.IGNORECASE): return "autofix"
                    if re.search(r'\bpass\b', value, re.IGNORECASE): return "pass"
    return None

def extract_entry_expectations(ann_path):
    expectations = {}
    current_entry = None
    
    with open(ann_path, 'r', encoding='utf-8') as f:
        for line in f:
            cols = line.rstrip('\n').split('\t')
            if not cols: continue
                
            if cols[0].strip() and cols[0] != "COMMON":
                current_entry = cols[0].strip()
                if current_entry not in expectations:
                    expectations[current_entry] = {}
                    
            if current_entry and len(cols) >= 5:
                qualifier = cols[3].strip()
                value = cols[4].strip()
                if qualifier == "note":
                    # cleanup, clean, autocleanup等を除外し、autofixに限定
                    matches = re.findall(r'([A-Z]{3}\d+)\s+(pass|fail|autofix)', value, re.IGNORECASE)
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
                if re.match(r'^[A-Z0-9]+$', rule_id) and level in ["ERR", "WAR", "FAT", "INFO", "AUTO-CLEANUP"]:
                    entry_name = parts[2]
                    results[current_file].add(rule_id)
                    if entry_name not in results_by_entry[current_file]:
                        results_by_entry[current_file][entry_name] = set()
                    results_by_entry[current_file][entry_name].add(rule_id)
                
    return results, results_by_entry

# ==============================================================================
# ファイル直接比較 (Diff)
# ==============================================================================
def compare_text_files(expected_path, actual_path):
    if not expected_path.exists():
        return False, "Golden file not found."
    if not actual_path.exists():
        return False, "Actual file not found."

    with open(expected_path, 'r', encoding='utf-8') as f:
        expected_lines = [line.rstrip('\r\n') for line in f.readlines()]
    with open(actual_path, 'r', encoding='utf-8') as f:
        actual_lines = [line.rstrip('\r\n') for line in f.readlines()]

    while expected_lines and expected_lines[-1] == '':
        expected_lines.pop()
    while actual_lines and actual_lines[-1] == '':
        actual_lines.pop()

    if len(expected_lines) != len(actual_lines):
        return False, f"Line count mismatch (Expected: {len(expected_lines)}, Actual: {len(actual_lines)})"

    for i, (exp, act) in enumerate(zip(expected_lines, actual_lines)):
        if exp != act:
            if exp.strip() == act.strip() and "".join(exp.split()) == "".join(act.split()):
                continue 
            return False, f"Diff at line {i+1}: Expected '{exp}' vs Actual '{act}'"

    return True, "Match"

def compare_fasta(fasta_ddbj, fasta_tool, ignore_ids=None):
    if ignore_ids is None: ignore_ids = set()
    if not HAS_BIOPYTHON: return False, "Biopython is not installed."
        
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
    
    if only_in_ddbj: error_msgs.append(f"Missing in current tool: {list(only_in_ddbj)[:3]}")
    if only_in_tool: error_msgs.append(f"Unexpected in current tool: {list(only_in_tool)[:3]}")

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
        if skipped_msgs: success_msg += f" | {', '.join(skipped_msgs)}"
        return True, success_msg
    else:
        if skipped_msgs: error_msgs.extend(skipped_msgs)
        return False, " | ".join(error_msgs)


# ==============================================================================
# メインテストランナー
# ==============================================================================
def run_e2e_tests(target_rule_id=None, mode="online", skip_only=False, docker_image=None):
    if not HAS_BIOPYTHON:
        print(f"{Colors.WARNINGYEL}[WARNING] Biopython is not installed. Amino acid FASTA comparisons will fail.{Colors.ENDC}\n")
        
    skip_db = mode in ["local", "ncbi"]
    skip_ncbi = mode == "local"
    skip_auth = mode == "auth-skip"

    mode_skipped_rules = get_skipped_rules(skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)

    # シェルスクリプトではなく、Pythonとmain.pyのパスを指定
    python_bin = project_root / ".venv" / "bin" / "python"
    main_py = project_root / "main.py"
    
    if not docker_image:
        if not python_bin.exists():
            print(f"{Colors.FAILRED}Error: Python executable not found at {python_bin}.{Colors.ENDC}")
            sys.exit(1)
        if not main_py.exists():
            print(f"{Colors.FAILRED}Error: {main_py} not found.{Colors.ENDC}")
            sys.exit(1)

    target_dirs = sorted([d for d in tests_dir.glob("*/*") if d.is_dir() and any(d.glob("*.ann"))])
    target_rules_set = set(target_rule_id.split('-')) if target_rule_id else set()

    if target_rule_id:
        target_dirs = [d for d in target_dirs if target_rule_id in d.name or any(r in d.name for r in target_rules_set)]
    elif skip_only:
        target_dirs = [d for d in target_dirs if any(r in mode_skipped_rules for r in d.name.split('-'))]

    passed_count = 0
    mismatched_count = 0
    errors = []
    skipped_count = 0
    not_skipped_errors = []
    
    autofix_fixed = 0
    autofix_not_fixed = 0
    autofix_errors = []
    
    autocleanup_cleaned = 0
    autocleanup_not_cleaned = 0
    autocleanup_errors = []
    
    translation_passed = 0
    translation_mismatched = 0
    translation_errors = []
    
    if not target_dirs:
        return {
            "passed": 0, "mismatched": 0, "errors": [], "skipped": 0, "not_skipped_errors": [],
            "autofix_fixed": 0, "autofix_not_fixed": 0, "autofix_errors": [],
            "autocleanup_cleaned": 0, "autocleanup_not_cleaned": 0, "autocleanup_errors": [],
            "translation_passed": 0, "translation_mismatched": 0, "translation_errors": []
        }

    msg = f"\nStarting E2E Tests via {'Docker (' + docker_image + ')' if docker_image else 'Shell'}"
    if target_rule_id: msg += f" for Rule(s): {target_rule_id}"
    
    if mode == "local":
        msg += f" [{Colors.WARNINGYEL}LOCAL MODE" + (" (SKIP ONLY)" if skip_only else " (FULL TEST)") + f"{Colors.ENDC}]"
    elif mode == "ncbi":
        msg += f" [{Colors.OKCYAN}NCBI API MODE" + (" (SKIP ONLY)" if skip_only else " (FULL TEST)") + f"{Colors.ENDC}]"
    elif mode == "auth-skip":
        msg += f" [{Colors.OKBLUE}AUTH SKIP MODE" + (" (SKIP ONLY)" if skip_only else " (FULL TEST)") + f"{Colors.ENDC}]"
    else:
        msg += f" [{Colors.OKGREEN}ONLINE MODE{Colors.ENDC}]"
    print(f"{msg}...")

    for target_dir in target_dirs:
        print(f"Testing directory: {target_dir.relative_to(project_root)}")

        if docker_image:
            import os
            rel_target = target_dir.relative_to(project_root)
            cmd = [
                "docker", "run", "--rm",
                "-u", f"{os.getuid()}:{os.getgid()}",
                "-v", f"{project_root}:/work",
                docker_image,
                "ddbj", str(rel_target), "-f"
            ]
        else:
            # .venv/bin/python main.py ddbj [target_dir] -f で実行
            cmd = [str(python_bin), str(main_py), "ddbj", str(target_dir), "-f"]
        
        if mode == "local": 
            cmd.append("-l" if docker_image else "--local")
        elif mode == "ncbi": 
            cmd.append("-n" if docker_image else "--ncbi-api")
        elif mode == "auth-skip": 
            cmd.append("--skip-auth")
            
        subprocess.run(cmd, capture_output=True, text=True)
                
        report_path = target_dir / "validation_report_details.txt"
        if not report_path.exists():
            print(f"{Colors.FAILRED}[ERROR]{Colors.ENDC} Details report not generated: {report_path}")
            continue

        triggered_rules_by_file, triggered_rules_by_entry = parse_details_report(report_path)

        for ann_path in target_dir.glob("*.ann"):
            filename = ann_path.name
            file_stem = ann_path.stem 

            if file_stem.endswith("_sub"): continue
                            
            parts = filename.split('.')
            is_file_level = len(parts) >= 3 and parts[-2] in ["pass", "fail", "autofix", "cleanup"]
            is_entries_level = "entries" in parts
            
            # [修正] ファイル名から正確にルールID部分だけを抽出
            file_rule_ids = parts[0].split('_')[0].split('-')
            
            if target_rule_id and not any(r in target_rules_set for r in file_rule_ids) and target_dir.name != target_rule_id:
                continue
            
            test_cases = []
            
            if not is_entries_level:
                expected_result = parts[-2] if is_file_level else extract_feature_expectations(ann_path)
                if expected_result:
                    actual_rules = triggered_rules_by_file.get(file_stem, set())
                    for rule_id in file_rule_ids:
                        if target_rule_id and rule_id not in target_rules_set and target_dir.name != target_rule_id: continue
                        test_cases.append({
                            "filename": filename, "rule_id": rule_id, 
                            "expected_result": expected_result, "rule_triggered": rule_id in actual_rules
                        })
            else:
                entry_expectations = extract_entry_expectations(ann_path)
                file_triggered_entries = triggered_rules_by_entry.get(file_stem, {})
                for entry_name, rules in entry_expectations.items():
                    for rule_id, expected_result in rules.items():
                        if target_rule_id and rule_id not in target_rules_set and target_dir.name != target_rule_id: continue
                        entry_actual_rules = file_triggered_entries.get(entry_name, set())
                        global_rules = file_triggered_entries.get("ALL", set()).union(file_triggered_entries.get("COMMON", set()))
                        test_cases.append({
                            "filename": f"{filename} [{entry_name}]", "rule_id": rule_id, 
                            "expected_result": expected_result, "rule_triggered": (rule_id in entry_actual_rules) or (rule_id in global_rules)
                        })

            test_cases.sort(key=lambda x: (x["filename"], x["rule_id"]))
            for tc in test_cases:
                tc_filename, tc_rule_id = tc["filename"], tc["rule_id"]
                tc_expected_result, tc_rule_triggered = tc["expected_result"], tc["rule_triggered"]
                test_name = f"{tc_filename} (Rule: {tc_rule_id})"

                # ==============================================================
                # ANN1810_2.fail に対する個別ハードコード除外
                # LocalモードではTaxonomyが引けず発火しないのが正仕様のため、テストをスキップ
                # ==============================================================
                if mode == "local" and tc_rule_id == "ANN1810" and "ANN1810_2" in tc_filename:
                    continue
                    
                if skip_only and tc_rule_id not in mode_skipped_rules:
                    continue

                if tc_rule_id in mode_skipped_rules:
                    # スキップされるべきルールが発火していないかを検証する
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected to be SKIPPED, but it TRIGGERED.")
                        errors.append(f"[{tc_rule_id}] {target_dir.name}/{test_name} (Expected SKIP)")
                        not_skipped_errors.append(f"[{tc_rule_id}] {target_dir.name}/{test_name}")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Skipped{Colors.ENDC}]        {test_name} (Correctly Skipped)")
                        skipped_count += 1
                    continue
                
                if tc_expected_result == "pass":
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected PASS, but rule triggered.")
                        errors.append(f"[{tc_rule_id}] {target_dir.name}/{test_name} (Expected PASS)")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name} (No error triggered)")
                        passed_count += 1
                else:
                    if not tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected rule to trigger, but it did NOT.")
                        errors.append(f"[{tc_rule_id}] {target_dir.name}/{test_name} (Expected to trigger)")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name} (Error correctly triggered)")
                        passed_count += 1

            if not skip_only:
                aa_dir = target_dir / "aa"
                current_faa_path = aa_dir / f"AA_{file_stem}.faa"
                ddbj_faa_path = aa_dir / f"AA_{file_stem}.tc.faa"
                fasta_path = ann_path.with_suffix('.fasta')
                
                if aa_dir.exists() and current_faa_path.exists() and fasta_path.exists():
                    tc_cmd = ["transChecker.sh", "-x", str(ann_path), "-s", str(fasta_path), "-o", str(ddbj_faa_path)]
                    try:
                        subprocess.run(tc_cmd, capture_output=True, text=True)
                    except Exception:
                        pass

                    if ddbj_faa_path.exists():
                        test_name_trans = f"{filename} (Translation FASTA Match)"
                        rule_prefix = f"[{','.join(file_rule_ids)}]" if file_rule_ids else ""
                        
                        is_match, result_msg = compare_fasta(str(ddbj_faa_path), str(current_faa_path))
                        if is_match:
                            print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_trans} - {result_msg}")
                            translation_passed += 1
                        else:
                            print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_trans}: {result_msg}")
                            translation_errors.append(f"{rule_prefix} {target_dir.name}/{test_name_trans} ({result_msg})")
                            translation_mismatched += 1
                            
        if not skip_only:
            expected_dir = target_dir / "expected"
            if expected_dir.exists() and expected_dir.is_dir():
                for golden_file in expected_dir.glob("*"):
                    if not golden_file.is_file(): continue
                    
                    # [修正] ".entries.ann" などを取り除いてからハイフン等で分割する (ANN4240のMismtachを防ぐため)
                    base_name = golden_file.name.split('.')[0]
                    file_rule_ids = base_name.split('_')[0].split('-')
                    
                    if target_rule_id and not any(r in target_rules_set for r in file_rule_ids) and target_dir.name != target_rule_id:
                        continue
                        
                    # [修正] このファイルに含まれるルールがスキップ対象の場合、Autofixのファイル比較処理自体を行わない
                    if any(r in mode_skipped_rules for r in file_rule_ids):
                        continue
                        
                    # ファイル名で厳密に cleanup と autofix を判定
                    is_cleanup = "cleanup" in golden_file.name.lower()
                    is_autofix = "autofix" in golden_file.name.lower()
                    
                    if is_cleanup:
                        label_clean = "cleanup"
                        err_list = autocleanup_errors
                    else:
                        label_clean = "auto-fix"
                        err_list = autofix_errors
                    
                    test_name_golden = f"{golden_file.name} ({label_clean} Match)"
                    
                    fixed_file = target_dir / "fixed" / golden_file.name
    
                    if not fixed_file.exists():
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_golden}: Actual fixed file is missing ({fixed_file.name}).")
                        err_msg = f"[{','.join(file_rule_ids)}] {target_dir.name}/{test_name_golden} (Fixed file missing: {fixed_file.name})"
                        errors.append(err_msg)
                        err_list.append(err_msg)
                        mismatched_count += 1
                        if is_cleanup: autocleanup_not_cleaned += 1
                        else: autofix_not_fixed += 1
                    else:
                        is_match, diff_msg = compare_text_files(golden_file, fixed_file)
                        if not is_match:
                            print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_golden}: Diff error -> {diff_msg}")
                            err_msg = f"[{','.join(file_rule_ids)}] {target_dir.name}/{test_name_golden} ({diff_msg})"
                            errors.append(err_msg)
                            err_list.append(err_msg)
                            mismatched_count += 1
                            if is_cleanup: autocleanup_not_cleaned += 1
                            else: autofix_not_fixed += 1
                        else:
                            print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_golden} (Perfect match)")
                            passed_count += 1
                            if is_cleanup: autocleanup_cleaned += 1
                            else: autofix_fixed += 1

    return {
        "passed": passed_count,
        "mismatched": mismatched_count,
        "errors": errors,
        "skipped": skipped_count,
        "not_skipped_errors": not_skipped_errors,
        "autofix_fixed": autofix_fixed,
        "autofix_not_fixed": autofix_not_fixed,
        "autofix_errors": autofix_errors,
        "autocleanup_cleaned": autocleanup_cleaned,
        "autocleanup_not_cleaned": autocleanup_not_cleaned,
        "autocleanup_errors": autocleanup_errors,
        "translation_passed": translation_passed,
        "translation_mismatched": translation_mismatched,
        "translation_errors": translation_errors
    }

def print_header(title, color):
    print(f"\n{color}============================================================{Colors.ENDC}")
    print(f"{color}  {title.ljust(56)}{Colors.ENDC}")
    print(f"{color}============================================================{Colors.ENDC}")

def print_summary(results_list, docker_image=None):
    print("\n" + "="*80)
    if docker_image:
        print(f" {Colors.OKGREEN}★ FINAL E2E TEST SUMMARY (DOCKER: {docker_image}) ★{Colors.ENDC} ")
    else:
        print(f" {Colors.OKGREEN}★ FINAL E2E TEST SUMMARY (SHELL) ★{Colors.ENDC} ")
    print("="*80)
    
    for title, res, color in results_list:
        print(f"\n{color}[ {title} ]{Colors.ENDC}")
        passed_label = "Matched" if title == "ONLINE MODE RESULTS" else "Matched (Normal Rules)"
        print(f"  {passed_label}: {res['passed']}")
        print(f"  Mismatched:             {Colors.FAILRED if res['mismatched'] > 0 else Colors.OKGREEN}{res['mismatched']}{Colors.ENDC}")
        
        if 'autofix_fixed' in res:
            print(f"  Autofix:                {Colors.OKGREEN}{res['autofix_fixed']} fixed{Colors.ENDC} / {Colors.FAILRED if res['autofix_not_fixed'] > 0 else Colors.OKGREEN}{res['autofix_not_fixed']} not fixed{Colors.ENDC}")
            if res.get('autofix_errors'):
                for e in res['autofix_errors']:
                    print(f"    - {e}")
                    
            print(f"  Auto-cleanup:           {Colors.OKGREEN}{res['autocleanup_cleaned']} cleaned{Colors.ENDC} / {Colors.FAILRED if res['autocleanup_not_cleaned'] > 0 else Colors.OKGREEN}{res['autocleanup_not_cleaned']} not cleaned{Colors.ENDC}")
            if res.get('autocleanup_errors'):
                for e in res['autocleanup_errors']:
                    print(f"    - {e}")

            if 'translation_passed' in res and (res['translation_passed'] > 0 or res['translation_mismatched'] > 0):
                print(f"  AA Translation:         {Colors.OKGREEN}{res['translation_passed']} matched{Colors.ENDC} / {Colors.FAILRED if res['translation_mismatched'] > 0 else Colors.OKGREEN}{res['translation_mismatched']} mismatched{Colors.ENDC}")
                if res.get('translation_errors'):
                    for e in res['translation_errors']:
                        print(f"    - {e}")

        general_errors = [e for e in res.get('errors', []) 
                          if e not in res.get('autofix_errors', []) 
                          and e not in res.get('autocleanup_errors', [])
                          and e not in res.get('translation_errors', [])]
                          
        if general_errors:
            print("  General Errors:")
            for e in general_errors:
                print(f"    - {e}")
                
        if title != "ONLINE MODE RESULTS":
            print(f"  Expectedly Skipped:     {Colors.OKGREEN}{res['skipped']}{Colors.ENDC}")
            print(f"  Not Skipped (Error!):   {Colors.FAILRED if len(res['not_skipped_errors']) > 0 else Colors.OKGREEN}{len(res['not_skipped_errors'])}{Colors.ENDC}")
            if res['not_skipped_errors']:
                for e in res['not_skipped_errors']:
                    print(f"    - {e}")
                    
    print("="*80 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run E2E tests for seq_validator.")
    parser.add_argument("rule_id", nargs="?", default=None, help="Target Rule ID to test (e.g. ANN0350)")
    
    parser.add_argument(
        "-d", "--docker", 
        dest="docker_image", 
        default=None, 
        help="Run tests using the specified Docker image (e.g., bsi-validator:0.1.0-beta)"
    )
    
    parser.add_argument(
        "--mode", 
        nargs="+", 
        choices=["online", "local", "local-skip", "ncbi", "ncbi-skip", "auth-skip", "all"], 
        default=["online", "local-skip", "ncbi-skip", "auth-skip"], 
        help="Execution mode(s). Multiple modes can be specified."
    )
    args = parser.parse_args()

    modes = args.mode

    if args.docker_image and modes == ["online", "local-skip", "ncbi-skip", "auth-skip"]:
        modes = ["local", "ncbi", "auth-skip"]

    if "all" in modes:
        if args.docker_image:
            modes = ["local", "ncbi", "auth-skip"]
        else:
            modes = ["online", "local", "ncbi", "auth-skip"]

    results_to_print = []
    
    if "online" in modes:
        print_header("PHASE 1: ONLINE MODE TESTING (Standard Pass/Fail Check)", Colors.OKGREEN)
        res_online = run_e2e_tests(target_rule_id=args.rule_id, mode="online", docker_image=args.docker_image)
        results_to_print.append(("ONLINE MODE RESULTS", res_online, Colors.OKGREEN))

    if "local" in modes:
        print_header("PHASE 2: LOCAL MODE TESTING (Full test: Normal + Skip)", Colors.WARNINGYEL)
        res_local = run_e2e_tests(target_rule_id=args.rule_id, mode="local", skip_only=False, docker_image=args.docker_image)
        results_to_print.append(("LOCAL MODE RESULTS (FULL TEST)", res_local, Colors.WARNINGYEL))
        
    elif "local-skip" in modes:
        print_header("PHASE 2: LOCAL MODE TESTING (Skip Verification Only)", Colors.WARNINGYEL)
        res_local = run_e2e_tests(target_rule_id=args.rule_id, mode="local", skip_only=True, docker_image=args.docker_image)
        results_to_print.append(("LOCAL MODE RESULTS (SKIP ONLY)", res_local, Colors.WARNINGYEL))

    if "ncbi" in modes:
        print_header("PHASE 3: NCBI API MODE TESTING (Full test: Normal + Skip)", Colors.OKCYAN)
        res_ncbi = run_e2e_tests(target_rule_id=args.rule_id, mode="ncbi", skip_only=False, docker_image=args.docker_image)
        results_to_print.append(("NCBI API MODE RESULTS (FULL TEST)", res_ncbi, Colors.OKCYAN))
        
    elif "ncbi-skip" in modes:
        print_header("PHASE 3: NCBI API MODE TESTING (Skip Verification Only)", Colors.OKCYAN)
        res_ncbi = run_e2e_tests(target_rule_id=args.rule_id, mode="ncbi", skip_only=True, docker_image=args.docker_image)
        results_to_print.append(("NCBI API MODE RESULTS (SKIP ONLY)", res_ncbi, Colors.OKCYAN))

    if "auth-skip" in modes:
        print_header("PHASE 4: AUTH SKIP MODE TESTING (Skip Verification Only)", Colors.OKBLUE)
        res_auth = run_e2e_tests(target_rule_id=args.rule_id, mode="auth-skip", skip_only=True, docker_image=args.docker_image)
        results_to_print.append(("AUTH SKIP MODE RESULTS (SKIP ONLY)", res_auth, Colors.OKBLUE))

    print_summary(results_to_print, docker_image=args.docker_image)