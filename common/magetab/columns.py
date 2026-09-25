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


def cross_column_duplicates(sdrf, colname):
    """**同じ行の中で** `colname` の複数の列が同じ値を指していれば、その値を並べて返す。

    `Raw Data File` / `Processed Data File` / `Metabolite Assignment File` は 1 行に複数列
    書ける（paired-end の 2 本、positive / negative の 2 本など）。同じ行の 2 つの列が同じ
    ファイルを指していれば、どちらかの書き間違いで本来あるはずのファイルが 1 本欠けている。

    **行をまたいだ重複は対象にしない。** 登録済みの MetaboBank study では、行ごとに使う列の
    本数が違う（1 本目の列だけ使う行と 2 本目まで使う行が混在する）ため、別の行の別の列に
    同じ MAF 名が出るのは正しい書き方として存在する（MTBKS218 / MTBKS221）。
    GEA / MetaboBank で同じ判定をするのでここに置く。
    """
    idxs = sdrf.col_indices(colname)
    if len(idxs) < 2:
        return []
    dup = []
    for row in sdrf.rows:
        seen = set()
        for i in idxs:
            v = (row[i] if i < len(row) else "").strip()
            if not v:
                continue
            if v in seen:
                if v not in dup:
                    dup.append(v)
            else:
                seen.add(v)
    return sorted(dup)


def format_duplicate_files(colname, dup, limit=5):
    """`cross_column_duplicates` の結果をメッセージ用の 1 行に整形する。

    実データでは 1 列まるごと取り違えると数百件並ぶので、先頭 `limit` 件＋総数に丸める。
    """
    shown = ", ".join(dup[:limit])
    more = f", ... ({len(dup)} files)" if len(dup) > limit else ""
    return f"{colname}: {shown}{more}"
