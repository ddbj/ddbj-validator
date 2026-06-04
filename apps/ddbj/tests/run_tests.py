#!/usr/bin/env python3

import os
import sys
import subprocess
import re
import argparse
import shutil
from pathlib import Path

# .env から変数を読み込むために追加
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
    
    # --- 動的取得 (既存ロジック) ---
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

    # --- ハードコードによる強制除外ロジック ---
    
    # [A] RDB必須ルール (Localモード、NCBI APIモードの両方でスキップ)
    if skip_db:
        # DRA/BioSample等DB必須ルール
        rdb_hardcoded = [
            "ANN0500", "ANN0510", "ANN0520", "ANN0530", "ANN0540", "ANN0550", 
            "ANN1130"
        ]
        skipped_rules.update(rdb_hardcoded)
        
    # [B] Taxonomy / ネットワーク必須ルール 
    if skip_ncbi:
        tax_hardcoded = [
            "ANN1025",
            "ANN1070",
            "ANN1430", "ANN1440", "ANN1450", "ANN1460",
            "ANN1810", 
            "ANN4210", "ANN4240"
        ]
        skipped_rules.update(tax_hardcoded)

    # =========================================================
    # [C] 認証必須ルール (Orchestrator直書きのため手動で追加)
    # =========================================================
    if skip_auth:
        skipped_rules.update(["ANN0422", "ANN0463", "ANN0481"])
        
    return skipped_rules

class Colors:
    OKGREEN = '\033[92m'
    OKCYAN = '\033[96m'
    OKBLUE = '\033[94m'
    FAILRED = '\033[91m'
    WARNINGYEL = '\033[93m'
    ENDC = '\033[0m'

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

# autofix proposal の確認サマリ（外側 proposal dict の old/new/message 等を要約したもの）。
# fixed/ には現れない出力なので、必要なときだけ別途ゴールデン突合する。
CONFIRMATION_SUMMARY_FILENAME = "autofix_confirmation_summary.txt"

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


def get_empty_result():
    return {
        "passed": 0, "mismatched": 0, "errors": [], "skipped": 0, "not_skipped_errors": [],
        "autofix_fixed": 0, "autofix_not_fixed": 0, "autofix_errors": [],
        "autocleanup_cleaned": 0, "autocleanup_not_cleaned": 0, "autocleanup_errors": [],
        "translation_passed": 0, "translation_mismatched": 0, "translation_errors": [],
        "confirmation_passed": 0, "confirmation_mismatched": 0, "confirmation_errors": []
    }

# ==============================================================================
# メインテストランナー
# ==============================================================================
def run_e2e_tests(target_rule_id=None, mode="curator", skip_only=False, docker_image=None, use_pip=False,
                  check_confirmation=False, update_confirmation=False):
    if not HAS_BIOPYTHON:
        print(f"{Colors.WARNINGYEL}[WARNING] Biopython is not installed. Amino acid FASTA comparisons will fail.{Colors.ENDC}\n")
        
    skip_db = mode in ["local", "ncbi"]
    skip_ncbi = mode == "local"
    # 修正: DBスキップ時(local, ncbi)は、自動的に skip_auth も True になるよう変更
    skip_auth = (mode == "auth-skip") or skip_db

    mode_skipped_rules = get_skipped_rules(skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)
        
    auth_check_rules = {"ANN0422", "ANN0463", "ANN0481"}
    
    # モードに応じたルールの絞り込み・スキップ制御
    target_rules_set = set(target_rule_id.split('-')) if target_rule_id else set()

    if mode == "web-app":
        # web-app モードは時間がかかるため、アカウント権限の3ルールのみをターゲットにする
        if not target_rules_set:
            target_rules_set = auth_check_rules
        else:
            target_rules_set = target_rules_set.intersection(auth_check_rules)
            
        if not target_rules_set:
            return get_empty_result()
            
    elif mode == "curator":
        # curator モードではアカウントを指定しないため、この3ルールは意図的にスキップする
        mode_skipped_rules.update(auth_check_rules)

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

    # サブディレクトリ対応: .annファイルが含まれるディレクトリを再帰的にすべて抽出する
    target_dirs = []
    for d in tests_dir.rglob("*"):
        if d.is_dir() and not set(d.parts).intersection({".pytest_cache", "reports", "fixed", "aa", "expected", "__pycache__"}):
            if any(f.is_file() and f.name.endswith(".ann") for f in d.iterdir()):
                target_dirs.append(d)
    target_dirs = sorted(target_dirs)

    if target_rules_set:
        # パスのどこかに target_rules_set に含まれるルール群が含まれていれば対象とする
        target_dirs = [d for d in target_dirs if any(r in d.parts for r in target_rules_set)]
    elif skip_only:
        target_dirs = [d for d in target_dirs if any(r in mode_skipped_rules for r in d.parts)]

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

    confirmation_passed = 0
    confirmation_mismatched = 0
    confirmation_errors = []

    if not target_dirs:
        return get_empty_result()

    # ==============================================================================
    # テスト実行前の一括クリーンアップ
    # ==============================================================================
    print(f"{Colors.OKCYAN}[INFO] Cleaning up previous test artifacts (reports, aa, fixed)...{Colors.ENDC}")
    for target_dir in target_dirs:
        for folder_name in ["reports", "aa", "fixed"]:
            folder_path = target_dir / folder_name
            if folder_path.exists() and folder_path.is_dir():
                shutil.rmtree(folder_path, ignore_errors=True)
    # ==============================================================================

    msg = f"\nStarting E2E Tests via {'Docker (' + docker_image + ')' if docker_image else 'Shell'}"
    if target_rule_id: msg += f" for Rule(s): {target_rule_id}"
    
    if mode == "local":
        msg += f" [{Colors.WARNINGYEL}LOCAL MODE" + (" (SKIP ONLY)" if skip_only else " (FULL TEST)") + f"{Colors.ENDC}]"
    elif mode == "ncbi":
        msg += f" [{Colors.OKCYAN}NCBI API MODE" + (" (SKIP ONLY)" if skip_only else " (FULL TEST)") + f"{Colors.ENDC}]"
    elif mode == "auth-skip":
        msg += f" [{Colors.OKBLUE}AUTH SKIP MODE" + (" (SKIP ONLY)" if skip_only else " (FULL TEST)") + f"{Colors.ENDC}]"
    elif mode == "curator":
        msg += f" [{Colors.OKGREEN}CURATOR MODE (No Account){Colors.ENDC}]"
    elif mode == "web-app":
        msg += f" [{Colors.OKGREEN}WEB APP MODE (Auth Check Only){Colors.ENDC}]"
    print(f"{msg}...")

    for target_dir in target_dirs:
        dir_label = str(target_dir.relative_to(project_root))
        print(f"Testing directory: {dir_label}")

        # --- アカウント指定オプションの解決 (Web Appモードのみ適用) ---
        account_val = None
        if mode == "web-app":
            if target_dir.name.endswith('a'):
                account_val = os.environ.get("ACCOUNT_A")
                if not account_val: print(f"[{Colors.WARNINGYEL}WARN{Colors.ENDC}] Directory ends with 'a', but ACCOUNT_A is not set in .env")
            elif target_dir.name.endswith('b'):
                account_val = os.environ.get("ACCOUNT_B")
                if not account_val: print(f"[{Colors.WARNINGYEL}WARN{Colors.ENDC}] Directory ends with 'b', but ACCOUNT_B is not set in .env")

        if docker_image:
            rel_target = target_dir.relative_to(project_root)
            container_target = f"/work/{rel_target}"
            
            cmd = [
                "docker", "run", "--rm",
                "-u", f"{os.getuid()}:{os.getgid()}",
                "-v", f"{str(project_root)}:/work",
                docker_image
            ]
            
            if mode == "local": 
                cmd.append("--local")
            elif mode == "ncbi": 
                cmd.append("-n")
            elif mode == "auth-skip": 
                cmd.append("--skip-auth")
                
            cmd.extend(["-f", container_target])
            if account_val:
                cmd.extend(["--account", account_val])
            
        elif use_pip:
            cli_cmd = project_root / ".venv" / "bin" / "ddbj-validator"
            
            if not cli_cmd.exists():
                print(f"{Colors.FAILRED}[ERROR] CLI command not found at {cli_cmd}. Did you run 'pip install .' ?{Colors.ENDC}")
                sys.exit(1)
                
            cmd = [str(cli_cmd)]
            
            if mode == "local": 
                cmd.append("--local")
            elif mode == "ncbi": 
                cmd.append("--ncbi-api")
            elif mode == "auth-skip": 
                cmd.append("--skip-auth")
                
            cmd.extend(["-f", str(target_dir)])
            if account_val:
                cmd.extend(["--account", account_val])

        else:
            cmd = [str(python_bin), str(main_py), "ddbj"]
            
            if mode == "local": 
                cmd.append("--local")
            elif mode == "ncbi": 
                cmd.append("--ncbi-api")
            elif mode == "auth-skip": 
                cmd.append("--skip-auth")
                
            cmd.extend(["-f", str(target_dir)])
            if account_val:
                cmd.extend(["--account", account_val])
                        
        # コマンドの実行
        result = subprocess.run(cmd, capture_output=True, text=True)
                
        report_path = target_dir / "reports" / "validation_report_details.txt"
        if not report_path.exists():
            print(f"{Colors.FAILRED}[ERROR]{Colors.ENDC} Details report not generated: {report_path}")
            if result.returncode != 0:
                print(f"{Colors.WARNINGYEL}[DEBUG] STDERR:{Colors.ENDC}\n{result.stderr}")
            continue

        triggered_rules_by_file, triggered_rules_by_entry = parse_details_report(report_path)

        for ann_path in target_dir.glob("*.ann"):
            filename = ann_path.name
            file_stem = ann_path.stem 

            if file_stem.endswith("_sub"): continue
                            
            parts = filename.split('.')
            is_entries_level = "entries" in parts
            
            # --- 複合テスト(and, skip)のファイル名解析 ---
            # 例: ANN0481_4.pass.and.ANN0490.ann または ANN0481_4.fail.skip.ANN0430.ann
            is_composite = False
            main_expect = None
            relation = None
            sec_rule = None
            
            if len(parts) >= 5 and parts[2] in ["and", "skip"]:
                is_composite = True
                main_expect = parts[1] # "pass" or "fail"
                relation = parts[2]    # "and" or "skip"
                sec_rule = parts[3]    # "ANNXXXX"
                is_file_level = True
            else:
                is_file_level = len(parts) >= 3 and parts[-2] in ["pass", "fail", "autofix", "cleanup"]

            # ファイル名から正確にルールID部分だけを抽出
            file_rule_ids = parts[0].split('_')[0].split('-')
            
            if is_composite:
                file_rule_ids.append(sec_rule)
            
            # ファイル個別のフィルタリングでも d.parts を利用
            rule_in_path = False
            if target_rules_set:
                rule_in_path = any(r in target_dir.parts for r in target_rules_set)
                
            if target_rules_set and not any(r in target_rules_set for r in file_rule_ids) and not rule_in_path:
                continue
            
            test_cases = []
            
            if not is_entries_level:
                if is_composite:
                    actual_rules = triggered_rules_by_file.get(file_stem, set())
                    main_rule = file_rule_ids[0]
                    
                    # 主ルールがテスト対象かどうかの判定
                    is_main_targeted = not target_rules_set or main_rule in target_rules_set or rule_in_path
                    
                    if is_main_targeted:
                        # 主ルールのテストケース追加
                        test_cases.append({
                            "filename": filename, "rule_id": main_rule, 
                            "expected_result": main_expect, "rule_triggered": main_rule in actual_rules,
                            "main_rule": main_rule
                        })
                        
                        # 副ルールのテストケース追加（and なら fail を期待、skip なら skipped を期待）
                        sec_expect = "fail" if relation == "and" else "skipped"
                        
                        # 副ルールは、主ルールがテスト対象であれば連動してテストする（ターゲット制限をバイパス）
                        test_cases.append({
                            "filename": filename, "rule_id": sec_rule, 
                            "expected_result": sec_expect, "rule_triggered": sec_rule in actual_rules,
                            "main_rule": main_rule
                        })
                else:
                    expected_result = parts[-2] if is_file_level else extract_feature_expectations(ann_path)
                    if expected_result:
                        actual_rules = triggered_rules_by_file.get(file_stem, set())
                        for rule_id in file_rule_ids:
                            if target_rules_set and rule_id not in target_rules_set and not rule_in_path: continue
                            test_cases.append({
                                "filename": filename, "rule_id": rule_id, 
                                "expected_result": expected_result, "rule_triggered": rule_id in actual_rules
                            })
            else:
                entry_expectations = extract_entry_expectations(ann_path)
                file_triggered_entries = triggered_rules_by_entry.get(file_stem, {})
                for entry_name, rules in entry_expectations.items():
                    for rule_id, expected_result in rules.items():
                        if target_rules_set and rule_id not in target_rules_set and not rule_in_path: continue
                        entry_actual_rules = file_triggered_entries.get(entry_name, set())
                        global_rules = file_triggered_entries.get("ALL", set()).union(file_triggered_entries.get("COMMON", set()))
                        test_cases.append({
                            "filename": f"{filename} [{entry_name}]", "rule_id": rule_id, 
                            "expected_result": expected_result, "rule_triggered": (rule_id in entry_actual_rules) or (rule_id in global_rules)
                        })

            test_cases.sort(key=lambda x: (x["filename"], x["rule_id"]))
            
            test_dir_label = str(target_dir.relative_to(tests_dir))
            
            for tc in test_cases:
                tc_filename, tc_rule_id = tc["filename"], tc["rule_id"]
                tc_expected_result, tc_rule_triggered = tc["expected_result"], tc["rule_triggered"]
                main_rule_for_tc = tc.get("main_rule")
                test_name = f"{tc_filename} (Rule: {tc_rule_id})"

                # ==============================================================
                # curatorモード時の連動テストの保護
                # 主ルールがスキップ対象の場合、副ルールの検証前提が崩れるためスキップする
                # ==============================================================
                if main_rule_for_tc and main_rule_for_tc in mode_skipped_rules and tc_rule_id != main_rule_for_tc:
                    continue

                # ==============================================================
                # ANN1810 に対する個別ハードコード除外
                # - ANN1810_2: LocalモードではTaxonomyが引けず発火しないのが正仕様のため、テストをスキップ
                # - ANN1810_1: Localモードでも通常通り発火するのが正仕様のため、スキップルールから除外
                # ==============================================================
                if mode == "local" and tc_rule_id == "ANN1810" and "ANN1810_2" in tc_filename:
                    continue

                is_skipped_rule = tc_rule_id in mode_skipped_rules
                if mode == "local" and tc_rule_id == "ANN1810" and "ANN1810_1" in tc_filename:
                    is_skipped_rule = False
                    
                if skip_only and not is_skipped_rule:
                    continue

                if is_skipped_rule:
                    # スキップされるべきルールが発火していないかを検証
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected to be SKIPPED, but it TRIGGERED.")
                        errors.append(f"[{tc_rule_id}] {test_dir_label}/{test_name} (Expected SKIP)")
                        not_skipped_errors.append(f"[{tc_rule_id}] {test_dir_label}/{test_name}")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Skipped{Colors.ENDC}]        {test_name} (Correctly Skipped)")
                        skipped_count += 1
                    continue
                
                # --- 副ルールのスキップ期待値の処理 ---
                if tc_expected_result == "skipped":
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected secondary rule to be SKIPPED, but it TRIGGERED.")
                        errors.append(f"[{tc_rule_id}] {test_dir_label}/{test_name} (Expected SKIP)")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name} (Secondary rule correctly skipped)")
                        passed_count += 1
                    continue
                
                if tc_expected_result == "pass":
                    if tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected PASS, but rule triggered.")
                        errors.append(f"[{tc_rule_id}] {test_dir_label}/{test_name} (Expected PASS)")
                        mismatched_count += 1
                    else:
                        print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name} (No error triggered)")
                        passed_count += 1
                else:
                    if not tc_rule_triggered:
                        print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name}: Expected rule to trigger, but it did NOT.")
                        errors.append(f"[{tc_rule_id}] {test_dir_label}/{test_name} (Expected to trigger)")
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
                        translation_errors.append(f"{rule_prefix} {test_dir_label}/{test_name_trans} ({result_msg})")
                        translation_mismatched += 1
                            
        if not skip_only:
            expected_dir = target_dir / "expected"
            if expected_dir.exists() and expected_dir.is_dir():
                for golden_file in expected_dir.glob("*"):
                    if not golden_file.is_file(): continue

                    # autofix 確認サマリは fixed/ には現れないため、この一般ゴールデン突合では扱わない
                    # （後段の専用ブロックで --check-confirmation 時のみ突合する）
                    if golden_file.name == CONFIRMATION_SUMMARY_FILENAME:
                        continue

                    # ".entries.ann" などを取り除いてからハイフン等で分割する
                    base_name = golden_file.name.split('.')[0]
                    file_rule_ids = base_name.split('_')[0].split('-')
                    
                    if target_rules_set and not any(r in target_rules_set for r in file_rule_ids) and not rule_in_path:
                        continue
                        
                    # このファイルに含まれるルールがスキップ対象の場合、Autofixのファイル比較処理自体を行わない
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
                        err_msg = f"[{','.join(file_rule_ids)}] {test_dir_label}/{test_name_golden} (Fixed file missing: {fixed_file.name})"
                        errors.append(err_msg)
                        err_list.append(err_msg)
                        mismatched_count += 1
                        if is_cleanup: autocleanup_not_cleaned += 1
                        else: autofix_not_fixed += 1
                    else:
                        is_match, diff_msg = compare_text_files(golden_file, fixed_file)
                        if not is_match:
                            print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_golden}: Diff error -> {diff_msg}")
                            err_msg = f"[{','.join(file_rule_ids)}] {test_dir_label}/{test_name_golden} ({diff_msg})"
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

            # ==============================================================
            # autofix 確認サマリ（proposal 要約）のゴールデン突合 / スナップショット
            # ------------------------------------------------------------
            # proposal の外側 dict（old/new/message 等）は fixed/ に現れないため別途突合する。
            # 毎回走らせる必要はないので --check-confirmation / --update-confirmation で明示有効化。
            # proposal を完全生成する内部 DB 使用の CURATOR モードを基準とし、そこでのみ扱う
            # （local/ncbi では外部DB系 autofix が落ちてサマリ内容が変わるため）。
            # ==============================================================
            if (check_confirmation or update_confirmation) and mode == "curator":
                test_dir_label = str(target_dir.relative_to(tests_dir))
                actual_summary = target_dir / "reports" / CONFIRMATION_SUMMARY_FILENAME
                golden_summary = target_dir / "expected" / CONFIRMATION_SUMMARY_FILENAME

                if update_confirmation:
                    # 現挙動を期待値としてスナップショット保存（＝ゴールデン整備）
                    if actual_summary.exists():
                        golden_summary.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(actual_summary, golden_summary)
                        print(f"  [{Colors.OKCYAN}Updated{Colors.ENDC}]        {test_dir_label}/{CONFIRMATION_SUMMARY_FILENAME} (snapshot saved)")
                    elif golden_summary.exists():
                        # proposal が出なくなった → 古いゴールデンを削除して整合を取る
                        golden_summary.unlink()
                        print(f"  [{Colors.WARNINGYEL}Removed{Colors.ENDC}]        {test_dir_label}/{CONFIRMATION_SUMMARY_FILENAME} (no proposals; stale golden removed)")
                else:
                    # --check-confirmation: ゴールデンが存在するディレクトリのみ突合する
                    if golden_summary.exists():
                        test_name_conf = f"{CONFIRMATION_SUMMARY_FILENAME} (Confirmation Summary Match)"
                        if not actual_summary.exists():
                            print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_conf}: Actual summary missing (no proposals generated?).")
                            err_msg = f"{test_dir_label}/{test_name_conf} (Actual summary missing)"
                            errors.append(err_msg)
                            confirmation_errors.append(err_msg)
                            confirmation_mismatched += 1
                        else:
                            is_match, diff_msg = compare_text_files(golden_summary, actual_summary)
                            if is_match:
                                print(f"  [{Colors.OKGREEN}Matched{Colors.ENDC}]        {test_name_conf} (Perfect match)")
                                confirmation_passed += 1
                            else:
                                print(f"  [{Colors.FAILRED}MISMATCH{Colors.ENDC}] {test_name_conf}: Diff error -> {diff_msg}")
                                err_msg = f"{test_dir_label}/{test_name_conf} ({diff_msg})"
                                errors.append(err_msg)
                                confirmation_errors.append(err_msg)
                                confirmation_mismatched += 1

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
        "translation_errors": translation_errors,
        "confirmation_passed": confirmation_passed,
        "confirmation_mismatched": confirmation_mismatched,
        "confirmation_errors": confirmation_errors
    }

def print_header(title, color):
    print(f"\n{color}============================================================{Colors.ENDC}")
    print(f"{color}  {title.ljust(56)}{Colors.ENDC}")
    print(f"{color}============================================================{Colors.ENDC}")

def print_summary(results_list, docker_image=None):
    print("\n" + "="*80)
    if docker_image:
        print(f" {Colors.OKGREEN} FINAL E2E TEST SUMMARY (DOCKER: {docker_image}) {Colors.ENDC} ")
    elif args.use_pip:
        print(f" {Colors.OKGREEN} FINAL E2E TEST SUMMARY (PIP CLI) {Colors.ENDC} ")
    else:
        print(f" {Colors.OKGREEN} FINAL E2E TEST SUMMARY (DIRECT EXECUTION) {Colors.ENDC} ")
    print("="*80)
    
    for title, res, color in results_list:
        print(f"\n{color}[ {title} ]{Colors.ENDC}")
        passed_label = "Matched" if "CURATOR MODE" in title or "WEB APP MODE" in title else "Matched (Normal Rules)"
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

            if res.get('confirmation_passed', 0) > 0 or res.get('confirmation_mismatched', 0) > 0:
                print(f"  Confirm Summary:        {Colors.OKGREEN}{res['confirmation_passed']} matched{Colors.ENDC} / {Colors.FAILRED if res['confirmation_mismatched'] > 0 else Colors.OKGREEN}{res['confirmation_mismatched']} mismatched{Colors.ENDC}")
                if res.get('confirmation_errors'):
                    for e in res['confirmation_errors']:
                        print(f"    - {e}")

        general_errors = [e for e in res.get('errors', [])
                          if e not in res.get('autofix_errors', [])
                          and e not in res.get('autocleanup_errors', [])
                          and e not in res.get('translation_errors', [])
                          and e not in res.get('confirmation_errors', [])]
                          
        if general_errors:
            print("  General Errors:")
            for e in general_errors:
                print(f"    - {e}")
                
        if "CURATOR MODE" not in title and "WEB APP MODE" not in title:
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
        help="Run tests using the specified Docker image (e.g., ddbj-validator:0.1.0-beta)"
    )

    parser.add_argument(
        "--use-pip",
        action="store_true",
        help="Run tests using the pip-installed CLI command (ddbj-validator) instead of main.py"
    )
    
    parser.add_argument(
        "--mode",
        nargs="+",
        choices=["curator", "web-app", "local", "local-skip", "ncbi", "ncbi-skip", "auth-skip", "all"],
        default=["curator", "web-app", "local-skip", "ncbi-skip", "auth-skip"],
        help="Execution mode(s). Multiple modes can be specified."
    )

    # autofix 確認サマリ（autofix_confirmation_summary.txt）のゴールデン突合制御。
    # 毎回は不要なため既定では無効。CURATOR モードでのみ作用する。
    parser.add_argument(
        "--check-confirmation",
        action="store_true",
        help="Enable golden comparison of autofix_confirmation_summary.txt (CURATOR mode only; off by default)."
    )
    parser.add_argument(
        "--update-confirmation",
        action="store_true",
        help="Snapshot the generated autofix_confirmation_summary.txt into expected/ (golden 整備; CURATOR mode only)."
    )
    args = parser.parse_args()

    modes = args.mode

    if args.docker_image and modes == ["curator", "web-app", "local-skip", "ncbi-skip", "auth-skip"]:
        modes = ["local", "ncbi", "auth-skip"]

    if "all" in modes:
        if args.docker_image:
            modes = ["local", "ncbi", "auth-skip"]
        else:
            modes = ["curator", "web-app", "local", "ncbi", "auth-skip"]

    # 確認サマリ系フラグは CURATOR モードでのみ作用する。対象モードが無ければ無効である旨を通知。
    if (args.check_confirmation or args.update_confirmation) and "curator" not in modes:
        print(f"{Colors.WARNINGYEL}[WARN] --check-confirmation/--update-confirmation は CURATOR モードでのみ有効です"
              f"（現在のモード: {modes}）。確認サマリの突合/更新は行われません。{Colors.ENDC}")

    results_to_print = []

    if "curator" in modes:
        print_header("PHASE 1: CURATOR MODE TESTING (Skip ANN0422, 0463, 0481 / No Account)", Colors.OKGREEN)
        res_cur = run_e2e_tests(target_rule_id=args.rule_id, mode="curator", docker_image=args.docker_image, use_pip=args.use_pip,
                                check_confirmation=args.check_confirmation, update_confirmation=args.update_confirmation)
        results_to_print.append(("CURATOR MODE RESULTS", res_cur, Colors.OKGREEN))

    if "web-app" in modes:
        print_header("PHASE 2: WEB APP MODE TESTING (Only ANN0422, 0463, 0481 / With Account)", Colors.OKGREEN)
        res_web = run_e2e_tests(target_rule_id=args.rule_id, mode="web-app", docker_image=args.docker_image, use_pip=args.use_pip)
        results_to_print.append(("WEB APP MODE RESULTS", res_web, Colors.OKGREEN))

    if "local" in modes:
        print_header("PHASE 3: LOCAL MODE TESTING (Full test: Normal + Skip)", Colors.WARNINGYEL)
        res_local = run_e2e_tests(target_rule_id=args.rule_id, mode="local", skip_only=False, docker_image=args.docker_image, use_pip=args.use_pip)
        results_to_print.append(("LOCAL MODE RESULTS (FULL TEST)", res_local, Colors.WARNINGYEL))
        
    elif "local-skip" in modes:
        print_header("PHASE 3: LOCAL MODE TESTING (Skip Verification Only)", Colors.WARNINGYEL)
        res_local = run_e2e_tests(target_rule_id=args.rule_id, mode="local", skip_only=True, docker_image=args.docker_image, use_pip=args.use_pip)
        results_to_print.append(("LOCAL MODE RESULTS (SKIP ONLY)", res_local, Colors.WARNINGYEL))

    if "ncbi" in modes:
        print_header("PHASE 4: NCBI API MODE TESTING (Full test: Normal + Skip)", Colors.OKCYAN)
        res_ncbi = run_e2e_tests(target_rule_id=args.rule_id, mode="ncbi", skip_only=False, docker_image=args.docker_image, use_pip=args.use_pip)
        results_to_print.append(("NCBI API MODE RESULTS (FULL TEST)", res_ncbi, Colors.OKCYAN))
        
    elif "ncbi-skip" in modes:
        print_header("PHASE 4: NCBI API MODE TESTING (Skip Verification Only)", Colors.OKCYAN)
        res_ncbi = run_e2e_tests(target_rule_id=args.rule_id, mode="ncbi", skip_only=True, docker_image=args.docker_image, use_pip=args.use_pip)
        results_to_print.append(("NCBI API MODE RESULTS (SKIP ONLY)", res_ncbi, Colors.OKCYAN))

    if "auth-skip" in modes:
        print_header("PHASE 5: AUTH SKIP MODE TESTING (Skip Verification Only)", Colors.OKBLUE)
        res_auth = run_e2e_tests(target_rule_id=args.rule_id, mode="auth-skip", skip_only=True, docker_image=args.docker_image, use_pip=args.use_pip)
        results_to_print.append(("AUTH SKIP MODE RESULTS (SKIP ONLY)", res_auth, Colors.OKBLUE))

    print_summary(results_to_print, docker_image=args.docker_image)
    
    # ==============================================================================
    # 終了コードの制御 (CI/CD や シェルスクリプトのアボート用)
    # ==============================================================================
    has_errors = False
    total_mismatches = 0

    for title, res, color in results_to_print:
        # Mismatch や エラーの数を合算
        mode_errors = (
            res.get("mismatched", 0) +
            res.get("translation_mismatched", 0) +
            res.get("autofix_not_fixed", 0) +
            res.get("autocleanup_not_cleaned", 0) +
            res.get("confirmation_mismatched", 0) +
            len(res.get("not_skipped_errors", []))
        )
        if mode_errors > 0:
            has_errors = True
            total_mismatches += mode_errors

    if has_errors:
        print(f"\n{Colors.FAILRED}[ABORT] Test failures detected (Total mismatch/errors). Exiting with status code 1.{Colors.ENDC}\n")
        sys.exit(1)
    else:
        print(f"\n{Colors.OKGREEN}[SUCCESS] All tests passed successfully! Exiting with status code 0.{Colors.ENDC}\n")
        sys.exit(0)