"""MetaboBank validator の CLI（サブコマンド metabobank / mb）。

入力: `--idf X.idf.txt --sdrf Y.sdrf.txt`、またはディレクトリ（*.idf.txt / *.sdrf.txt を自動検出）。
モード: -l ローカル / -n NCBI / -d 内部DB。-j/--json で JSON 出力。-o 出力先（reports/ ＋ fixed/）。
autofix は fixed/ に IDF/SDRF を書き出す（-f で全適用）。
"""
import argparse
import datetime
import re
import sys

from common import cli_modes
from pathlib import Path

from apps.metabobank.context import ValidationContext
from apps.metabobank import reader
from apps.metabobank.validator import Validator
from apps.metabobank.reporter import (
    build_summary, build_details, write_text_reports, write_json_report,
)

_JST = datetime.timezone(datetime.timedelta(hours=9))


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator metabobank", description="MetaboBank Validator")
    p.add_argument("target", nargs="?", default=None, help="入力ディレクトリ（*.idf.txt / *.sdrf.txt を自動検出）")
    p.add_argument("--idf", default=None, help="IDF ファイル")
    p.add_argument("--sdrf", default=None, help="SDRF ファイル")
    p.add_argument("--account", default=None, help="Submitter id")
    p.add_argument("-o", "--out-dir", default=None, help="出力ディレクトリ（既定: 入力の親）")
    p.add_argument("-l", "--local", action="store_true", help="Local mode (skip DB/NCBI)")
    p.add_argument("-n", "--ncbi-api", action="store_true", help="Use NCBI API, skip internal DB")
    p.add_argument("-d", "--internal-db", action="store_true", help="内部 DDBJ DB を使う")
    p.add_argument("-j", "--json", action="store_true", help="出力を JSON にする")
    p.add_argument("-f", "--force-fix", action="store_true", help="autofix を全適用（fixed/ に出力）")
    p.add_argument("-b", "--biosample", action="store_true",
                   help="SDRF->BioSample の autofix を SSUB 更新 TSV として biosample/ に出力（内部 DB 必須）")
    # -f 時の既定方向（内部/テスト用・非表示）: bs2sdrf=BioSample->SDRF / sdrf2bs=SDRF->BioSample
    p.add_argument("--biosample-apply", choices=["bs2sdrf", "sdrf2bs"], default="bs2sdrf",
                   help=argparse.SUPPRESS)
    return p


def _tool_version():
    return cli_modes.tool_version("apps.metabobank")


def _env_internal_db():
    return cli_modes.env_internal_db()


def _resolve_modes(args):
    return cli_modes.resolve_modes(args)


def _resolve_inputs(args):
    idf, sdrf = args.idf, args.sdrf
    if args.target:
        d = Path(args.target)
        if d.is_dir():
            for p in sorted(d.glob("*.idf.txt")):
                idf = idf or str(p)
            for p in sorted(d.glob("*.sdrf.txt")):
                sdrf = sdrf or str(p)
    return idf, sdrf


def _fetch_biosample_attrs(context, sub, account):
    """参照 SAMD の BioSample 属性を内部 DB から取得（MB_SR0021/0022/0023 用）。core は common/magetab/biosample。

    account が確定していれば allowed（account 所有∪permit）でゲートし、account 外の SAMD は突合しない
    （account 無しは全参照が対象）。allowed は MB_IR0041 用の account_biosamples とも共有する
    （同一の参照 SAMD 集合なので再クエリを避ける）。
    """
    from common.magetab import biosample as _bs
    cols = _bs.ref_columns(context, default=("Comment[BioSample]", "Characteristics[biosample_accession]"))
    _bs.fetch_attrs_gated(context, sub, account, cols, warn_prefix="metabobank BioSample fetch failed",
                          share_account_biosamples=True)


def _fetch_account_bioprojects(context, sub, account):
    """MB_IR0040 用: IDF Comment[BioProject] のうち account 所有 ∪ DRA permit の集合を取得。

    BioSample 側（MB_IR0041 の account_biosamples）は _fetch_biosample_attrs が解決済み。
    取得に失敗しても None のままにして該当ルールをスキップさせる（他の検証は続行）。
    """
    if not account or not sub.idf:
        return
    from common.db_manager import DatabaseManager
    from apps.dra import db_meta

    ref_bp = {v.strip() for v in sub.idf.get("Comment[BioProject]") if v.strip()}
    if not ref_bp:
        return
    cli_modes.db_checking("BioProject DB", len(ref_bp), "project")

    def _fetch():
        dm = DatabaseManager()
        try:
            dra_conn = dm.get_dra_conn()
        except Exception:
            dra_conn = None
        return db_meta.fetch_account_bioprojects(dm.get_bp_conn(), dra_conn, account, ref_bp)

    context.account_bioprojects = cli_modes.warn_none(
        "bp", _fetch, "metabobank account BioProject fetch failed")


def _write_fixed(sub, out_dir):
    """autofix: fixed/ に IDF/SDRF を書き出す（blank_before 整形＋簡易値補正）。"""
    from apps.metabobank.defs import load_definitions
    fixed = Path(out_dir) / "fixed"
    fixed.mkdir(parents=True, exist_ok=True)
    nulls_nr = load_definitions().get("null_values", {}).get("not_recommended", [])
    written = []
    if sub.idf:
        idf = sub.idf
        # Experimental Factor Type ← Name（MB_IR0035）
        names = idf.get("Experimental Factor Name")
        if names and idf.get("Experimental Factor Type") != names:
            idf.fields["Experimental Factor Type"] = list(names)
        lines = []
        for name in idf.field_order:
            if name in idf.blank_before:
                lines.append("")
            vals = []
            for v in idf.get(name):
                vv = v
                m = re.match(r"^(\d{4})/(\d{1,2})/(\d{1,2})$", vv.strip())
                if m:  # 日付 / → -（MB_IR0013）
                    vv = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
                for nr in nulls_nr:
                    if re.fullmatch(nr, vv.strip()):  # 非推奨 null → missing（MB_IR0021）
                        vv = "missing"
                        break
                vals.append(vv)
            lines.append("\t".join([name] + vals))
        p = fixed / Path(idf.raw_path).name
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(str(p))
    if sub.sdrf:
        s = sub.sdrf
        rows = ["\t".join(s.header)] + ["\t".join(r) for r in s.rows]
        p = fixed / Path(s.raw_path).name
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        written.append(str(p))
    return written


def run(args):
    started = datetime.datetime.now(_JST)
    idf_path, sdrf_path = _resolve_inputs(args)
    if not idf_path and not sdrf_path:
        print("[ERROR] 入力がありません（--idf/--sdrf またはディレクトリ）", file=sys.stderr)
        return 2
    for pth in (idf_path, sdrf_path):
        if pth and not Path(pth).exists():
            print(f"[ERROR] Input not found: {pth}", file=sys.stderr)
            return 2

    skip_db, skip_ncbi, skip_auth = _resolve_modes(args)
    # account 未指定なら認証系ルールをスキップ（誤検出防止。ddbj/dra と同方針。
    # mb の BS 突合 MB_SR0021-0023 は SAMD 参照で account 非依存＝requires_rdb のため影響なし）
    if not args.account:
        skip_auth = True
    context = ValidationContext(account=args.account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)
    sub, pre = reader.parse(idf_path, sdrf_path, account=args.account)
    reason = reader.wrong_db_reason(sub)
    if reason:
        print(f"[ERROR] {reason} Aborting MetaboBank validation. (use the correct subcommand)", file=sys.stderr)
        return 2
    out_dir = args.out_dir or str(Path(idf_path or sdrf_path).parent)

    if not args.json:
        cli_modes.print_found(1, "file set")   # idf+sdrf = 1 set
    if not context.skip_db:
        cli_modes.reset_db_access_log()
        _fetch_biosample_attrs(context, sub, args.account)
        if not context.skip_auth:
            _fetch_account_bioprojects(context, sub, args.account)
    results = pre + Validator(context).run(sub)

    now = datetime.datetime.now(_JST)
    when = started.strftime("%Y-%m-%d %H:%M:%S JST")
    elapsed = str(datetime.timedelta(seconds=int((now - started).total_seconds())))
    version = _tool_version()
    label = f"{Path(idf_path).name if idf_path else ''} {Path(sdrf_path).name if sdrf_path else ''}".strip()
    # ヘッダ用: 参照 SAMD の重複排除数 ＋ submission type（Comment[Submission type]）
    from common.magetab import biosample as _bs
    _cols = _bs.ref_columns(context, default=("Comment[BioSample]", "Characteristics[biosample_accession]"))
    sample_count = len(_bs.referenced_samds(sub, _cols)) if sub.sdrf else None
    sub_type = sub.idf.submission_type if sub.idf else ""
    summary = build_summary(results, label, version, when, elapsed, sample_count, sub_type)
    if args.json:
        write_json_report(results, out_dir, label, version)
        report_files = ["validation_report.json"]
    else:
        details = build_details(results, label, version, when, elapsed, sample_count, sub_type)
        write_text_reports(summary, details, out_dir)
        report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
        print(cli_modes.stdout_summary(summary))   # === タイトル行は出さず前後に空行

    # BioSample <-> SDRF 双方向 autofix（MB_SR0023）。内部 DB モードのみ提案が出る。
    from apps.metabobank import autofix
    if args.biosample and context.skip_db:
        print("[WARN] Local mode or --skip-db is enabled. The --biosample (-b) option will be ignored.",
              file=sys.stderr)
    proposals = autofix.build_proposals(results)
    if proposals:
        # -b（biosample_mode）あり時のみ SDRF -> BioSample 提案を出す（無ければ BS -> SDRF のみ）
        autofix.review(proposals, force_fix=args.force_fix,
                       biosample_apply=args.biosample_apply, biosample_mode=args.biosample)
        autofix.write_confirmation(proposals, out_dir)
        autofix.apply_bs2sdrf(sub, proposals)   # sub.sdrf を BioSample 値へ（fixed/ に反映される）
        if args.biosample and not context.skip_db:
            autofix.build_ssub_tsvs(sub, proposals, out_dir, _cols)   # ddbj 体裁で保存メッセージを出力

    # fixed 出力: -f 指定時、または bs2sdrf の autofix が確定した場合に SDRF/IDF を fixed/ へ
    has_bs2sdrf = any(p["direction"] == "bs2sdrf" for p in proposals)
    if args.force_fix or has_bs2sdrf:
        for p in _write_fixed(sub, out_dir):
            print(f"  => fixed file: {p}")

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
