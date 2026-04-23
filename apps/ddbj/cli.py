#!/usr/bin/env python3

import sys
import re
import argparse
from pathlib import Path
from dotenv import load_dotenv
from apps.ddbj.file_manager import find_file_pairs
from apps.ddbj.preprocessor import ANN_EXTENSIONS, FASTA_EXTENSIONS
from apps.ddbj.orchestrator import ValidatorPipeline
from apps.ddbj.reporter import ValidationReporter

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="DDBJ MSS Validator")
    # 位置引数（ターゲット）を追加。0個以上の引数を受け付ける
    parser.add_argument("targets", nargs="*", help="Target directories or files (default: current directory)")
    # 既存のフラグも後方互換性のために残す
    parser.add_argument("-d", "--dir", action="append", help="Target directory (deprecated, use positional arguments)")
    parser.add_argument("-a", "--ann", help="Annotation file (deprecated, use positional arguments)")
    parser.add_argument("-s", "--seq", help="Sequence file (deprecated, use positional arguments)")
    
    parser.add_argument("-w", "--web", action="store_true", help="NSSS (web submission) mode")
    parser.add_argument("-f", "--force-fix", action="store_true", help="Automatically apply all auto-fixes without prompting")
    args = parser.parse_args()
        
    # --- 1. ターゲットの収集とデフォルト設定 ---
    raw_targets = list(args.targets)
    if args.dir: raw_targets.extend(args.dir)
    if args.ann: raw_targets.append(args.ann)
    if args.seq: raw_targets.append(args.seq)

    # 何も指定されなかった場合はカレントディレクトリを対象とする
    if not raw_targets:
        raw_targets = ["."]

    # --- 2. ディレクトリとファイルの振り分けと存在チェック ---
    dirs = []
    files = []
    # 複数回同じパスが指定された場合の重複を排除
    for t in list(dict.fromkeys(raw_targets)): 
        p = Path(t)
        if p.is_dir():
            dirs.append(p)
        elif p.is_file():
            files.append(p)
        else:
            print(f"[ERROR] Target not found: '{t}'", file=sys.stderr)
            sys.exit(1)

    # --- 3. 追加チェック1: 混在エラー ---
    if dirs and files:
        print("[ERROR] Cannot mix directories and files in arguments. Please specify only directories or only files.", file=sys.stderr)
        sys.exit(1)

    pairs = []
    report_out_dir = None 
    target_dirs_for_report = []

    # --- 4. ディレクトリモードの処理 ---
    if dirs:
        # 追加チェック2: 複数ディレクトリ時の NSUB 重複チェック
        if len(dirs) > 1:
            nsubs = set()
            for d in dirs:
                match = re.search(r'(NSUB\d+)', str(d))
                if not match:
                    print(f"[ERROR] NSUB ID could not be extracted from directory path '{d}'. Processing aborted.", file=sys.stderr)
                    sys.exit(1)
                
                nsub_id = match.group(1)
                if nsub_id in nsubs:
                    print(f"[ERROR] Duplicated NSUB ID '{nsub_id}' across directories. Processing aborted.", file=sys.stderr)
                    sys.exit(1)
                nsubs.add(nsub_id)

        target_dirs_for_report = dirs
        for d in dirs:
            if not report_out_dir: report_out_dir = d
            
            sub_pairs, file_errors = find_file_pairs(d)
            
            if file_errors:
                for err in file_errors:
                    print(f"[FATAL] {err['message']}", file=sys.stderr)
                sys.exit(1)

            if not sub_pairs:
                print(f"[FATAL] No matching ANN/FASTA file pairs found in '{d}'.", file=sys.stderr)
                sys.exit(1)
                
            pairs.extend(sub_pairs)
                            
        set_str = "1 file set" if len(pairs) == 1 else f"{len(pairs)} file sets"
        dir_str = "1 directory" if len(dirs) == 1 else f"{len(dirs)} directories"
        print(f"Found {set_str} in {dir_str}.")

    # --- 5. ファイルモードの処理 ---
    elif files:
        # 追加チェック3: 拡張子の妥当性チェック
        valid_files = []
        for f in files:
            is_valid = any(f.name.endswith(ext) for ext in ANN_EXTENSIONS + FASTA_EXTENSIONS)
            if not is_valid:
                print(f"[ERROR] Invalid ANN or FASTA file extension for '{f.name}'.", file=sys.stderr)
                sys.exit(1)
            valid_files.append(f)

        paired_stems = set()
        for f in valid_files:
            if not report_out_dir: report_out_dir = f.parent
            target_dirs_for_report.append(f.parent)
            
            is_ann = any(f.name.endswith(ext) for ext in ANN_EXTENSIONS)
            
            base_name = f.name
            for ext in ANN_EXTENSIONS + FASTA_EXTENSIONS:
                if f.name.endswith(ext):
                    base_name = f.name[:-len(ext)]
                    break
            
            # すでにペアとして処理済みの場合はスキップ
            if base_name in paired_stems:
                continue 

            ann_path = None
            seq_path = None

            if is_ann:
                ann_path = str(f)
                for ext in FASTA_EXTENSIONS:
                    candidate = f.parent / (base_name + ext)
                    if candidate.is_file():
                        seq_path = str(candidate)
                        break
            else:
                seq_path = str(f)
                for ext in ANN_EXTENSIONS:
                    candidate = f.parent / (base_name + ext)
                    if candidate.is_file():
                        ann_path = str(candidate)
                        break
            
            if not ann_path or not seq_path:
                print(f"[FATAL] Corresponding paired file not found for '{f}'.", file=sys.stderr)
                sys.exit(1)
            
            pairs.append((ann_path, seq_path))
            paired_stems.add(base_name)
            
        # 重複する出力先ディレクトリを整理
        target_dirs_for_report = list(dict.fromkeys(target_dirs_for_report))

    # --- パイプラインの実行とレポート出力 --- #
    pipeline = ValidatorPipeline(pairs, report_out_dir, args.web, args.force_fix)
    
    # 1. 検証の実行と Autofix 提案の収集
    all_results = pipeline.run_validation()
    
    # 2. 全体統合レポートの生成 (実行したカレントディレクトリに出力)
    combined_reporter = ValidationReporter(out_dir=".")
    comb_sum_path, comb_det_path = combined_reporter.generate_report(all_results, print_console=True)
    
    # 3. Autofix の承認と適用
    pipeline.run_autofix()
    
    # 4. 各ディレクトリへの個別レポート配分
    import shutil
    
    # 複数ディレクトリ（複数NSUB）指定時のみ combined を出力するためのフラグ
    output_combined = len(target_dirs_for_report) > 1
    
    for d_path in target_dirs_for_report:
        d_abs = d_path.resolve()
        
        sub_results = [
            r for r in all_results 
            if r.get('full_path') and Path(r['full_path']).resolve().is_relative_to(d_abs)
        ]
        
        if sub_results:
            indiv_reporter = ValidationReporter(out_dir=d_path)
            indiv_reporter.generate_report(sub_results, print_console=False)
            
            # フラグが True のときだけ combined ファイルをコピー
            if output_combined:
                if comb_sum_path.exists():
                    try:
                        shutil.copy(comb_sum_path, d_path / "validation_report_summary_combined.txt")
                    except Exception as e:
                        print(f"[WARN] Cannot copy summary to {d_path}: {e}", file=sys.stderr)
                if comb_det_path.exists():
                    try:
                        shutil.copy(comb_det_path, d_path / "validation_report_details_combined.txt")
                    except Exception as e:
                        print(f"[WARN] Cannot copy details to {d_path}: {e}", file=sys.stderr)
    
    # ========================================================
    # クリーンアップと終了メッセージ
    # カレントディレクトリ指定時など、個別レポートと出力先が被っている場合は削除しない
    # ========================================================
    is_conflict = any(comb_sum_path.resolve() == (d / "validation_report_summary.txt").resolve() for d in target_dirs_for_report)

    if not is_conflict:
        try:
            if comb_sum_path.exists(): comb_sum_path.unlink()
            if comb_det_path.exists(): comb_det_path.unlink()
        except Exception:
            pass

    dist_dir_label = "directory" if len(target_dirs_for_report) == 1 else "directories"
    print(f"\n\n[ All reports successfully generated to {len(target_dirs_for_report)} {dist_dir_label} ]")
    for d in target_dirs_for_report:
        print(f"{d}")
        print(f"  validation_report_summary.txt (Individual)")
        print(f"  validation_report_details.txt (Individual)")
        # メッセージの出力もフラグで制御
        if output_combined:
            print(f"  validation_report_summary_combined.txt (Combined)")
            print(f"  validation_report_details_combined.txt (Combined)")
        print() # ディレクトリごとの空行

if __name__ == "__main__":
    main()