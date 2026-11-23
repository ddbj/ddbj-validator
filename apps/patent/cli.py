"""`ddbj-validator patent`: 特許（ST.26 由来）の ann + FASTA を検査する。

    ddbj-validator patent <dir または ann / fasta> [-o <out>] [-j N] [--json] [-l]

特許は出願に添付された配列情報をそのまま FF にするので、FF が作れれば ok の緩い検査にする。
値に手を入れず、fixed/ は出さない。出すのは reports/ だけ。
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from apps.ddbj.file_manager import find_file_pairs
from apps.ddbj.preprocessor import ANN_EXTENSIONS, FASTA_EXTENSIONS
from apps.patent import runner
from apps.patent.reporter import PatentReporter

# 内部 DB（Taxonomy）の接続設定を .env から読む（ddbj の cli と同じ）
load_dotenv()


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="ddbj-validator patent",
        description="Validate patent (ST.26) annotation and sequence file sets.")
    parser.add_argument("targets", nargs="*", help="Target directory, or annotation/sequence files (default: current directory)")
    parser.add_argument("-o", "--out-dir", type=str, help="Output directory for reports")
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="Number of parallel processes (default: up to 8. Use 0 to use all available cores)")
    parser.add_argument("--json", action="store_true", help="Output report as JSON (validation_report.json). -j is --jobs, not JSON")
    parser.add_argument("-l", "--local", action="store_true", help="Run without the Taxonomy database (PAT0043 is skipped)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging to stderr")
    return parser


def _base_name(path, extensions):
    name = Path(path).name
    for ext in extensions:
        if name.endswith(ext):
            return name[:-len(ext)]
    return None


def _pairs_from_files(files):
    """ファイルで渡されたときの組。base 名が同じ ann と FASTA を 1 組にする（ANN0020 は find_file_pairs と同じ文言）。"""
    anns, fastas = {}, {}
    for f in files:
        base = _base_name(f, ANN_EXTENSIONS)
        if base is not None:
            anns.setdefault(base, []).append(str(f))
            continue
        base = _base_name(f, FASTA_EXTENSIONS)
        if base is not None:
            fastas.setdefault(base, []).append(str(f))
        else:
            print(f"[FATAL] Not an annotation or sequence file: {f}", file=sys.stderr)
            sys.exit(1)
    pairs, errors = [], []
    for base in sorted(set(anns) | set(fastas)):
        a, s = anns.get(base, []), fastas.get(base, [])
        if len(a) == 1 and len(s) == 1:
            pairs.append((a[0], s[0]))
        else:
            errors.append({
                "level": "FATAL", "rule": "ANN0020", "target": "file", "entry": "ALL",
                "message": f"Invalid file pair for '{base}': {len(a)} annotation file(s) and {len(s)} sequence file(s).",
                "file": f"{base}.*", "category": "file_manager"})
    return pairs, errors


def _resolve_targets(args):
    targets = [Path(t) for t in (args.targets or ["."])]
    dirs = [t for t in targets if t.is_dir()]
    files = [t for t in targets if not t.is_dir()]
    for f in files:
        if not f.is_file():
            print(f"[FATAL] File or directory not found: {f}", file=sys.stderr)
            sys.exit(1)
    if dirs and (files or len(dirs) > 1):
        print("[ERROR] Specify one directory, or annotation/sequence files.", file=sys.stderr)
        sys.exit(1)
    if dirs:
        pairs, errors = find_file_pairs(dirs[0])
        base_dir = dirs[0]
    else:
        pairs, errors = _pairs_from_files(files)
        base_dir = files[0].parent
    out_dir = Path(args.out_dir) if args.out_dir else base_dir
    return sorted(pairs), errors, out_dir


def _jobs(args):
    cpu_count = os.cpu_count() or 1
    if args.jobs is None:
        return min(cpu_count, 8)
    return cpu_count if args.jobs <= 0 else args.jobs


def main():
    args = _build_parser().parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s", stream=sys.stderr)
    pairs, file_errors, out_dir = _resolve_targets(args)
    if not pairs and not file_errors:
        print("[FATAL] No annotation/sequence file sets found.", file=sys.stderr)
        sys.exit(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = _jobs(args)
    set_str = "1 file set" if len(pairs) == 1 else f"{len(pairs)} file sets"
    print(f"Found {set_str}.")

    try:
        from apps.patent import __version__ as tool_version
    except Exception:
        tool_version = "unknown"

    start_time = time.time()
    known_organisms = None if args.local else runner.fetch_known_organisms(pairs)
    if not args.local and known_organisms is None:
        print("[WARN] The Taxonomy database could not be reached. PAT0043 (organism name) is skipped.", file=sys.stderr)
    jsonl_paths, tmp_dir = runner.run(pairs, file_errors, out_dir, jobs, known_organisms=known_organisms)
    end_time = time.time()
    try:
        reporter = PatentReporter(out_dir=out_dir)
        header = f"Version: {tool_version}\n"
        if args.json:
            reporter.write_json_report(jsonl_paths, version=tool_version)
            report_files = ["validation_report.json"]
        else:
            # 数千 set の内容を画面に流さない。画面には件数だけ出す
            reporter.generate_report(jsonl_paths, print_console=False, start_time=start_time, end_time=end_time,
                                     version=tool_version)
            report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
        reporter.write_table_report(jsonl_paths, header_info=header, set_str=set_str)
        report_files += ["validation_report_table.txt", "validation_report_table.tsv"]
    finally:
        runner.cleanup(tmp_dir)

    print(f"Validated {set_str} in {end_time - start_time:.1f} seconds.")
    print(f"\n[ All reports successfully generated to {out_dir / 'reports'} ]")
    for name in report_files:
        print(f"  {name}")


if __name__ == "__main__":
    main()
