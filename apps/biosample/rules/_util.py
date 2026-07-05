"""biosample ルール共通の小ヘルパ（空・missing 判定・正規化）。

複数ルールで重複していた定義をここへ集約（Tier 1 リファクタ）。挙動は従来どおり。
"""
import re
# INSDC の missing/null 判定は common に一本化（CV は common/resources/definitions.json 単一ソース）。
# 既存 import 互換のため再エクスポートする。
from common.insdc_missing import (
    is_missing_value,
    is_missing_without_term,
    MISSING_RE,
    MISSING_WITH_TERM_RE,
)


def is_empty(v):
    """None または空白のみなら True。"""
    return v is None or str(v).strip() == ""


def norm(v):
    """空白正規化＋小文字化（値の同一性比較用）。"""
    return re.sub(r"\s+", " ", str(v).strip().lower()) if v else ""


# ゲノム系パッケージのプレフィクス（前方一致で判定）。原核=MIGS.ba / 真核=MIGS.eu。
# R0104/R0109 等で共用（annotated genome / informal name 判定）。
MIGS_BA_EU = ("MIGS.ba", "MIGS.eu")


def pkg_startswith(pkg, *prefixes):
    """package 名が prefixes のいずれかで前方一致するか（None 安全）。
    `not rec.package or not rec.package.startswith(...)` の定型を1関数に集約。"""
    return bool(pkg) and pkg.startswith(prefixes)
