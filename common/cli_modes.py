"""CLI 実行モード解決の共通ロジック（bp/dra/mb/gea で共有）。

3 つの skip_* フラグ（skip_db / skip_ncbi / skip_auth）を CLI 引数・環境変数から解決する。
skip_auth は skip_db に従う（DB がなければ権限検証不可）。
"""
import importlib
import os


def env_internal_db():
    """環境変数 DDBJ_VALIDATOR_INTERNAL_DB が有効か。"""
    return os.environ.get("DDBJ_VALIDATOR_INTERNAL_DB", "").strip().lower() not in ("", "0", "false", "no")


def resolve_modes(args):
    """(skip_db, skip_ncbi, skip_auth) を返す。
    -l → 完全ローカル / -n → NCBI API / -d or env → 内部 DB / 既定 → NCBI（DB スキップ）。"""
    if args.local:
        skip_db, skip_ncbi = True, True
    elif args.ncbi_api:
        skip_db, skip_ncbi = True, False
    elif getattr(args, "internal_db", False) or env_internal_db():
        skip_db, skip_ncbi = False, False
    else:
        skip_db, skip_ncbi = True, False
    return skip_db, skip_ncbi, skip_db


def tool_version(package):
    """package（例 "apps.gea"）の __version__ を返す。取得不可なら "unknown"。

    各サブコマンドの版は apps/<app>/__init__.py の __version__ で個別管理（release.sh --all が bump する運用）。
    """
    try:
        return getattr(importlib.import_module(package), "__version__", "unknown")
    except Exception:
        return "unknown"


# --- 内部 DB アクセスの表示（ddbj と同体裁。access した DB だけ表示）---
_db_header_shown = {"v": False}


def reset_db_access_log():
    """1 回の実行の先頭で呼ぶ（"Checking Internal DB..." ヘッダを 1 度だけ出すため）。"""
    _db_header_shown["v"] = False


def db_checking(label, n, singular, plural=None):
    """`[Label] Checking N noun...` を表示（n==0 は非表示）。初回に "Checking Internal DB..." を出す。"""
    if not n:
        return
    if not _db_header_shown["v"]:
        print("\nChecking Internal DB...")
        _db_header_shown["v"] = True
    plural = plural or f"{singular}s"
    print(f"[{label}] Checking {n} {singular if n == 1 else plural}...")


def print_found(n, unit="file set"):
    """ddbj 風の先頭行 'Found N file set(s) in 1 directory.'（標準出力）。"""
    noun = unit if n == 1 else unit + "s"
    print(f"Found {n} {noun} in 1 directory.")


def stdout_summary(summary):
    """summary を標準出力用に整形（'=== ... ===' タイトル行を除き、前後に空行）。ファイル出力は元のまま。"""
    body = "\n".join(l for l in summary.splitlines() if not l.startswith("=== "))
    return "\n" + body.strip("\n") + "\n"
