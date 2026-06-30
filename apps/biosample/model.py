"""BioSample validator の内部レコード表現。

入力（XML、または TSV→XML 変換後の XML）をパースしてこの構造へ。
ルールはこの構造だけを見る（XML/TSV の差異を意識しない）。
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
    raw: Any = None                          # 元 XML 要素（必要時の参照用）

    def attr(self, name):
        """属性の代表値（先頭値）を返す。無ければ None。"""
        vals = self.attributes.get(name)
        return vals[0] if vals else None

    def attr_values(self, name):
        """属性の全値（リスト）。無ければ空リスト。"""
        return self.attributes.get(name, [])


@dataclass
class BioSampleSubmission:
    """1 サブミッション（XML の <BioSampleSet>）。複数 BioSample を保持。"""
    records: list = field(default_factory=list)
    submission_id: Optional[str] = None      # SSUB（ファイル名などから）
    package: Optional[str] = None            # サブミッション代表パッケージ（通常全サンプル共通）
    account: Optional[str] = None            # --account（submitter id）
