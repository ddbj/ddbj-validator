"""BioProject validator の CLI（サブコマンド bioproject）。

入力は BioProject XML（-x）。実行モードは biosample と同一骨格:
  既定=NCBI API（DB/auth スキップ、taxonomy は NCBI）。env DDBJ_VALIDATOR_INTERNAL_DB=1 or -d で内部DB(curator)。
  -l 完全ローカル / -n NCBI / -d 内部DB。出力は既定 TSV（summary＋details）、-j で JSON。
"""
import argparse
import datetime
import sys
from pathlib import Path

from apps.bioproject.context import ValidationContext
from apps.bioproject import xml_reader
from apps.bioproject.validator import Validator
from apps.bioproject.reporter import (
    build_summary, build_details, write_text_reports, write_json_report,
)

_JST = datetime.timezone(datetime.timedelta(hours=9))


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator bioproject", description="BioProject Validator")
    p.add_argument("-x", "--xml", dest="xml", required=True, help="BioProject XML 入力ファイル")
    p.add_argument("--account", default=None, help="Submitter id (account) for auth-dependent rules")
    p.add_argument("-o", "--out-dir", default=None, help="Output directory (default: input's parent)")
    p.add_argument("-l", "--local", action="store_true", help="Local mode (skip DB and NCBI API)")
    p.add_argument("-n", "--ncbi-api", action="store_true", help="Use NCBI API, skip internal DB (一般ユーザ既定)")
    p.add_argument("-d", "--internal-db", action="store_true", help="内部 DDBJ DB を使う curator モード")
    p.add_argument("-j", "--json", action="store_true", help="出力を JSON にする（既定は TSV）")
    return p


def _tool_version():
    try:
        from apps.bioproject import __version__
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
    elif args.internal_db:
        skip_db, skip_ncbi = False, False
    elif _env_internal_db():
        skip_db, skip_ncbi = False, False
    else:
        skip_db, skip_ncbi = True, False
    return skip_db, skip_ncbi, skip_db  # skip_auth は skip_db に従う


def _fetch_taxonomy(context, organisms, taxids):
    """organism 群の taxonomy を context.tax_data / taxid_info へ。default=内部DB / -n=NCBI。"""
    try:
        if not context.skip_db:
            from common.db_manager import DatabaseManager
            from common.db_taxonomy import fetch_taxonomy_data, fetch_taxid_info
            conn = DatabaseManager().get_tax_conn()
            context.tax_data = fetch_taxonomy_data(conn, organisms)
            if taxids:
                context.taxid_info = fetch_taxid_info(conn, taxids)
        else:
            from common.db_taxonomy import fetch_taxonomy_from_ncbi
            context.tax_data = fetch_taxonomy_from_ncbi(organisms)
    except Exception as e:
        print(f"[WARN] taxonomy fetch failed: {e}", file=sys.stderr)
        context.tax_data = {}


def run(args):
    started = datetime.datetime.now(_JST)
    in_path = Path(args.xml)
    if not in_path.exists():
        print(f"[ERROR] Input not found: {in_path}", file=sys.stderr)
        return 2
    skip_db, skip_ncbi, skip_auth = _resolve_modes(args)
    context = ValidationContext(account=args.account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)

    submission, pre_errors = xml_reader.parse_xml(str(in_path), account=args.account)
    out_dir = args.out_dir or str(in_path.parent)

    if submission is None:  # BP_R0001（well-formed でない）
        results = pre_errors
    else:
        if not context.skip_ncbi:
            organisms = sorted({r.organism_name for r in submission.records if r.organism_name})
            taxids = {str(r.tax_id).strip() for r in submission.records
                      if r.tax_id and str(r.tax_id).strip().isdigit()}
            if organisms:
                _fetch_taxonomy(context, organisms, taxids)
        results = pre_errors + Validator(context).run(submission)

    n_proj = len(submission.records) if submission else 0
    now = datetime.datetime.now(_JST)
    when = started.strftime("%Y-%m-%d %H:%M:%S JST")
    elapsed = str(datetime.timedelta(seconds=int((now - started).total_seconds())))
    version = _tool_version()
    summary = build_summary(results, n_proj, in_path.name, version, when, elapsed)
    if args.json:
        write_json_report(results, out_dir, in_path.name, version)
        report_files = ["validation_report.json"]
    else:
        details = build_details(results, in_path.name, version, when, elapsed)
        write_text_reports(summary, details, out_dir)
        report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
    if not args.json:
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
