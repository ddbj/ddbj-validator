"""DRA validator の CLI（サブコマンド dra）。

入力は 1 セッション分の DRA XML 群。指定方法は 2 通り（併用も可）:
  - ディレクトリ: 中の *.xml を root 要素でロール自動判定。
  - 個別指定: --sub / --exp / --run / --ana（複数可）。
実行モードは biosample/bioproject と同一骨格（-l ローカル / -n NCBI / -d 内部DB, -j JSON）。
1 セッションに渡された submission/experiment/run/analysis を 1 submission として検証する。
"""
import argparse
import datetime
import sys
from pathlib import Path

from apps.dra.context import ValidationContext
from apps.dra import xml_reader
from apps.dra.validator import Validator
from apps.dra.reporter import build_summary, build_details, write_text_reports, write_json_report

_JST = datetime.timezone(datetime.timedelta(hours=9))


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator dra", description="DRA Validator")
    p.add_argument("target", nargs="?", default=None, help="入力ディレクトリ（中の *.xml を root でロール判定）")
    p.add_argument("--sub", "--submission", dest="sub", action="append", default=[], help="submission XML")
    p.add_argument("--exp", "--experiment", dest="exp", action="append", default=[], help="experiment XML")
    p.add_argument("--run", dest="run", action="append", default=[], help="run XML")
    p.add_argument("--ana", "--analysis", dest="ana", action="append", default=[], help="analysis XML（任意）")
    p.add_argument("--account", default=None, help="Submitter id (account) for auth-dependent rules")
    p.add_argument("-o", "--out-dir", default=None, help="Output directory (default: 入力の親)")
    p.add_argument("-l", "--local", action="store_true", help="Local mode (skip DB and NCBI API)")
    p.add_argument("-n", "--ncbi-api", action="store_true", help="Use NCBI API, skip internal DB")
    p.add_argument("-d", "--internal-db", action="store_true", help="内部 DDBJ DB を使う curator モード")
    p.add_argument("-j", "--json", action="store_true", help="出力を JSON にする（既定は TSV）")
    return p


def _tool_version():
    try:
        from apps.dra import __version__
        return __version__
    except Exception:
        return "unknown"


def _env_internal_db():
    import os
    return os.environ.get("DDBJ_VALIDATOR_INTERNAL_DB", "").strip().lower() not in ("", "0", "false", "no")


def _resolve_modes(args):
    if args.local:
        skip_db, skip_ncbi = True, True
    elif args.ncbi_api:
        skip_db, skip_ncbi = True, False
    elif args.internal_db or _env_internal_db():
        skip_db, skip_ncbi = False, False
    else:
        skip_db, skip_ncbi = True, False
    return skip_db, skip_ncbi, skip_db  # skip_auth は skip_db に従う


def _collect_paths(args):
    """ディレクトリ＋個別指定から検証対象 XML パス群を集める。"""
    paths = []
    if args.target:
        d = Path(args.target)
        if d.is_dir():
            paths.extend(sorted(str(p) for p in d.glob("*.xml")))
        elif d.exists():
            paths.append(str(d))
    for group in (args.sub, args.exp, args.run, args.ana):
        paths.extend(group)
    # 重複除去（順序維持）
    seen, uniq = set(), []
    for p in paths:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq


def _fetch_db_meta(context, submission, account):
    """内部 DB 依存ルール用メタを context へ（DRA_R0004 center / R0009 名 / R0015 BP / R0016 BS）。"""
    try:
        from common.db_manager import DatabaseManager
        from apps.dra import db_meta
        dm = DatabaseManager()
        dra_conn = dm.get_dra_conn()
        context.account_org_name = db_meta.fetch_submitter_center_name(dm.get_submitter_conn(), account)
        ref_bp = {(o.study_ref or "").strip() for o in submission.experiments + submission.analyses if o.study_ref}
        context.account_bioprojects = db_meta.fetch_account_bioprojects(dm.get_bp_conn(), dra_conn, account, ref_bp)
        ref_bs = {(e.sample_ref or "").strip() for e in submission.experiments if e.sample_ref}
        for a in submission.analyses:
            ref_bs.update(s.strip() for s in a.sample_refs)
        context.account_biosamples = db_meta.fetch_account_biosamples(dm.get_bs_conn(), dra_conn, account, ref_bs)
        ref_drr = {d.strip() for a in submission.analyses for d in a.run_refs if d}
        context.account_runs = db_meta.fetch_account_runs(dra_conn, account, ref_drr)
        context.account_object_names = db_meta.fetch_account_object_names(dra_conn, account)
    except Exception as e:
        print(f"[WARN] dra DB meta fetch failed: {e}", file=sys.stderr)


def run(args):
    started = datetime.datetime.now(_JST)
    paths = _collect_paths(args)
    if not paths:
        print("[ERROR] 入力 XML がありません（ディレクトリ or --sub/--exp/--run/--ana）", file=sys.stderr)
        return 2
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        print(f"[ERROR] Input not found: {', '.join(missing)}", file=sys.stderr)
        return 2

    skip_db, skip_ncbi, skip_auth = _resolve_modes(args)
    context = ValidationContext(account=args.account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)

    submission, pre_errors = xml_reader.parse_files(paths, account=args.account)
    out_dir = args.out_dir or str(Path(paths[0]).parent)
    if not context.skip_db:   # 内部 DB モードのみ: account/DB 依存ルール用メタを取得
        _fetch_db_meta(context, submission, args.account)
    results = pre_errors + Validator(context).run(submission)

    counts_obj = {"experiments": len(submission.experiments), "runs": len(submission.runs),
                  "analyses": len(submission.analyses)}
    now = datetime.datetime.now(_JST)
    when = started.strftime("%Y-%m-%d %H:%M:%S JST")
    elapsed = str(datetime.timedelta(seconds=int((now - started).total_seconds())))
    version = _tool_version()
    label = f"{len(paths)} files"
    summary = build_summary(results, counts_obj, label, version, when, elapsed)
    if args.json:
        write_json_report(results, out_dir, label, version)
        report_files = ["validation_report.json"]
    else:
        details = build_details(results, label, version, when, elapsed)
        write_text_reports(summary, details, out_dir)
        report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
        print(summary.rstrip("\n"))
    print(f"[ All reports successfully generated to {Path(out_dir)/'reports'} ]\n"
          + "\n".join(f"  {f}" for f in report_files))
    return 1 if any(r.get("level") == "error" for r in results) else 0


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    args = _build_parser().parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
