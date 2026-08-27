"""BioProject validator の CLI（サブコマンド bioproject）。

入力は BioProject XML（-x）または DDBJ Record v3 JSON（-r）。Record は record_reader が
XML と同じモデルを組むので、ルールは入力形式を意識しない。実行モードは biosample と同一骨格:
  既定=NCBI API（DB/auth スキップ、taxonomy は NCBI）。env DDBJ_VALIDATOR_INTERNAL_DB=1 or -d で内部DB(curator)。
  -l 完全ローカル / -n NCBI / -d 内部DB。出力は既定 TSV（summary＋details）、-j で JSON。
"""
import argparse
import datetime
import re
import sys

from common import cli_modes
from pathlib import Path

from apps.bioproject.context import ValidationContext
from apps.bioproject import record_reader, xml_reader
from apps.bioproject.validator import Validator
from apps.bioproject.reporter import (
    build_summary, build_details, write_text_reports, write_json_report,
)

_JST = datetime.timezone(datetime.timedelta(hours=9))


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator bioproject", description="BioProject Validator")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("-x", "--xml", dest="xml", default=None, help="BioProject XML 入力ファイル")
    g.add_argument("-r", "--record", dest="record", default=None,
                   help="DDBJ Record 入力ファイル (v3 JSON)。project を検証する")
    p.add_argument("--account", default=None, help="Submitter id (account) for auth-dependent rules")
    p.add_argument("-o", "--out-dir", default=None, help="Output directory (default: input's parent)")
    p.add_argument("-l", "--local", action="store_true", help="Local mode (skip DB and NCBI API)")
    p.add_argument("-n", "--ncbi-api", action="store_true", help="Use NCBI API, skip internal DB (一般ユーザ既定)")
    p.add_argument("-d", "--internal-db", action="store_true", help="内部 DDBJ DB を使う curator モード")
    p.add_argument("-j", "--json", action="store_true", help="出力を JSON にする（既定は TSV）")
    return p


def _tool_version():
    return cli_modes.tool_version("apps.bioproject")


def _env_internal_db():
    return cli_modes.env_internal_db()


def _resolve_modes(args):
    return cli_modes.resolve_modes(args)


def _fetch_taxonomy(context, organisms, taxids):
    """organism 群の taxonomy を context.tax_data / taxid_info へ。default=内部DB / -n=NCBI。"""
    try:
        if not context.skip_db:
            from common.db_manager import DatabaseManager
            from common.db_taxonomy import fetch_taxonomy_data, fetch_taxid_info
            cli_modes.db_checking("Taxonomy DB", len(organisms), "organism")
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


def _fetch_db_meta(context, submission, account):
    """内部 DB 依存ルール用メタを context へ（BP_R0016 umbrella / R0021 prefix↔SAMD / R0004 重複）。"""
    try:
        from common.db_manager import DatabaseManager
        from apps.bioproject import db_meta
        dm = DatabaseManager()
        umbrella_refs = {a for r in submission.records for a in r.umbrella_member_ids if a}
        samds = {(lt.get("biosample_id") or "").strip()
                 for r in submission.records for lt in r.locus_tags if lt.get("biosample_id")}
        cli_modes.db_checking("BioProject DB", len(umbrella_refs), "umbrella project")
        cli_modes.db_checking("BioSample DB", len(samds), "sample")
        context.umbrella_ok = (db_meta.fetch_umbrella_accessions(dm.get_bp_conn(), umbrella_refs)
                               if umbrella_refs else set())
        context.bs_locus_prefix = (db_meta.fetch_biosample_locus_prefix(dm.get_bs_conn(), samds)
                                   if samds else {})
        if account:
            context.project_names = db_meta.fetch_account_project_names(dm.get_bp_conn(), account)
    except Exception as e:
        print(f"[WARN] bioproject DB meta fetch failed: {e}", file=sys.stderr)


def _psub_from_path(in_path):
    """入力ファイル名から PSUB submission id を抽出（例 PSUB008052.xml → PSUB008052）。"""
    m = re.search(r"PSUB\d+", Path(in_path).name, re.IGNORECASE)
    return m.group(0).upper() if m else None


def _account_from_psub(psub):
    """PSUB から submitter_id（account）を内部 BioProject DB で解決。失敗時 None。"""
    if not psub:
        return None
    try:
        from common.db_manager import DatabaseManager
        from apps.bioproject import db_meta
        return db_meta.fetch_submitter_by_submission(DatabaseManager().get_bp_conn(), psub)
    except Exception as e:
        print(f"[WARN] account auto-derivation from {psub} failed: {e}", file=sys.stderr)
        return None


def run(args):
    started   = datetime.datetime.now(_JST)
    is_record = bool(args.record)
    in_path   = Path(args.record or args.xml)
    if not in_path.exists():
        print(f"[ERROR] Input not found: {in_path}", file=sys.stderr)
        return 2
    skip_db, skip_ncbi, skip_auth = _resolve_modes(args)
    # account 未指定なら PSUB（ファイル名）から自動導出（内部 DB モードのみ）。導出できなければ認証系スキップ。
    submission_id = _psub_from_path(in_path)
    account = args.account or (_account_from_psub(submission_id) if not skip_db else None)
    if not account:
        skip_auth = True
    context = ValidationContext(account=account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)
    context.self_submission_id = submission_id   # BP_R0004 の自己除外にも使う

    if is_record:
        submission, pre_errors = record_reader.parse_record(str(in_path), account=account)
    else:
        submission, pre_errors = xml_reader.parse_xml(str(in_path), account=account)
    out_dir = args.out_dir or str(in_path.parent)

    if not args.json:
        cli_modes.print_found(1, "file")   # BioProject は XML / Record いずれも 1 ファイル

    # 読めたが検証対象が無い。「project 0 件」を「指摘 0 件」として返すと、渡す record を
    # 間違えた側は成功したと読む。指摘が 1 件も無いのにレポートを書くと「検証して問題なし」に
    # 見えるので、書かずに入力エラーで落とす。
    if is_record and submission is not None and not submission.records:
        print(f"[ERROR] No project in record: {in_path}", file=sys.stderr)
        if not pre_errors:
            # 指摘ゼロのレポートを書くと「検証して問題なし」に見える。書かずに落とす
            # （レポートが無ければ web api 側も「検証は成立していない」と扱う）。
            return 2
        # スキーマ違反は実際の指摘なので通常経路でレポートに残す。project 0 件なので
        # ルールは何も出さず、結果は pre_errors だけになる。

    if submission is None:  # BP_R0001（well-formed でない）
        results = pre_errors
    else:
        cli_modes.reset_db_access_log()
        if not context.skip_ncbi:
            organisms = sorted({r.organism_name for r in submission.records if r.organism_name})
            taxids = {str(r.tax_id).strip() for r in submission.records
                      if r.tax_id and str(r.tax_id).strip().isdigit()}
            if organisms:
                _fetch_taxonomy(context, organisms, taxids)
        if not context.skip_db:   # 内部 DB モードのみ: umbrella/locus_tag/重複 用メタ
            _fetch_db_meta(context, submission, account)
        results = pre_errors + Validator(context).run(submission)

    n_proj = len(submission.records) if submission else 0
    now = datetime.datetime.now(_JST)
    when = started.strftime("%Y-%m-%d %H:%M:%S JST")
    elapsed = str(datetime.timedelta(seconds=int((now - started).total_seconds())))
    version = _tool_version()
    summary = build_summary(results, n_proj, in_path.name, version, when, elapsed,
                            submission_id=submission_id, account=account)
    if args.json:
        write_json_report(results, out_dir, in_path.name, version)
        report_files = ["validation_report.json"]
    else:
        details = build_details(results, in_path.name, version, when, elapsed)
        write_text_reports(summary, details, out_dir)
        report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
    if not args.json:
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
