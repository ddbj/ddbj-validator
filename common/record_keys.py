"""DDBJ Record（v3 JSON）を読む側で揃えておく判定。"""


def carries(record, key):
    """record が top-level の `key`（projects / samples …）を持つか。

    web api の振り分けと、各 reader の「担当外も載っている」の知らせは同じ答えを出す
    必要があるのでここに置く。空の list は 0 件であって、持たないのと同じ。list でない
    値は形が違うだけで持ってはいるので、持つ側に倒す — 振り分けで捨てると、担当する
    reader が形の違反として報告する機会が無くなる。
    """
    value = record.get(key)
    return value is not None and value != []
