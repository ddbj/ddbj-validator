"""XML のテキスト・属性値をまとめて走査するユーティリティ（非 ASCII チェック用）。

BioProject / BioSample / DRA の「非 ASCII 文字が入っていないか」を見るルールは、
もともと **モデルに取り込んだ数フィールドだけ**を対象にしていた。そのため Contact の氏名や
Organization 名、Grant の名称など、モデルに載せていない要素は素通りしていた。
ここでは XML の **すべての要素テキストと属性値**を (要素, パス, 値) で列挙して、
各 app のルールが漏れなく検査できるようにする。

文字参照（`&#x201c;` など）の扱い:
XML パーサは文字参照を実体へ展開するので、展開後の値だけを見ると「ソースは ASCII だけで
書かれているファイル」まで非 ASCII と判定してしまう。`literal_non_ascii()` でソースの
バイト列に **素の文字として**現れた非 ASCII を集め、それで絞り込む。
"""
import re
from pathlib import Path

from common.text import _non_ascii

_ENCODING_RE = re.compile(rb"""<\?xml[^>]*?encoding\s*=\s*["']([\w.-]+)["']""", re.I)


def literal_non_ascii(xml_path):
    """XML ソースに素の文字として現れる非 ASCII 文字の集合を返す。

    `&#x201c;` のような文字参照はソース上では ASCII だけで書かれているので、ここには含まれない。
    バイト列がすべて ASCII ならその時点で空集合（ファイルの大半はこのケース）。
    """
    try:
        raw = Path(xml_path).read_bytes()
    except OSError:
        return set()
    if not any(b > 0x7F for b in raw):
        return set()
    m = _ENCODING_RE.search(raw[:200])
    enc = m.group(1).decode("ascii", "replace") if m else "utf-8"
    try:
        text = raw.decode(enc, errors="replace")
    except LookupError:
        text = raw.decode("utf-8", errors="replace")
    return {ch for ch in text if ord(ch) > 0x7F}


def _walk(el, base):
    """要素 el 以下を (要素, パス, 値) で列挙する内部関数。"""
    for k, v in sorted(el.attrib.items()):
        if v and v.strip():
            yield el, f"{base}@{k}", v.strip()
    if el.text and el.text.strip():
        yield el, base, el.text.strip()
    # 同名の兄弟が複数あるときだけ添字を付ける（Publication[2] のように場所を特定できるようにする）
    total = {}
    for child in el:
        total[child.tag] = total.get(child.tag, 0) + 1
    seen = {}
    for child in el:
        seen[child.tag] = seen.get(child.tag, 0) + 1
        idx = f"[{seen[child.tag]}]" if total[child.tag] > 1 else ""
        yield from _walk(child, f"{base}/{child.tag}{idx}")
        # 混在内容（要素の後ろに続く地の文）も親の内容なので拾う
        if child.tail and child.tail.strip():
            yield el, base, child.tail.strip()


def iter_values(root, prefix=None):
    """root 以下のすべての要素テキスト・属性値を (要素, パス, 値) で列挙する。

    パスは `BioSample/Owner/Contacts/Contact/Name/Last` のように要素名を `/` で連結したもの。
    属性は `要素@属性名`。prefix を与えると先頭をその名前に差し替える（既定は root のタグ名）。
    """
    return _walk(root, prefix if prefix is not None else root.tag)


def non_ascii_values(root, literal=None, prefix=None):
    """非 ASCII を含む (要素, パス, 値) だけを列挙する。

    literal に `literal_non_ascii()` の集合を渡すと、**ソースに素で書かれていた文字**を
    含む値だけに絞る（すべて文字参照で書かれた値は対象外）。None なら絞り込まない。
    """
    for el, path, value in iter_values(root, prefix):
        if not _non_ascii(value):
            continue
        if literal is not None and not any(ord(ch) > 0x7F and ch in literal for ch in value):
            continue   # すべて文字参照由来（ソースは ASCII のみ）
        yield el, path, value
