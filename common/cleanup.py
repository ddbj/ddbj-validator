"""全 app 共通の auto cleanup（対話なしで強制的に値をきれいにする前処理）。

ddbj の preprocessor（ANN0180 / ANN0170）にならい、各 app は **読み込み直後・外部参照の取得前**に
値をこの関数で置き換え、以降のルール・Taxonomy などの外部参照・fixed 出力はきれいになった値を使う。
置き換えた内容は各 app の既存ルール ID で warning として報告する（黙って直さない）。

処理の順:
1. 空白に似た文字（NBSP、全角空白など）を半角空白へ、ゼロ幅空白と BOM は削除。
   表は `common/resources/definitions.json` の `char_normalization.space_like`
   （GEA / MetaboBank の charnorm と同じ表）。
2. 前後の空白を除く。
3. 空白の連続（タブ・改行を含む）を半角空白 1 つにする。`keep_newlines=True` なら改行は残す
   （IDF の Protocol Description のように改行に意味がある欄用）。
4. `unquote=True` なら前後を囲む対クオート（"..." / '...'）を外す。

2026-10-03: NBSP を含む organism / host が 1 つあるだけで Taxonomy DB（EUC_JP）への問い合わせが
丸ごと失敗し、SSUB051896 の 817 sample で BS_R0045 の taxonomy_id 提案が消えた件を受けて全 app に入れた。
℃→degree C のような意味の絡む置換は、app ごとの表（BS の special_characters、MAGE-TAB の
charnorm）に任せ、ここでは空白系だけを扱う。
"""
import functools
import re

from common.definitions import load_common_definitions

_WS_RE = re.compile(r"\s+")
_INLINE_WS_RE = re.compile(r"[^\S\n]+")        # 改行以外の空白の連続
_SPACES_AROUND_NL_RE = re.compile(r" *\n *")   # 改行の前後に残った空白


@functools.lru_cache(maxsize=1)
def space_like_table():
    """{空白に似た文字: 半角空白} の表。"""
    cn = (load_common_definitions() or {}).get("char_normalization", {})
    return dict(cn.get("space_like", {}))


def normalize_space_like(v):
    """空白に似た文字だけを半角空白にする（strip・畳み込みはしない）。"""
    if not v:
        return v
    table = space_like_table()
    if not any(ch in table for ch in v):
        return v
    return "".join(table.get(ch, ch) for ch in v)


def clean_value(v, *, keep_newlines=False, unquote=True):
    """値をきれいにした文字列を返す。直す必要がなければ元と同じ文字列。None・空はそのまま返す。"""
    if not v:
        return v
    s = normalize_space_like(v)
    s = _collapse(s.strip(), keep_newlines)
    if unquote and len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = _collapse(s[1:-1].strip(), keep_newlines)
    return s


def _collapse(s, keep_newlines):
    if not keep_newlines:
        return _WS_RE.sub(" ", s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _INLINE_WS_RE.sub(" ", s)
    return _SPACES_AROUND_NL_RE.sub("\n", s)
