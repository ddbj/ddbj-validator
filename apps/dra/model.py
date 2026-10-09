"""DRA validator の内部レコード表現。

入力をパースして 1 つの `DraSubmission` に束ねる（= 1 submission 単位で検証）。対応する入力は
1 セッションに渡された submission / experiment / run / analysis の各 XML と、DDBJ Record（v3 JSON）。
ルールはこの構造だけを見る（入力形式の差異を意識しない）。

構造（SRA metadata model）:
- SUBMISSION（1）: alias/accession/center_name/lab_name/hold_date/contacts。ACTIONS の source 名は使わない。
- EXPERIMENT（1+）: study_ref(BP)・sample_ref(BS)・library・platform。
- RUN（1+）: experiment_ref(DRX)・files[]。
- ANALYSIS（0+・任意）: study_ref(BP・必須)・targets(SAMPLE/RUN)・files[]。
"""
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DraFile:
    """DATA_BLOCK/FILES/FILE。"""
    filename: Optional[str] = None
    filetype: Optional[str] = None
    checksum_method: Optional[str] = None
    checksum: Optional[str] = None


@dataclass
class DraObject:
    """DRA オブジェクト共通（alias/accession/center_name/title）。"""
    alias: Optional[str] = None
    accession: Optional[str] = None
    center_name: Optional[str] = None
    title: Optional[str] = None
    # 元の入力（XML 入力なら Element、Record 入力なら v3 の object の dict）。
    # ルールは参照しない。参照すると入力形式に依存してしまう。
    raw: Any = None

    @property
    def label(self):
        return self.accession or self.alias or self.__class__.__name__


@dataclass
class DraExperiment(DraObject):
    description: Optional[str] = None
    study_ref: Optional[str] = None            # STUDY_REF@accession（BioProject, PRJDB）
    sample_ref: Optional[str] = None           # SAMPLE_DESCRIPTOR@accession（BioSample, SAMD）
    library_name: Optional[str] = None
    library_strategy: Optional[str] = None
    library_source: Optional[str] = None
    library_selection: Optional[str] = None
    library_layout: Optional[str] = None       # "SINGLE" / "PAIRED"
    nominal_length: Optional[str] = None        # PAIRED@NOMINAL_LENGTH（insert size）
    platform: Optional[str] = None             # ILLUMINA / PACBIO_SMRT 等
    instrument_model: Optional[str] = None
    # 必須のまとまりがあるか（DRA_R0002）。中身が空でも「ある」は「無い」と区別する。
    design_present: bool = False               # DESIGN
    library_descriptor_present: bool = False   # DESIGN/LIBRARY_DESCRIPTOR
    platform_present: bool = False             # PLATFORM


@dataclass
class DraRun(DraObject):
    experiment_ref: Optional[str] = None       # EXPERIMENT_REF@accession（DRX）
    experiment_refname: Optional[str] = None   # EXPERIMENT_REF@refname（alias）
    files: list = field(default_factory=list)  # [DraFile]
    data_block_present: bool = False           # DATA_BLOCK があるか（DRA_R0002）


@dataclass
class DraAnalysis(DraObject):
    description: Optional[str] = None
    study_ref: Optional[str] = None            # STUDY_REF@accession（BioProject・必須）
    sample_refs: list = field(default_factory=list)  # TARGET[@sra_object_type='SAMPLE']@accession（1+ 必須）
    run_refs: list = field(default_factory=list)     # TARGET[@sra_object_type='RUN']@accession（0+ 任意）
    files: list = field(default_factory=list)  # [DraFile]
    data_block_present: bool = False           # DATA_BLOCK があるか（DRA_R0002）


@dataclass
class DraSubmissionMeta(DraObject):
    """SUBMISSION 要素（submission そのもの）。"""
    lab_name: Optional[str] = None
    submission_date: Optional[str] = None
    # ACTIONS のうち @target の無い HOLD と RELEASE の最後のものが HOLD なら、その @HoldUntilDate
    # （RELEASE なら None）。DDBJ Record の submission.hold_date と同じ決め方。
    hold_date: Optional[str] = None
    contacts: list = field(default_factory=list)


@dataclass
class DraSubmission:
    """1 入力（XML 群のセッション / DDBJ Record）= 1 submission。
    submission は 1 つ、experiment/run は 1+、analysis は 0+。"""
    submission: Optional[DraSubmissionMeta] = None
    experiments: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    analyses: list = field(default_factory=list)
    account: Optional[str] = None
    # role('submission'/'experiment'/'run'/'analysis') -> [filename]。レポートの見出しに出す。
    # Record 入力では、その役割のものを載せている record ファイルの名前。
    role_files: dict = field(default_factory=dict)
    # パースした XML の生データ。DRA_R0050（非 ASCII）が全要素を走査するために持つ。
    # [{"file": ファイル名, "root": ルート要素, "literal": ソースに素で現れた非 ASCII 文字の集合}]
    xml_docs: list = field(default_factory=list)
    submission_id: Optional[str] = None             # submission alias 由来（例 amr_ddbj-0104_Submission → amr_ddbj-0104）
