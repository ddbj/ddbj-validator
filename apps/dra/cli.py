"""DRA validator の CLI（サブコマンド dra）。

入力は 1 セッション分の DRA XML 群。指定方法は 2 通り（併用も可）:
  - ディレクトリ: 中の *.xml を root 要素でロール自動判定。
  - 個別指定: --sub / --exp / --run / --ana（複数可）。
実行モードは biosample/bioproject と同一骨格（-l ローカル / -n NCBI / -d 内部DB, -j JSON）。
1 セッションに渡された submission/experiment/run/analysis を 1 submission として検証する。
"""
import argparse
import datetime
import re
import sys

from common import cli_modes
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
    return cli_modes.tool_version("apps.dra")


def _env_internal_db():
    return cli_modes.env_internal_db()


def _resolve_modes(args):
    return cli_modes.resolve_modes(args)


def _submission_id(submission):
    """submission alias から submission id を得る（例 'amr_ddbj-0104_Submission' → 'amr_ddbj-0104'）。"""
    sm = submission.submission
    if not sm or not sm.alias:
        return None
    a = sm.alias.strip()
    return a.split("_Submission")[0] if "_Submission" in a else a


def _account_from_submission_id(submission_id):
    """submission id から account を導出（末尾の '-<連番>' を除く。例 'amr_ddbj-0104' → 'amr_ddbj'）。
    アカウント名はハイフンを含むため、後方の -\\d{4,} だけを除外する。"""
    if not submission_id:
        return None
    acc = re.sub(r"-\d{4,}$", "", submission_id)
    return acc or None


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
    """内部 DB 依存ルール用メタを context へ（DRA_R0004 center / R0009 名 / R0015/16/41/42/43）。

    取得ごとに独立して失敗を吸収する（1 つの DB/接続失敗が他ルール用メタ取得を巻き込まないため）。
    """
    from common.db_manager import DatabaseManager
    from apps.dra import db_meta
    dm = DatabaseManager()

    def _try(label, fn):
        return cli_modes.warn_none(label, fn, "dra DB meta fetch failed")

    dra_conn = _try("dra_conn", dm.get_dra_conn)
    ref_bp = {(o.study_ref or "").strip() for o in submission.experiments + submission.analyses if o.study_ref}
    ref_bs = {(e.sample_ref or "").strip() for e in submission.experiments if e.sample_ref}
    for a in submission.analyses:
        ref_bs.update(s.strip() for s in a.sample_refs)
    ref_drr = {d.strip() for a in submission.analyses for d in a.run_refs if d}

    cli_modes.db_checking("BioProject DB", len(ref_bp), "project")
    cli_modes.db_checking("BioSample DB", len(ref_bs), "sample")
    cli_modes.db_checking("DRA DB", len(ref_drr), "DRA Run")
    context.account_org_name = _try("org", lambda: db_meta.fetch_submitter_center_name(dm.get_submitter_conn(), account))
    context.account_bioprojects = _try("bp", lambda: db_meta.fetch_account_bioprojects(dm.get_bp_conn(), dra_conn, account, ref_bp))
    context.account_biosamples = _try("bs", lambda: db_meta.fetch_account_biosamples(dm.get_bs_conn(), dra_conn, account, ref_bs))
    context.account_runs = _try("runs", lambda: db_meta.fetch_account_runs(dra_conn, account, ref_drr))
    context.account_object_names = _try("obj_names", lambda: db_meta.fetch_account_object_names(dra_conn, account))


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
    submission, pre_errors = xml_reader.parse_files(paths, account=args.account)

    # submission alias から submission id / account を導出。
    # DDBJ 以外の DRA 等は必ずアカウントに紐づくため、--account 未指定なら alias から自動取得する。
    submission.submission_id = _submission_id(submission)
    account = args.account or _account_from_submission_id(submission.submission_id)
    submission.account = account

    context = ValidationContext(account=account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)
    out_dir = args.out_dir or str(Path(paths[0]).parent)
    if not args.json:
        cli_modes.print_found(1, "file set")   # sub/exp/run/ana = 1 set
    if not context.skip_db:   # 内部 DB モードのみ: account/DB 依存ルール用メタを取得
        cli_modes.reset_db_access_log()
        _fetch_db_meta(context, submission, account)
    results = pre_errors + Validator(context).run(submission)

    now = datetime.datetime.now(_JST)
    when = started.strftime("%Y-%m-%d %H:%M:%S JST")
    elapsed = str(datetime.timedelta(seconds=int((now - started).total_seconds())))
    version = _tool_version()
    label = f"{len(paths)} files"
    summary = build_summary(results, submission, version, when, elapsed)
    if args.json:
        write_json_report(results, out_dir, label, version)
        report_files = ["validation_report.json"]
    else:
        details = build_details(results, submission, version, when, elapsed)
        write_text_reports(summary, details, out_dir)
        report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
        print(cli_modes.stdout_summary(summary))   # === タイトル行は出さず前後に空行
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
