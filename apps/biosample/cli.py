"""BioSample validator の CLI（サブコマンド biosample）。

入力は XML（-x）/ TSV（-t）/ DDBJ Record v3 JSON（-r）。TSV は XML へ変換してから検証する。
Record は record_reader が XML と同じモデルを組むので、ルールは入力形式を意識しない。
  ddbj-validator biosample (-x <xml> | -t <tsv> | -r <record.json>) [-s SSUBxxxx] [-p <package>] [--account ID] [-o OUT] [-l|-n|-d] [-j]
実行モード: 既定は一般ユーザ向け NCBI API モード（内部DB/auth スキップ、taxonomy は NCBI。ddbj v と同じ公開モード）。
  curator は環境変数 DDBJ_VALIDATOR_INTERNAL_DB=1（.bashrc 等に1回）で既定を内部DBモードにできる。明示フラグ -l/-n/-d は常に優先。
出力: 既定は ddbj v 風の TSV（summary＋details、summary は標準出力）。-j 指定で result.json 互換 JSON。
autofix の修正済みファイルは入力形式に従う（XML/TSV → XML、Record → Record）。
TSV 入力の submission_id / package は -s / -p で指定。省略時はファイル名 `SSUBxxxx.<Package>.txt` から補完
（-s/-p が優先。ファイル名から必要値が得られない場合はエラー終了）。
"""
import argparse
import datetime
import sys
import tempfile
from pathlib import Path

from common import cli_modes
from apps.biosample.context import ValidationContext
from apps.biosample import xml_reader, tsv_to_xml, record_reader, autofix
from apps.biosample.validator import Validator
from apps.biosample.reporter import (
    build_summary, build_details, build_autofix_lines,
    write_text_reports, write_autofix_confirmation, write_json_report,
)

_JST = datetime.timezone(datetime.timedelta(hours=9))


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator biosample", description="BioSample Validator")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("-x", "--xml", dest="xml", default=None, help="BioSample XML 入力ファイル")
    g.add_argument("-t", "--tsv", dest="tsv", default=None, help="BioSample TSV 入力ファイル (.txt/.tsv)")
    g.add_argument("-r", "--record", dest="record", default=None,
                   help="DDBJ Record 入力ファイル (v3 JSON)。samples[] を検証する")
    p.add_argument("-s", "--submission-id", dest="submission_id", default=None,
                   help="TSV/Record 入力の submission id（例 SSUB000001）。TSV は省略時ファイル名から補完。"
                        "Record は SSUB を持たないため、必要ならここで渡す")
    p.add_argument("-p", "--package", dest="package", default=None,
                   help="TSV 入力の package full name（例 Human / MIGS.ba）。省略時はファイル名から補完")
    p.add_argument("--account", default=None, help="Submitter id (account) for auth-dependent rules")
    p.add_argument("-o", "--out-dir", default=None, help="Output directory (default: input's parent)")
    p.add_argument("-l", "--local", action="store_true", help="Local mode (skip DB and NCBI API)")
    p.add_argument("-n", "--ncbi-api", action="store_true", help="Use NCBI API, skip internal DB (一般ユーザ既定)")
    p.add_argument("-d", "--internal-db", action="store_true",
                   help="内部 DDBJ DB を使う curator モード（env DDBJ_VALIDATOR_INTERNAL_DB でも既定化可）")
    p.add_argument("-j", "--json", action="store_true",
                   help="出力を result.json 互換 JSON にする（既定は TSV summary＋details）")
    return p


def _tool_version():
    """biosample アプリのバージョン（apps/biosample/__init__.py の __version__）。ddbj と独立管理。"""
    try:
        from apps.biosample import __version__
        return __version__
    except Exception:
        return "unknown"


def _env_internal_db():
    """環境変数 DDBJ_VALIDATOR_INTERNAL_DB が truthy かどうか（curator 用の既定モード切替）。"""
    import os
    return os.environ.get("DDBJ_VALIDATOR_INTERNAL_DB", "").strip().lower() not in ("", "0", "false", "no")


def _resolve_modes(args):
    """実行モードを解決。
    明示フラグ（-l/-n/-d）が最優先。無ければ環境変数 DDBJ_VALIDATOR_INTERNAL_DB（curator 用）で内部DB、
    それも無ければ一般ユーザ既定 = NCBI API モード（DB/auth スキップ、taxonomy は NCBI。ddbj v と同じ公開モード）。
    """
    if args.local:                       # -l: 完全ローカル（DB/NCBI 無し）
        skip_db, skip_ncbi = True, True
    elif args.ncbi_api:                  # -n: NCBI API（DB スキップ）
        skip_db, skip_ncbi = True, False
    elif args.internal_db:               # -d: 内部DB（明示）
        skip_db, skip_ncbi = False, False
    elif _env_internal_db():             # env: curator 既定 = 内部DB
        skip_db, skip_ncbi = False, False
    else:                                # 一般ユーザ既定 = NCBI API
        skip_db, skip_ncbi = True, False
    skip_auth = skip_db  # DB が無ければ認証検証不可（ddbj と同じ強制）
    return skip_db, skip_ncbi, skip_auth


def _resolve_tsv_meta(tsv_path, arg_sub, arg_pkg):
    """TSV 入力の (submission_id, package) を解決。-s/-p 優先、無ければファイル名から補完。
    必要値が特定できなければ (None, エラーメッセージ) を返す。"""
    fn_sub, fn_pkg = tsv_to_xml.parse_filename(tsv_path)
    submission_id = arg_sub or fn_sub
    package = arg_pkg or fn_pkg
    if not submission_id:
        return None, "submission_id を特定できません。-s で指定するか、ファイル名を SSUBxxxx.<Package>.txt にしてください。"
    if not package:
        return None, "package を特定できません。-p で指定するか、ファイル名を SSUBxxxx.<Package>.txt にしてください。"
    return (submission_id, package), None


def _finalize(args, results, records, in_path, out_dir, submission_id, package, started, fixed_path):
    """レポート出力（ファイル）＋標準出力を仕様どおりに行う。戻り値: レベル別 error 件数を含む counts。"""
    now = datetime.datetime.now(_JST)
    when = started.strftime("%Y-%m-%d %H:%M:%S JST")
    elapsed = str(datetime.timedelta(seconds=int((now - started).total_seconds())))
    version = _tool_version()
    sample_count = len(records)
    autofix_lines = build_autofix_lines(results)
    reports_dir = Path(out_dir) / "reports"

    summary_text = build_summary(results, sample_count, in_path.name, submission_id, package, version, when, elapsed)
    if args.json:
        write_json_report(results, out_dir, in_path.name, version)
        report_files = ["validation_report.json"]
    else:
        details_text = build_details(results, records, sample_count, in_path.name, submission_id, package, version, when, elapsed)
        write_text_reports(summary_text, details_text, out_dir)
        report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
    # autofix 内容は -j の有無に関わらずファイル出力
    write_autofix_confirmation(autofix_lines, out_dir)

    # 標準出力（-j 以外は summary 本文を先頭に。以降 [Auto-Fix] → saved → reports は共通で stdout のみ）
    parts = []
    if not args.json:
        parts.append(cli_modes.stdout_summary(summary_text).strip("\n"))   # === タイトル行は出さない
    if autofix_lines:
        parts.append("[ Auto-Fix ]\n" + "\n".join(autofix_lines))
        if fixed_path:
            parts.append(f"=> Auto-fixed {_fixed_label(fixed_path)} saved to: {fixed_path}")
    parts.append(f"[ All reports successfully generated to {reports_dir} ]\n"
                 + "\n".join(f"  {f}" for f in report_files))
    print("\n" + "\n\n".join(parts))   # DB チェック/Found 行との間に空行

    return {"error": sum(1 for r in results if r.get("level") == "error")}


def _fixed_label(fixed_path):
    """autofix 出力の呼び名。ddbj の "Auto-fixed ANN saved to" と同じ形にする。"""
    return "Record" if fixed_path.suffix.lower() == ".json" else "XML"


def _ssub_from_name(path):
    """ファイル名の stem が SSUB で始まれば submission_id を補完（root 属性・-s が無い場合のフォールバック）。"""
    import re
    m = re.match(r"(SSUB\d+)", Path(path).stem)
    return m.group(1) if m else None


def run(args):
    started = datetime.datetime.now(_JST)
    is_tsv = bool(args.tsv)
    is_record = bool(args.record)
    in_path = Path(args.record or args.tsv or args.xml)
    if not in_path.exists():
        print(f"[ERROR] Input not found: {in_path}", file=sys.stderr)
        return 2

    if is_record and args.package:
        # record の package は samples[].package から取る。黙って無視すると、
        # 指定したつもりの package で検証されたと読まれる。
        print("[ERROR] -p/--package is not used with -r/--record; "
              "the package is taken from samples[].package.", file=sys.stderr)
        return 2

    skip_db, skip_ncbi, skip_auth = _resolve_modes(args)
    # --account は curator（内部DB）モードでのみ有効。他モードでは auth 検証ができないため abort（英語メッセージ）。
    if args.account and skip_db:
        print("[ERROR] --account is only valid in curator mode (internal DB). "
              "Use -d/--internal-db or set DDBJ_VALIDATOR_INTERNAL_DB=1; do not combine --account with -n/-l.",
              file=sys.stderr)
        return 2
    context = ValidationContext(account=args.account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)

    if not args.json:
        cli_modes.print_found(1, "file")   # BioSample は TSV/XML/Record いずれも 1 ファイル

    # TSV は XML へ変換してから検証（検証パスは XML 一本）。Record は専用 reader。
    submission_id = None
    if is_record:
        fix_source = str(in_path)
        # record は SSUB を持たないので -s がそのまま submission_id になる。
        # 渡されないと BS_R0091 が自分自身の locus_tag_prefix を重複と報告する。
        submission_id = args.submission_id
        if not submission_id:
            print("[WARN] --submission-id が指定されていません。登録済みの submission を"
                  "再検証する場合、自分自身の locus_tag_prefix が重複として報告されます "
                  "(BS_R0091)。", file=sys.stderr)
        try:
            submission, pre_errors = record_reader.parse_record(
                str(in_path), submission_id=submission_id, account=args.account)
        except record_reader.Unsupported as e:
            # レポートを書かずに落とす。書くと「検証して問題なし」に見える。
            print(f"[ERROR] {e}", file=sys.stderr)
            return 2
    else:
        if is_tsv:
            meta, err = _resolve_tsv_meta(str(in_path), args.submission_id, args.package)
            if err:
                print(f"[ERROR] {err}", file=sys.stderr)
                return 2
            submission_id, package = meta
            xml_text = tsv_to_xml.tsv_to_xml(str(in_path), package=package, submission_id=submission_id)
            tmp = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
            tmp.write(xml_text or "")
            tmp.close()
            fix_source = tmp.name
        else:
            fix_source = str(in_path)
        submission, pre_errors = xml_reader.parse_xml(fix_source, submission_id=submission_id,
                                                      account=args.account)

    out_dir = args.out_dir or str(in_path.parent)
    if submission is None:
        # 整形不正（R0097 等）でパース不可（サンプル 0）
        counts = _finalize(args, pre_errors, [], in_path, out_dir,
                           submission_id or _ssub_from_name(in_path), None, started, None)
        return 1 if counts.get("error") else 0

    # 読めたが検証対象が無い。「サンプル 0 件」を「指摘 0 件」として返すと、渡す record を
    # 間違えた側は成功したと読むので、入力エラーとして落とす。ただしスキーマ違反などの
    # pre_errors は握りつぶさずレポートに残す（落とす理由と別の問題が同時にあり得る）。
    if is_record and not submission.records:
        print(f"[ERROR] No samples in record: {in_path}", file=sys.stderr)
        if pre_errors:
            # スキーマ違反は実際の指摘なので残す。error 級なので「問題なし」とは読まれない。
            _finalize(args, pre_errors, [], in_path, out_dir,
                      submission_id or _ssub_from_name(in_path), None, started, None)
            return 1
        # 指摘ゼロのレポートを書くと「検証して問題なし」に見える。書かずに入力エラーで落とす
        # （レポートが無ければ web api 側も「検証は成立していない」と扱う）。
        return 2

    # account が --account 未指定でも XML ルートの submitter_id から解決できていれば採用（互換）
    if not context.account and submission.account:
        context.account = submission.account
    # account を特定できない場合は認証系ルール（requires_auth）をスキップ（誤検出防止。ddbj/dra と同方針）
    if not context.account:
        context.skip_auth = True

    cli_modes.reset_db_access_log()
    # taxonomy 取得（local では skip。default=内部DB、-n=NCBI API）
    # organism に加え、R0105 用に component_organism も解決対象に含める。
    if not context.skip_ncbi:
        names = {r.organism for r in submission.records if r.organism}
        for r in submission.records:
            names.update(v for v in r.attr_values("component_organism") if v)
            names.update(v for v in r.attr_values("host") if v)  # R0015 用
            names.update(v for v in r.attr_values("metagenome_source") if v)  # R0106 用
        organisms = sorted(names)
        # BS_R0004/R0096/R0142 用: 記載 taxonomy_id ＋ 数値 organism（taxid 記載）を taxid→学名解決対象に
        taxids = {str(r.taxonomy_id).strip() for r in submission.records
                  if getattr(r, "taxonomy_id", None) and str(r.taxonomy_id).strip().isdigit()}
        taxids |= {r.organism.strip() for r in submission.records
                   if r.organism and r.organism.strip().isdigit()}
        if organisms:
            _fetch_taxonomy(context, organisms, taxids)

    # account/BioProject 取得（内部DB。skip_auth／account 未指定では実行しない）
    if not context.skip_auth and context.account:
        _fetch_account(context, submission)

    # biosample DB 登録済み locus_tag_prefix 取得（R0091。内部DB モードのみ）
    if not context.skip_db:
        _fetch_registered_prefixes(context)

    results = pre_errors + Validator(context).run(submission)

    # autofix 全自動適用（対話なし）→ 修正済みファイルを fixed/ に出力（先に適用して保存先を確定）。
    # 入力が TSV でも出力は XML（検証パスと同一の XML を元に修正）。Record 入力なら Record。
    autofix.clean_fixed_dir(out_dir)
    if is_record:
        fixed_name = in_path.stem + ".json"
        n_fixed = autofix.apply_autofix_record(fix_source, results, out_dir, fixed_name)
    else:
        fixed_name = in_path.name if not is_tsv else (in_path.stem + ".xml")
        n_fixed = autofix.apply_autofix(fix_source, results, out_dir, fixed_name)
    fixed_path = (Path(out_dir) / "fixed" / fixed_name) if n_fixed else None

    package = submission.package or (submission.records[0].package if submission.records else None)
    sub_id = submission.submission_id or submission_id or _ssub_from_name(in_path)
    counts = _finalize(args, results, submission.records, in_path, out_dir, sub_id, package, started,
                       fixed_path)
    return 1 if counts.get("error") else 0


def _fetch_taxonomy(context, organisms, taxids=None):
    """organism 群の taxonomy 情報を context.tax_data へ。default=内部DB / -n=NCBI。失敗時は空。
    内部DBモードでは taxids（記載 taxonomy_id）→ {学名, rank, is_species_or_below} も取得し context.taxid_info へ（BS_R0004/R0096 用）。"""
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


def _fetch_account(context, submission):
    """account 認証に必要な情報を内部DBから取得（D 群 R0006/0129/0070/0095 用）。

    最適化: アカウント保有の全アクセッションを取得せず、**submission が参照する
    bioproject_id / derived_from(SAMD) のみ** を対象に所属判定する（大規模アカウントの固定コスト回避）。
    参照が 1 つも無ければ認証系ルールは何も判定しないため、DB 問い合わせ自体を行わない。
    """
    try:
        import re
        from common.db_manager import DatabaseManager
        from common.db_meta import fetch_bp_psubs, fetch_prjdb_by_psub
        from apps.biosample.db_meta import fetch_authorized_refs, fetch_authorized_bp_submissions

        samd_re = re.compile(r"SAMD\d+", re.IGNORECASE)
        # submission が参照する bioproject_id（PRJDB/PSUB）と derived_from(SAMD)
        ref_bps = {r.attr("bioproject_id").strip().upper()
                   for r in submission.records if r.attr("bioproject_id")}
        ref_prjdb = {b for b in ref_bps if b.startswith("PRJDB")}
        ref_psub = {b for b in ref_bps if b.startswith("PSUB")}
        ref_samds = set()
        for r in submission.records:
            v = r.attr("derived_from")
            if v:
                ref_samds.update(m.upper() for m in samd_re.findall(v))

        # 参照が無ければ R0006/R0129/R0095 は何も出さない → DB アクセス不要
        if not ref_bps and not ref_samds:
            return

        cli_modes.db_checking("BioProject DB", len(ref_bps), "project")
        cli_modes.db_checking("BioSample DB", len(ref_samds), "sample")
        dm = DatabaseManager()
        bp_conn = dm.get_bp_conn()
        bs_conn = dm.get_bs_conn()
        dra_conn = dm.get_dra_conn()

        # PSUB -> PRJDB 置換候補（R0095）。解決される PRJDB も所属判定対象に含める。
        if ref_psub:
            context.psub_to_prjd = fetch_prjdb_by_psub(bp_conn, sorted(ref_psub)) or {}
            ref_prjdb |= {info["accession"].upper() for info in context.psub_to_prjd.values()
                          if info.get("accession")}

        # 直接参照された PRJDB の BioProject メタ（R0070 umbrella 判定）
        direct_prjdb = sorted(b for b in ref_bps if b.startswith("PRJDB"))
        if direct_prjdb:
            context.bp_meta = fetch_bp_psubs(bp_conn, direct_prjdb) or {}

        # 参照分のみの所属判定（アカウント保有数に非依存）
        proj, samd = fetch_authorized_refs(bp_conn, bs_conn, dra_conn, context.account,
                                           ref_prjdb, ref_samds)
        context.authorized_projects = proj
        context.authorized_samds = samd
        # bioproject_id は PSUB でも書かれ得るため、参照 PSUB の所属も合流（R0006）
        context.authorized_projects |= fetch_authorized_bp_submissions(
            bp_conn, dra_conn, context.account, referenced=ref_psub)
    except Exception as e:
        print(f"[WARN] account/bioproject fetch failed: {e}", file=sys.stderr)


def _fetch_registered_prefixes(context):
    """biosample DB 登録済みの locus_tag_prefix を context に取得（R0091 用）。"""
    try:
        from common.db_manager import DatabaseManager
        from apps.biosample.db_meta import fetch_registered_locus_tag_prefixes
        cli_modes.db_checking("BioSample DB", 1, "locus_tag_prefix set")
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
