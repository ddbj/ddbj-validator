"""MAGE-TAB（IDF＋SDRF）の汎用内部表現。MetaboBank / GEA で共有。

- IDF: key-value TSV。1 列目=項目名、2 列目以降=値の配列。Person*/Protocol* は列並列。
- SDRF: 表形式 TSV。ヘッダに列種別（*Name / Characteristics[x] / Comment[x] / Protocol REF（順序付き複数）/
  Parameter Value[x] / Data File / Factor Value[x]）。行＝サンプル→assay→データの関係。

app 固有のアクセサ（submission_type, bioproject, protocols の列名など）は各 app の model で
本クラスを継承して追加する。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Idf:
    fields: dict = field(default_factory=dict)            # name -> [values]
    field_order: list = field(default_factory=list)       # 出現順の項目名
    blank_before: set = field(default_factory=set)        # 直前に空行があった項目名（整形保持用）
    duplicate_fields: list = field(default_factory=list)  # 重複して出現した項目名
    raw_path: Optional[str] = None

    def get(self, name):
        return self.fields.get(name, [])

    def first(self, name):
        v = self.fields.get(name, [])
        return v[0] if v else ""

    def parallel(self, index_key, value_keys):
        """列並列フィールド（Protocol* / Person* 等）を index_key の各値に対する dict のリストに整形。"""
        names = self.get(index_key)
        out = []
        for i, nm in enumerate(names):
            d = {index_key: nm}
            for k in value_keys:
                vals = self.get(k)
                d[k] = vals[i] if i < len(vals) else ""
            out.append(d)
        return out


@dataclass
class Sdrf:
    header: list = field(default_factory=list)    # 列名（重複含む・順序）
    rows: list = field(default_factory=list)       # [[cell,...]]
    raw_path: Optional[str] = None

    def col_indices(self, name):
        """列名（完全一致）のインデックス一覧。"""
        return [i for i, h in enumerate(self.header) if h == name]

    def values(self, name):
        """列名の全行の値（複数列なら連結）。"""
        idxs = self.col_indices(name)
        out = []
        for row in self.rows:
            for i in idxs:
                out.append(row[i] if i < len(row) else "")
        return out


@dataclass
class Submission:
    idf: Optional[Idf] = None
    sdrf: Optional[Sdrf] = None
    account: Optional[str] = None
