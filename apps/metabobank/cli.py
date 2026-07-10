"""MetaboBank validator の CLI（サブコマンド metabobank / mb）。

入力: `--idf X.idf.txt --sdrf Y.sdrf.txt`、またはディレクトリ（*.idf.txt / *.sdrf.txt を自動検出）。
モード: -l ローカル / -n NCBI / -d 内部DB。-j/--json で JSON 出力。-o 出力先（reports/ ＋ fixed/）。
autofix は fixed/ に IDF/SDRF を書き出す（-f で全適用）。
"""
import argparse
import datetime
import re
import sys
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
    return p


def _tool_version():
    try:
        from apps.metabobank import __version__
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
    return skip_db, skip_ncbi, skip_db


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
    """参照 SAMD の BioSample 属性を内部 DB から取得（MB_SR0021/0022/0023 用）。"""
    try:
        from common.db_manager import DatabaseManager
        samds = set()
        if sub.sdrf:
            for col in ("Comment[BioSample]", "Characteristics[biosample_accession]"):
                for i in sub.sdrf.col_indices(col):
                    for row in sub.sdrf.rows:
                        v = (row[i] if i < len(row) else "").strip()
                        if re.match(r"^SAMD\d+$", v):
                            samds.add(v)
        if not samds:
            context.biosample_attrs = {}
            return
        conn = DatabaseManager().get_bs_conn()
        attrs = {}
        with conn.cursor() as cur:
            cur.execute(
                "SELECT acc.accession_id, attr.attribute_name, attr.attribute_value "
                "FROM mass.attribute attr JOIN mass.accession acc USING(smp_id) "
                "WHERE acc.accession_id = ANY(%s)", (sorted(samds),))
            for acc_id, name, value in cur.fetchall():
                attrs.setdefault(str(acc_id).strip(), {})[str(name).strip()] = value
        context.biosample_attrs = attrs
    except Exception as e:
        print(f"[WARN] metabobank BioSample fetch failed: {e}", file=sys.stderr)
        context.biosample_attrs = None


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
    context = ValidationContext(account=args.account, skip_db=skip_db, skip_ncbi=skip_ncbi, skip_auth=skip_auth)
    sub, pre = reader.parse(idf_path, sdrf_path, account=args.account)
    out_dir = args.out_dir or str(Path(idf_path or sdrf_path).parent)

    if not context.skip_db:
        _fetch_biosample_attrs(context, sub, args.account)
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
