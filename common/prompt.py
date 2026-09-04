"""対話プロンプト用の共通ヘルパー。

CLI の確認プロンプトは、非 TTY（パイプ／リダイレクト／CI・`docker run` の -it 無し）では
そもそも答えを受け取れない。判定を各所で書くと実装漏れが起きるため（issue #9）、
TTY 判定と EOF 耐性のある入力をここに集約する。
"""
import sys


def is_interactive():
    """確認プロンプトを出せる状況か（stdin が TTY か）を判定する。"""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, AttributeError):
        # stdin が閉じている／差し替えられている場合は非対話とみなす
        return False


def ask(prompt, eof_default):
    """対話プロンプト。EOF (Ctrl-D / stdin 終端) では eof_default を返して落ちないようにする。"""
    try:
        return input(prompt).strip().lower()
    except EOFError:
        print()
        return eof_default
