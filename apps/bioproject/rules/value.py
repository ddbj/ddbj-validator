"""BioProject 値ルール（文字種・データ形式）。biosample の R0058/R0013 と同型ロジック。

- BP_R0060: 非 ASCII 文字（= BS_R0058）。error。検査対象は **XML の全要素テキスト・属性値**
  （2026-09-28 に自由文 4 フィールドから拡大）。**文字参照（`&#x201c;` 等）は対象外**
  （ソースは ASCII だけで書かれており下流も扱えるため。submission.source_non_ascii を参照）。
- BP_R0059: 不正データ形式（前後/連続空白・囲みクオート。= BS_R0013）。warning。
  こちらは自由文フィールド（title / description / organism_name / publication reference）のみ。
"""
from apps.bioproject.rules.base import BpRule
# 空白正規化・非 ASCII 判定は common に集約した共有ロジック（旧: apps.biosample.rules.value_ascii）
from common.text import normalize_data_format
# XML 全要素の走査（非 ASCII 検査用）
from common.xmltext import non_ascii_values


def _text_fields(rec):
    """自由文フィールド {ラベル: 値} を返す（None は除外）。"""
    fields = {"Title": rec.title, "Description": rec.description, "organism": rec.organism_name}
    for i, pub in enumerate(rec.publications):
        if pub.reference:
            fields[f"Publication[{i}].Reference"] = pub.reference
    return {k: v for k, v in fields.items() if v}


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
    rule_id = "BP_R0059"
    level = "warning"
    target = "#fields"
    description = "Invalid data format."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for name, v in _text_fields(rec).items():
                fixed = normalize_data_format(v)
                if fixed and fixed != v:
                    out.append(self.result(sample=rec.label, target=name,
                                           message=f"Invalid data format. ({name}: '{v}', Suggested: '{fixed}')"))
        return out
