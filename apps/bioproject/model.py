"""BioProject validator の内部レコード表現。

入力をパースしてこの構造へ。対応する入力は BioProject XML
（PackageSet > Package > Project > Project ＋ Submission）と DDBJ Record（v3 JSON）。
ルールはこの構造だけを見る（入力形式の差異を意識しない）。新しい入力形式に対応するとは、
ここへ組み直す reader を 1 本足すこと以上の意味を持たない。
通常 1 入力 = 1 project（XML で複数は BP_R0037）。
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Publication:
    """ProjectDescr/Publication。id（PubMed 数値 / PMC / DOI）と DbType、free-text Reference。"""
    id: Optional[str] = None
    db_type: Optional[str] = None       # ePubmed / eDOI / ePMC 等
    reference: Optional[str] = None


@dataclass
class BioProjectRecord:
    """1 BioProject（XML の内側 Project 要素）に対応。"""
    accession: Optional[str] = None          # ProjectID/ArchiveID@accession（PRJDBxxxx）
    archive: Optional[str] = None            # @archive（DDBJ 等）
    title: Optional[str] = None              # ProjectDescr/Title
    description: Optional[str] = None        # ProjectDescr/Description
    release_date: Optional[str] = None       # ProjectDescr/ProjectReleaseDate
    publications: list = field(default_factory=list)   # [Publication]
    project_kind: Optional[str] = None       # umbrella / submission / single_organism / other
    top_admin_subtype: Optional[str] = None  # ProjectTypeTopAdmin@subtype（umbrella 用）
    sample_scope: Optional[str] = None       # Target@sample_scope（eMonoisolate/eEnvironment/eMultispecies/eOther…）
    material: Optional[str] = None           # Target@material
    capture: Optional[str] = None            # Target@capture
    method_type: Optional[str] = None        # Method@method_type
    method_text: Optional[str] = None        # Method 本文（method_type=eOther のとき説明を入れる）
    data_types: list = field(default_factory=list)     # Objectives/Data@data_type ＋ ProjectDataTypeSet/DataType
    data_entries: list = field(default_factory=list)   # [{"type":..., "text":...}]（Data 要素ごと。eOther 説明判定用）
    target_description: Optional[str] = None # Target/Description（sample_scope/material/capture=eOther 時の説明）
    subtype_other_descr: Optional[str] = None  # ProjectTypeTopAdmin/DescriptionSubtypeOther（subtype=eOther 時の説明）
    relevance_present: bool = False          # Relevance 要素の有無
    # Relevance/Other を「選んだ」か。text が空でも要素があれば選択とみなす、が XML での
    # 判定なので、Other の有無と text は別の情報になる。BP_R0007 が両方を見る。
    relevance_other_selected: bool = False
    relevance_other: Optional[str] = None    # Relevance/Other の text（None=要素なし or 空）
    organism_name: Optional[str] = None      # Organism/OrganismName
    tax_id: Optional[str] = None             # Organism@taxID
    locus_tags: list = field(default_factory=list)     # [{"prefix":..., "biosample_id":...}]
    umbrella_member_ids: list = field(default_factory=list)  # ProjectLinks/Link/Hierarchical[@type='TopAdmin']/MemberID@accession（BP_R0016）
    # 元の入力（XML 入力なら Element、Record 入力なら v3 の project dict）。
    # ルールは参照しない。参照すると入力形式に依存してしまう。
    raw: Any = None

    @property
    def label(self):
        """レポート用の識別子（accession 優先、無ければ title）。"""
        return self.accession or self.title or "BioProject"


@dataclass
class BioProjectSubmission:
    """1 BioProject XML（PackageSet）。通常 1 project。"""
    records: list = field(default_factory=list)
    account: Optional[str] = None            # --account（submitter id）
