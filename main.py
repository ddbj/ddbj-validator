#!/usr/bin/env python3
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(
        description="BSI Validation Tools",
        usage="bsi-validator <command> [<args>]"
    )
    subparsers = parser.add_subparsers(dest="command")
    
    # サブコマンドの登録（将来BioProjectなどをここに追加します）
    subparsers.add_parser("ddbj", help="Run DDBJ Validator")
    
    # parse_known_args を使うことで、ddbj 特有の引数(-d, -wなど)を unknown として分離
    args, unknown = parser.parse_known_args()
    
    if args.command == "ddbj":
        # sys.argvを書き換えて、ddbj側のargparseに綺麗に引数を引き継ぐ
        sys.argv = [f"{sys.argv[0]} ddbj"] + unknown
        from apps.ddbj.cli import main as ddbj_main
        ddbj_main()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()