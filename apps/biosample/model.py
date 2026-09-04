"""BioSample validator の内部レコード表現。

入力をパースしてこの構造へ。対応する入力は XML / TSV（→XML 変換後）/ DDBJ Record（v3 JSON）。
ルールはこの構造だけを見る（入力形式の差異を意識しない）。新しい入力形式に対応するとは、
ここへ組み直す reader を 1 本足すこと以上の意味を持たない。
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BioSampleRecord:
    """1 サンプル（XML の 1 <BioSample>）に対応。"""
    accession: Optional[str] = None          # Ids/Id（biosample_accession）
    sample_name: Optional[str] = None        # Description/SampleName（= 属性 sample_name とも対応）
    title: Optional[str] = None              # Description/Title
    organism: Optional[str] = None           # Description/Organism/OrganismName
    taxonomy_id: Optional[str] = None        # Description/Organism@taxonomy_id
    package: Optional[str] = None            # Models/Model（パッケージ名）
    # 属性名 -> 値リスト（同名属性が複数あり得るためリストで保持。R0061 等の検出に使う）
    attributes: dict = field(default_factory=dict)
    access: Optional[str] = None             # BioSample@access
    # 元の入力（XML 入力なら Element、Record 入力なら v3 の sample dict）。
    # ルールは参照しない。参照すると入力形式に依存してしまい、上の契約が崩れる。
    raw: Any = None

    @property
    def sample_id(self):
        """レポート用のサンプル識別子（sample_name 優先、無ければ accession）。"""
        return self.sample_name or self.accession

    def attr(self, name):
        """属性の代表値（先頭値）を返す。無ければ None。"""
        vals = self.attributes.get(name)
        return vals[0] if vals else None

    def attr_values(self, name):
        """属性の全値（リスト）。無ければ空リスト。"""
        return self.attributes.get(name, [])


@dataclass
class BioSampleSubmission:
    """1 サブミッション（XML の <BioSampleSet>、Record の samples[]）。複数 BioSample を保持。"""
    records: list = field(default_factory=list)
    submission_id: Optional[str] = None      # SSUB（ファイル名などから）
    package: Optional[str] = None            # サブミッション代表パッケージ（通常全サンプル共通）
    account: Optional[str] = None            # --account（submitter id）
