"""テキスト値の共通ユーティリティ（非 ASCII 判定・空白正規化・特殊文字置換・HTML 検出）。

biosample / bioproject の値ルールが共有する純関数。app 間の相互 import（レイヤ違反）を避けるため
common に置く。状態を持たない純関数のみ。
"""
import re

_WS_RE = re.compile(r"\s+")
# HTML マークアップ（タグ）検出。`<tag ...>` / `</tag>` / `<br/>` を拾う。
# 開始 `<` の直後（空白許容）に英字が来る場合のみタグとみなし、"a < 5" のような不等号は誤検知しない。
_HTML_RE = re.compile(r"<\s*/?\s*[A-Za-z][^<>]*>")


def normalize_data_format(v):
    """連続空白の畳み込み（前後 strip＋タブ/改行/連続空白→半角空白1つ）＋前後を囲む対クオートの除去。
    Ruby v invalid_data_format(String#squish 相当) に準拠。補正不要なら元の値と同じ文字列を返す。"""
    s = _WS_RE.sub(" ", v.strip())
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = _WS_RE.sub(" ", s[1:-1].strip())
    return s


def apply_special_chars(value, special_chars):
    """special_chars に従い特殊文字を置換した文字列を返す。
    長いキーを先に処理し "μm"→"micro"+"m" のような部分置換を防ぐ。"""
    out = value
    for target in sorted(special_chars, key=len, reverse=True):
        out = out.replace(target, special_chars[target])
    return out


def _non_ascii(v):
    try:
        v.encode("ascii")
        return False
    except (UnicodeEncodeError, AttributeError):
        return True


def _has_html(v):
    return bool(v) and bool(_HTML_RE.search(v))
