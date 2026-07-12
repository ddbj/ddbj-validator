#!/usr/bin/env python3

import sys
import argparse

# 既知のトップレベルサブコマンド（将来サブコマンドが増えたらここに追加）
KNOWN_COMMANDS = {"ddbj", "biosample", "bioproject", "dra", "metabobank", "mb", "gea"}

def main():
    parser = argparse.ArgumentParser(
        description="DDBJ Validation Tools",
        usage="ddbj-validator [ddbj|biosample|bioproject] [<args>]",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("ddbj", help="Run DDBJ Validator")
    subparsers.add_parser("biosample", help="Run BioSample Validator")
    subparsers.add_parser("bioproject", help="Run BioProject Validator")
    subparsers.add_parser("dra", help="Run DRA Validator")
    subparsers.add_parser("metabobank", help="Run MetaboBank Validator")
    subparsers.add_parser("mb", help="Run MetaboBank Validator (alias)")
    subparsers.add_parser("gea", help="Run GEA Validator")

    # --- 'ddbj' サブコマンドの省略を許可する ---
    # 第1引数が既知のサブコマンドでなければ、暗黙的に 'ddbj' を補完する。
    # これにより内部キュレータは
    #   ddbj-validator <dir>   （= ddbj-validator ddbj <dir>）
    #   ddbj-validator         （= カレントディレクトリを検証）
    # のように 'ddbj' を省略して実行できる。
    raw = sys.argv[1:]
    if not raw or raw[0] not in KNOWN_COMMANDS:
        raw = ["ddbj"] + raw

    # 補完済みの引数列を明示的に渡してパースする
    args, unknown = parser.parse_known_args(raw)

    if args.command == "ddbj":
        # ddbj 側の argparse へ引数をきれいに引き継ぐため sys.argv を再構成
        sys.argv = [f"{sys.argv[0]} ddbj"] + unknown
        from apps.ddbj.cli import main as ddbj_main
        ddbj_main()
    elif args.command == "biosample":
        sys.argv = [f"{sys.argv[0]} biosample"] + unknown
        from apps.biosample.cli import main as biosample_main
        biosample_main()
    elif args.command == "bioproject":
        sys.argv = [f"{sys.argv[0]} bioproject"] + unknown
        from apps.bioproject.cli import main as bioproject_main
        bioproject_main()
    elif args.command == "dra":
        sys.argv = [f"{sys.argv[0]} dra"] + unknown
        from apps.dra.cli import main as dra_main
        dra_main()
    elif args.command in ("metabobank", "mb"):
        sys.argv = [f"{sys.argv[0]} {args.command}"] + unknown
        from apps.metabobank.cli import main as mb_main
        mb_main()
    elif args.command == "gea":
        sys.argv = [f"{sys.argv[0]} gea"] + unknown
        from apps.gea.cli import main as gea_main
        gea_main()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
    