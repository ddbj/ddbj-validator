"""MetaboBank の非 ASCII 文字正規化（強制 autofix）。

definitions.json の `char_normalization`（hyphen_like / space_like / symbol / greek）を
1 つの置換表にまとめ、テキストを ASCII 化する。表に無い non-ASCII は「残存」として報告し、
呼び出し側（MB_IR0024 / MB_SR0030）が error にする。

正規化対象外: タブ `\t`・改行（列区切り・レコード構造のため）。
"""
import functools

from apps.metabobank.defs import load_definitions


@functools.lru_cache(maxsize=1)
def _table():
    """全カテゴリを結合したフラットな {文字: ASCII 置換文字列} を返す。"""
    cn = (load_definitions() or {}).get("char_normalization", {})
    flat = {}
    for cat in ("hyphen_like", "space_like", "symbol", "greek",
                "quote", "superscript", "subscript", "fraction"):
        flat.update(cn.get(cat, {}))
    return flat


def normalize(text):
    """text を正規化する。

    戻り値 (new_text, mapped, residual):
      new_text : 正規化後の文字列（残存 non-ASCII はそのまま残す）
      mapped   : ASCII 化した元 non-ASCII 文字の set（autofix 報告用）
      residual : 表に無く ASCII 化できなかった non-ASCII 文字の set（error 用）
    """
    if not text:
        return text, set(), set()
    table = _table()
    out = []
    mapped = set()
    residual = set()
    for ch in text:
        if ord(ch) < 128:
            out.append(ch)
        elif ch in table:
            out.append(table[ch])
            mapped.add(ch)
        else:
            out.append(ch)  # error 報告のため残す
            residual.add(ch)
    return "".join(out), mapped, residual


# --- 報告メッセージ（MB_IR0024 / MB_SR0030 で共通利用） ---
_WARN_MSG = ("Non-ASCII characters were normalized to ASCII "
             "(hyphen-like -> '-', space-like -> ' '; symbols and Greek letters spelled out, "
             "e.g. degree Celsius -> 'degree C', Greek mu -> 'micro', multiplication sign -> 'x').")


def _disp(c):
    """表示用: 印字可能ならそのまま、不可なら U+XXXX。"""
    return c if c.isprintable() else f"U+{ord(c):04X}"


def fix_warning_message(where, mapped):
    """autofix 適用（warning）用メッセージ。where=フィールド名/セル位置。"""
    chars = ", ".join(f"'{_disp(c)}'" for c in sorted(mapped))
    return f"{_WARN_MSG} ({where}: {chars})"


def residual_error_message(where, residual):
    """autofix 後に残った非 ASCII / 制御文字（error）用メッセージ。IDF/SDRF 共通体裁。"""
    chars = ", ".join(f"'{_disp(c)}'" for c in sorted(residual))
    return f"Invalid characters: {chars} ({where})"
