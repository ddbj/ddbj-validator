import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
from apps.ddbj.file_manager import find_file_pairs
from apps.ddbj.preprocessor import ANN_EXTENSIONS, FASTA_EXTENSIONS
from apps.ddbj.orchestrator import ValidatorPipeline
from apps.ddbj.reporter import ValidationReporter

load_dotenv()

def main():
    parser = argparse.ArgumentParser(description="DDBJ Validator")
    
    # 位置引数（ターゲット）を追加。0個以上の引数を受け付ける
    parser.add_argument("targets", nargs="*", help="Target directories or files (default: current directory)")
    
    # 既存のフラグも後方互換性のために残す
    parser.add_argument("-d", "--dir", action="append", help="Target directory (deprecated, use positional arguments)")
    parser.add_argument("-a", "--ann", help="Annotation file (deprecated, use positional arguments)")
    parser.add_argument("-s", "--seq", help="Sequence file (deprecated, use positional arguments)")
    parser.add_argument("-j", "--jobs", type=int, default=None, help="Number of parallel processes (default: up to 8. Use 0 to use all available cores)")
    parser.add_argument("-w", "--web", action="store_true", help="NSSS (web submission) mode")
    parser.add_argument("-f", "--force-fix", action="store_true", help="Automatically apply all auto-fixes without prompting")
    
    # --- ユーザー向けメインオプション ---
    # 出力ディレクトリの指定 (-o / --out-dir)
    parser.add_argument("-o", "--out-dir", type=str, help="Output directory for reports and fixed files")
    
    parser.add_argument("-l", "--local", action="store_true", help="Run in completely local mode (Skip both internal DB and NCBI API)")
    parser.add_argument("-n", "--ncbi-api", action="store_true", help="Run with public NCBI API (Skip internal DB, but use NCBI API)")
    
    # --- 開発者向け個別制御オプション ---
    parser.add_argument("--skip-db", action="store_true", help="Skip internal DB queries")
    parser.add_argument("--skip-ncbi", action="store_true", help="Skip NCBI API queries")
    
    # NCBI API key 指定
    parser.add_argument("--ncbi-api-key", type=str, help="NCBI API key to increase rate limits (optional)")

    args = parser.parse_args()

    if args.ncbi_api_key:
        os.environ["NCBI_API_KEY"] = args.ncbi_api_key
    
    # --- オプションの論理解決 ---
    skip_db = False
    skip_ncbi = False

    # 1. ローカルモードの適用 (-l)
    if args.local:
        skip_db = True
        skip_ncbi = True

    # 2. NCBI APIモードの適用 (-n)
    # (-l と同時に指定された場合、NCBIをスキップするという設定を上書きしてONにする)
    if args.ncbi_api:
        skip_db = True
        skip_ncbi = False

    # 3. 開発者向け個別指定オプションの適用 (さらに上書き)
    if args.skip_db:
        skip_db = True
    if args.skip_ncbi:
        skip_ncbi = True
        
    # --- 0. 並列数の決定 ---
    cpu_count = os.cpu_count() or 1
    if args.jobs is None:
        # 未指定: 最大8までに制限 (OOMとI/Oスラッシングを防止)
        jobs = min(cpu_count, 8)
    elif args.jobs <= 0:
        # -j 0 指定: 制限なしでありったけのコアを使う (HPC等のハイエンド環境向け)
        jobs = cpu_count
    else:
        # 明示的な指定 (例: -j 16)
        jobs = args.jobs
                        
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
    
    # -o オプションで指定された出力先ディレクトリの初期化
    report_out_dir = None 
    if args.out_dir:
        report_out_dir = Path(args.out_dir)
        report_out_dir.mkdir(parents=True, exist_ok=True)
        
    target_dirs_for_report = []

    # --- 4. ディレクトリモードの処理 ---
    if dirs:
        if len(dirs) > 1:
            print("[ERROR] Cannot specify multiple directories. Please specify only one directory.", file=sys.stderr)
            sys.exit(1)

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
        print(f"Found {set_str} in 1 directory.")

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
    # 解決済みの skip_db, skip_ncbi フラグを渡す
    pipeline = ValidatorPipeline(
        pairs, report_out_dir, args.web, args.force_fix, jobs, 
        skip_db=skip_db, skip_ncbi=skip_ncbi
    )
    
    try:
        # 1. 検証の実行と Autofix 提案の収集 (戻り値はメモリ配列ではなく JSONL のパスリスト)
        jsonl_paths = pipeline.run_validation()
        
        # 2. レポートの生成 (ストリーミング処理)
        # -o オプションがあればそれを最優先に、なければ対象ディレクトリに出力
        target_dir = report_out_dir if args.out_dir else (target_dirs_for_report[0] if target_dirs_for_report else Path(report_out_dir))
        reporter = ValidationReporter(out_dir=target_dir)
        reporter.generate_report(jsonl_paths, print_console=True)
        
        # 3. Autofix の承認と適用
        pipeline.run_autofix()
        
        print(f"\n\n[ All reports successfully generated to {target_dir} ]")
        print(f"  validation_report_summary.txt")
        print(f"  validation_report_details.txt\n")
    finally:
        # 4. コンテナやホストのディスクを圧迫しないよう、テンポラリファイルを確実に削除
        pipeline.cleanup_tmp_dir()

if __name__ == "__main__":
    main()