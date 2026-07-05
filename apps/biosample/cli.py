"""BioSample validator の CLI（サブコマンド biosample）。

入力は XML（正準）。TSV (.txt/.tsv) は XML へ変換してから検証する。
  ddbj-validator biosample <input.xml|SSUBxxxx_Package.txt> [--account ID] [-o OUT] [-l|-n]
パッケージ補完: TSV はファイル名 `SSUBxxxxxx_<Package>.txt` から。account は --account で渡す。
"""
import argparse
import sys
import tempfile
from pathlib import Path

from apps.biosample.context import ValidationContext
from apps.biosample import xml_reader, tsv_to_xml, autofix
from apps.biosample.validator import Validator
from apps.biosample.reporter import write_reports, write_json_report


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator biosample", description="BioSample Validator")
    p.add_argument("input", help="BioSample XML, or SSUBxxxxxx_<Package>.txt (TSV)")
    p.add_argument("--account", default=None, help="Submitter id (account) for auth-dependent rules")
    p.add_argument("-o", "--out-dir", default=None, help="Output directory (default: input's parent)")
    p.add_argument("-l", "--local", action="store_true", help="Local mode (skip DB and NCBI API)")
    p.add_argument("-n", "--ncbi-api", action="store_true", help="Use NCBI API, skip internal DB")
    p.add_argument("-j", "--json", action="store_true",
                   help="Also emit reports/validation_report.json (flat result.json format)")
    return p


def _tool_version():
    """pyproject.toml から本ツールのバージョンを取得（取得失敗時は 'unknown'）。"""
    try:
        import tomllib
        with open(Path(__file__).resolve().parents[2] / "pyproject.toml", "rb") as f:
            return tomllib.load(f).get("project", {}).get("version", "unknown")
    except Exception:
        try:
            import toml
            data = toml.load(Path(__file__).resolve().parents[2] / "pyproject.toml")
            return data.get("project", {}).get("version", "unknown")
        except Exception:
            return "unknown"


def _resolve_modes(args):
    skip_db = bool(args.local or args.ncbi_api)
    skip_ncbi = bool(args.local)
    skip_auth = skip_db  # DB が無ければ認証検証不可（ddbj と同じ強制）
    return skip_db, skip_ncbi, skip_auth


def run(args):
    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[ERROR] Input not found: {in_path}", file=sys.stderr)
        return 2

    skip_db, skip_ncbi, skip_auth = _resolve_modes(args)
    context = ValidationContext(account=args.account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)

    # TSV は XML へ変換してから検証（検証パスは XML 一本）
    is_tsv = in_path.suffix.lower() in (".txt", ".tsv")
    submission_id = None
    if is_tsv:
        xml_text = tsv_to_xml.tsv_to_xml(str(in_path))
        submission_id, _pkg = tsv_to_xml.parse_filename(str(in_path))
        tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
        tmp.write(xml_text or "")
        tmp.close()
        xml_for_parse = tmp.name
    else:
        xml_for_parse = str(in_path)

    submission, pre_errors = xml_reader.parse_xml(xml_for_parse, submission_id=submission_id, account=args.account)

    out_dir = args.out_dir or str(in_path.parent)
    if submission is None:
        # 整形不正（R0097 等）でパース不可
        counts = write_reports(pre_errors, out_dir, in_path.name)
        if args.json:
            write_json_report(pre_errors, out_dir, in_path.name, _tool_version())
        return 1 if counts.get("error") else 0

    # account が --account 未指定でも XML ルートの submitter_id から解決できていれば採用（互換）
    if not context.account and submission.account:
        context.account = submission.account

    # taxonomy 取得（local では skip。default=内部DB、-n=NCBI API）
    # organism に加え、R0105 用に component_organism も解決対象に含める。
    if not context.skip_ncbi:
        names = {r.organism for r in submission.records if r.organism}
        for r in submission.records:
            names.update(v for v in r.attr_values("component_organism") if v)
            names.update(v for v in r.attr_values("host") if v)  # R0015 用
            names.update(v for v in r.attr_values("metagenome_source") if v)  # R0106 用
        organisms = sorted(names)
        if organisms:
            _fetch_taxonomy(context, organisms)

    # account/BioProject 取得（内部DB。skip_auth／account 未指定では実行しない）
    if not context.skip_auth and context.account:
        _fetch_account(context, submission)

    # biosample DB 登録済み locus_tag_prefix 取得（R0091。内部DB モードのみ）
    if not context.skip_db:
        _fetch_registered_prefixes(context)

    results = pre_errors + Validator(context).run(submission)
    counts = write_reports(results, out_dir, in_path.name)
    if args.json:
        write_json_report(results, out_dir, in_path.name, _tool_version())

    # autofix 全自動適用（対話なし）。修正済み XML を fixed/ に出力。
    # 入力が TSV でも出力は XML（検証パスと同一の XML を元に修正）。
    autofix.clean_fixed_dir(out_dir)
    fixed_name = in_path.name if not is_tsv else (in_path.stem + ".xml")
    n_fixed = autofix.apply_autofix(xml_for_parse, results, out_dir, fixed_name)
    if n_fixed:
        print(f"[autofix] applied {n_fixed} fix(es) -> {Path(out_dir) / 'fixed' / fixed_name}")

    return 1 if counts.get("error") else 0


def _fetch_taxonomy(context, organisms):
    """organism 群の taxonomy 情報を context.tax_data へ。default=内部DB / -n=NCBI。失敗時は空。"""
    try:
        if not context.skip_db:
            from common.db_manager import DatabaseManager
            from common.db_taxonomy import fetch_taxonomy_data
            context.tax_data = fetch_taxonomy_data(DatabaseManager().get_tax_conn(), organisms)
        else:
            from common.db_taxonomy import fetch_taxonomy_from_ncbi
            context.tax_data = fetch_taxonomy_from_ncbi(organisms)
    except Exception as e:
        print(f"[WARN] taxonomy fetch failed: {e}", file=sys.stderr)
        context.tax_data = {}


def _fetch_account(context, submission):
    """account 所属アクセッション／BioProject メタを内部DBから取得（D 群 R0006/0129/0070/0095 用）。

    共通 DB fetch は common.db_meta（ddbj 実装の re-export）を単一入口として利用する。
    """
    try:
        from common.db_manager import DatabaseManager
        from common.db_meta import (
            fetch_authorized_accessions,
            fetch_bp_psubs,
            fetch_prjdb_by_psub,
        )
        from apps.biosample.db_meta import fetch_authorized_bp_submissions
        dm = DatabaseManager()
        bp_conn = dm.get_bp_conn()
        bs_conn = dm.get_bs_conn()
        dra_conn = dm.get_dra_conn()
        # account 所属（BioProject/BioSample）
        proj, samd, _dra = fetch_authorized_accessions(bp_conn, bs_conn, dra_conn, context.account)
        context.authorized_projects = proj or set()
        context.authorized_samds = samd or set()
        # bioproject_id は PSUB（submission id）でも書かれ得るため、参照可 PSUB も許可集合に合流（R0006）
        context.authorized_projects |= fetch_authorized_bp_submissions(bp_conn, dra_conn, context.account)
        # 提出中の bioproject_id を収集し、PRJDB=メタ / PSUB=置換候補を解決
        bps = {
            r.attr("bioproject_id").strip()
            for r in submission.records
            if r.attr("bioproject_id")
        }
        prjdb = [b for b in bps if b.upper().startswith("PRJDB")]
        psub = [b for b in bps if b.upper().startswith("PSUB")]
        if prjdb:
            context.bp_meta = fetch_bp_psubs(bp_conn, prjdb) or {}
        if psub:
            context.psub_to_prjd = fetch_prjdb_by_psub(bp_conn, psub) or {}
    except Exception as e:
        print(f"[WARN] account/bioproject fetch failed: {e}", file=sys.stderr)


def _fetch_registered_prefixes(context):
    """biosample DB 登録済みの locus_tag_prefix を context に取得（R0091 用）。"""
    try:
        from common.db_manager import DatabaseManager
        from apps.biosample.db_meta import fetch_registered_locus_tag_prefixes
        bs_conn = DatabaseManager().get_bs_conn()
        context.registered_locus_tag_prefixes = fetch_registered_locus_tag_prefixes(bs_conn) or {}
    except Exception as e:
        print(f"[WARN] locus_tag_prefix fetch failed: {e}", file=sys.stderr)


def main():
    # 内部 DB（taxonomy 等）接続のため .env を読み込む（ddbj cli と同様）
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    args = _build_parser().parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
