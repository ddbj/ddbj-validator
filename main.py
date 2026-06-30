#!/usr/bin/env python3

import sys
import argparse

# 既知のトップレベルサブコマンド（将来サブコマンドが増えたらここに追加）
KNOWN_COMMANDS = {"ddbj", "biosample"}

def main():
    parser = argparse.ArgumentParser(
        description="DDBJ Validation Tools",
        usage="ddbj-validator [ddbj|biosample] [<args>]",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("ddbj", help="Run DDBJ Validator")
    subparsers.add_parser("biosample", help="Run BioSample Validator")

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
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
    