"""MAGE-TAB（gea / metabobank）の SDRF 列名をパターン表と照合する共通ヘルパー。

definitions.json の `sdrf.fields` / `required_columns_warning` は正規表現表記
（`Characteristics\\[.*\\]`）と literal 列名が混在する。列名は **全体一致**（re.fullmatch）で判定し、
正規表現として壊れているパターンは literal として等値比較する。

もとは gea / metabobank の rules/sdrf.py に別々にあった。metabobank 版だけ `re.search` でも真に
していたが、初期実装（21e0ca5）からの写し間違いで意図ではなく、公開 162 study の全 SDRF 列で
判定が変わる列は 0 だったので（2026-09-15 実測）fullmatch に揃えた。
"""
import re


def matches_any(colname, patterns):
    """colname がパターン列のいずれかに全体一致するか。"""
    for p in patterns:
        try:
            if re.fullmatch(p, colname):
                return True
        except re.error:
            if p == colname:
                return True
    return False


def matches_any_header(header, pattern):
    """ヘッダー列のいずれかが pattern に全体一致するか。"""
    return any(matches_any(h, [pattern]) for h in header)
