"""BioProject 値ルール（文字種・データ形式）。biosample の R0058/R0013 と同型ロジック。

- BP_R0060: 非 ASCII 文字（= BS_R0058）。error。検査対象は **XML の全要素テキスト・属性値**
  （2026-09-28 に自由文 4 フィールドから拡大）。**文字参照（`&#x201c;` 等）は対象外**
  （ソースは ASCII だけで書かれており下流も扱えるため。submission.source_non_ascii を参照）。
- BP_R0059: 不正データ形式（前後/連続空白・囲みクオート・NBSP などの空白系文字。= BS_R0013）。warning。
  **強制 cleanup**（2026-10-03。それまでは自由文 4 フィールドの報告のみ）。xml_reader がパース直後に
  XML の全要素テキスト・属性値を置き換えてからモデルを組むので、長さ（R0005/R0006）・Taxonomy・
  重複（R0004）・非 ASCII（R0060）はきれいにした値で判定する。validator のルール列には登録しない。
"""
from apps.bioproject.rules.base import BpRule
# 空白正規化・非 ASCII 判定は common に集約した共有ロジック（旧: apps.biosample.rules.value_ascii）
from common.cleanup import clean_value
# XML 全要素の走査（非 ASCII 検査用）
from common.xmltext import non_ascii_values


class BP_R0060(BpRule):
    """XML のどこかに非 ASCII 文字が素で入っていれば error。

    2026-09-28 まで Title / Description / organism / Publication の Reference の 4 つしか
    見ておらず、Contact の氏名や Organization 名、Grant の名称のようにモデルへ取り込んでいない
    要素は素通りしていた。**全要素のテキストと属性値**を走査し、どの要素かをパスで示す。

    XML パーサは `&#x201c;` のような文字参照を実体へ展開するので、値だけを見ると
    ASCII だけで書かれたファイルまで非 ASCII と判定してしまう。**ソースに素の文字として
    現れた非 ASCII だけ**を対象にするため、`submission.source_non_ascii` で絞り込む。
    """
    rule_id = "BP_R0060"
    level = "error"
    target = "#fields"
    description = "Non-ASCII format characters detected."

    def validate(self, submission, context):
        root = getattr(submission, "raw_root", None)
        if root is None:
            return []   # パース結果が無い（parse_xml 経由なら必ず入る）
        # ソースに素で入っている非 ASCII 文字。文字参照で書かれたものはここに入らない。
        literal = getattr(submission, "source_non_ascii", None)
        sample = submission.records[0].label if submission.records else None
        out, seen = [], set()
        for _el, path, value in non_ascii_values(root, literal):
            if value in seen:
                continue    # 同じ値が複数箇所に写っている（accession 等）ときは 1 回だけ出す
            seen.add(value)
            out.append(self.result(sample=sample, target=path,
                                   message=f"Non-ASCII characters detected in '{path}'. (Found: '{value}')"))
        return out


class BP_R0059(BpRule):
    """XML の全要素テキスト・属性値を強制的にきれいにする（auto cleanup）。

    `cleanup(root)` を xml_reader がパース直後に呼ぶ。値を in-place で置き換え、置き換えた値ごとに
    warning を 1 件返す。属性値（accession・taxID など）は囲みクオートを外さない。
    """
    rule_id = "BP_R0059"
    level = "warning"
    target = "#fields"
    description = "Invalid data format."

    def cleanup(self, root):
        out = []
        for el, path, attr in _iter_slots(root, root.tag):
            old = el.get(attr) if attr else el.text
            new = clean_value(old, unquote=not attr)
            if not new or new == old:
                continue
            if attr:
                el.set(attr, new)
            else:
                el.text = new
            # 前後の ASCII 空白だけの違い（XML の整形インデント）は報告しない。値としては同じ。
            shown = old.strip(" \t\r\n")
            if new == shown:
                continue
            out.append(self.result(target=path, autofix=True, old_value=shown, new_value=new,
                                   message=f"Invalid data format. ({path}: '{shown}', Suggested: '{new}')"))
        return out


def _iter_slots(el, path):
    """(要素, パス, 属性名 or None) を列挙する。属性名 None は要素テキスト。
    パスは common/xmltext と同じ書き方（同名の兄弟が複数あるときだけ [n] を付ける）。"""
    for k in sorted(el.attrib):
        if el.attrib[k] and el.attrib[k].strip():
            yield el, f"{path}@{k}", k
    if len(el) == 0 and el.text and el.text.strip():
        yield el, path, None
    total = {}
    for child in el:
        total[child.tag] = total.get(child.tag, 0) + 1
    seen = {}
    for child in el:
        seen[child.tag] = seen.get(child.tag, 0) + 1
        idx = f"[{seen[child.tag]}]" if total[child.tag] > 1 else ""
        yield from _iter_slots(child, f"{path}/{child.tag}{idx}")
