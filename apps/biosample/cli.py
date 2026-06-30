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
from apps.biosample import xml_reader, tsv_to_xml
from apps.biosample.validator import Validator
from apps.biosample.reporter import write_reports


def _build_parser():
    p = argparse.ArgumentParser(prog="ddbj-validator biosample", description="BioSample Validator")
    p.add_argument("input", help="BioSample XML, or SSUBxxxxxx_<Package>.txt (TSV)")
    p.add_argument("--account", default=None, help="Submitter id (account) for auth-dependent rules")
    p.add_argument("-o", "--out-dir", default=None, help="Output directory (default: input's parent)")
    p.add_argument("-l", "--local", action="store_true", help="Local mode (skip DB and NCBI API)")
    p.add_argument("-n", "--ncbi-api", action="store_true", help="Use NCBI API, skip internal DB")
    return p


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
        return 1 if counts.get("error") else 0

    results = pre_errors + Validator(context).run(submission)
    counts = write_reports(results, out_dir, in_path.name)
    return 1 if counts.get("error") else 0


def main():
    args = _build_parser().parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
