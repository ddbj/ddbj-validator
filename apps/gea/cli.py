"""GEA validator の CLI（サブコマンド gea）。

入力: `--idf X.idf.txt --sdrf Y.sdrf.txt`、またはディレクトリ（*.idf.txt / *.sdrf.txt を自動検出）。
モード: -l ローカル / -n NCBI / -d 内部DB。-j/--json で JSON 出力。-o 出力先（reports/ ＋ fixed/）。
autofix は fixed/ に IDF/SDRF を書き出す（-f で全適用）。BioSample 整合（GEA_BS0003）は BS 値へ寄せる。
"""
import argparse
import datetime
import re
import sys

from common import cli_modes
from pathlib import Path

from apps.gea.context import ValidationContext
from apps.gea import reader
from apps.gea.validator import Validator
from apps.gea.reporter import (
    build_summary, build_details, write_text_reports, write_json_report,
)

_JST = datetime.timezone(datetime.timedelta(hours=9))


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator gea", description="GEA Validator")
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
    return p


def _tool_version():
    return cli_modes.tool_version("apps.gea")


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
    """参照 SAMD の BioSample 属性を内部 DB から取得（GEA_BS0001/0002/0003 用）。core は common/magetab/biosample。"""
    from common.magetab import biosample as _bs
    try:
        context.biosample_attrs = _bs.fetch_biosample_attrs(sub, _bs.ref_columns(context))
    except Exception as e:
        print(f"[WARN] gea BioSample fetch failed: {e}", file=sys.stderr)
        context.biosample_attrs = None


def _fetch_account_refs(context, sub, account):
    """GEA_REF0002 用: account で登録済みの BioProject/BioSample/Run 集合を取得（DRA db_meta 再利用）。

    参照元: IDF Comment[BioProject] / SDRF Comment[BioSample] / SDRF Comment[SRA_RUN]。
    取得ごとに独立に失敗を吸収（1 接続失敗が他を巻き込まない）。
    """
    from common.db_manager import DatabaseManager
    from apps.dra import db_meta
    dm = DatabaseManager()

    def _try(label, fn):
        try:
            return fn()
        except Exception as e:
            print(f"[WARN] gea account ref fetch failed ({label}): {e}", file=sys.stderr)
            return None

    def _sdrf_vals(col):
        out = set()
        if sub.sdrf:
            for i in sub.sdrf.col_indices(col):
                for row in sub.sdrf.rows:
                    v = (row[i] if i < len(row) else "").strip()
                    if v:
                        out.add(v)
        return out

    ref_bp = {v.strip() for v in (sub.idf.get("Comment[BioProject]") if sub.idf else []) if v.strip()}
    ref_bs = _sdrf_vals("Comment[BioSample]")
    ref_drr = _sdrf_vals("Comment[SRA_RUN]")
    dra_conn = _try("dra_conn", dm.get_dra_conn)
    context.account_bioprojects = _try("bp", lambda: db_meta.fetch_account_bioprojects(dm.get_bp_conn(), dra_conn, account, ref_bp))
    context.account_biosamples = _try("bs", lambda: db_meta.fetch_account_biosamples(dm.get_bs_conn(), dra_conn, account, ref_bs))
    context.account_runs = _try("runs", lambda: db_meta.fetch_account_runs(dra_conn, account, ref_drr))

    # GEA 固有 DB メタ（REF0005 ADF / REF0003・0004 DRA linkage）。GEA DB は .env の GEA_DB_NAME から。
    from apps.gea import db_meta as gea_db

    gea_conn = _try("gea_conn", dm.get_gea_conn)
    if gea_conn is not None:
        context.array_designs_registered = _try("adf", lambda: gea_db.fetch_array_designs(gea_conn, account))
    if dra_conn is not None:
        runs_bs = _try("dra_link", lambda: gea_db.fetch_dra_submission_objects(dra_conn, dm.get_bs_conn(), ref_drr))
        if runs_bs:
            context.dra_submission_runs, context.dra_submission_biosamples = runs_bs
        context.dra_run_triples = _try("dra_triples", lambda: gea_db.fetch_dra_run_triples(dra_conn, ref_drr))


def _write_fixed(sub, out_dir, results, context):
    """autofix: fixed/ に IDF/SDRF を書き出す（blank_before 整形＋日付/null 補正＋BioSample 同期）。"""
    from apps.gea.defs import load_definitions
    fixed = Path(out_dir) / "fixed"
    fixed.mkdir(parents=True, exist_ok=True)
    nulls_nr = load_definitions().get("null_values", {}).get("not_recommended", [])
    written = []
    if sub.idf:
        idf = sub.idf
        # Experimental Factor Type ← Name（GEA は Name を Type として使う）
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
                if m:  # 日付 / → -
                    vv = f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
                for nr in nulls_nr:
                    if re.fullmatch(nr, vv.strip()):  # 非推奨 null → missing
                        vv = "missing"
                        break
                vals.append(vv)
            lines.append("\t".join([name] + vals))
        p = fixed / Path(idf.raw_path).name
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(str(p))
    if sub.sdrf:
        s = sub.sdrf
        # BioSample 同期（GEA_BS0003 autofix）: 該当 SAMD 行の Characteristics[attr] を BS 値へ上書き
        fixes = [r for r in results if r.get("autofix") and r.get("samd") and r.get("attr")]
        if fixes:
            ref_cols = context.definitions.get("biosample_sync", {}).get("biosample_ref_columns", [])
            for row in s.rows:
                samd = None
                for col in ref_cols:
                    for i in s.col_indices(col):
                        v = (row[i] if i < len(row) else "").strip()
                        if re.match(r"^SAMD\d+$", v):
                            samd = v
                if not samd:
                    continue
                for fx in fixes:
                    if fx["samd"] != samd:
                        continue
                    for i in s.col_indices(f"Characteristics[{fx['attr']}]"):
                        if i < len(row):
                            row[i] = fx["new_value"]
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
    context = ValidationContext(account=args.account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)
    sub, pre = reader.parse(idf_path, sdrf_path, account=args.account)
    reason = reader.wrong_db_reason(sub)
    if reason:
        print(f"[ERROR] {reason} Aborting GEA validation. (use the correct subcommand)", file=sys.stderr)
        return 2
    out_dir = args.out_dir or str(Path(idf_path or sdrf_path).parent)

    if not context.skip_db:
        _fetch_biosample_attrs(context, sub, args.account)
        _fetch_account_refs(context, sub, args.account)
    results = pre + Validator(context).run(sub)

    now = datetime.datetime.now(_JST)
    when = started.strftime("%Y-%m-%d %H:%M:%S JST")
    elapsed = str(datetime.timedelta(seconds=int((now - started).total_seconds())))
    version = _tool_version()
    label = f"{Path(idf_path).name if idf_path else ''} {Path(sdrf_path).name if sdrf_path else ''}".strip()
    summary = build_summary(results, label, version, when, elapsed)
    if args.json:
        write_json_report(results, out_dir, label, version)
        report_files = ["validation_report.json"]
    else:
        details = build_details(results, label, version, when, elapsed)
        write_text_reports(summary, details, out_dir)
        report_files = ["validation_report_summary.txt", "validation_report_details.txt"]
        print(summary.rstrip("\n"))

    if args.force_fix:
        for p in _write_fixed(sub, out_dir, results, context):
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
