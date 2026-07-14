"""DRA validator の内部レコード表現。

1 セッションに渡された submission / experiment / run / analysis の各 XML をパースし、
1 つの `DraSubmission` に束ねる（= 1 submission 単位で検証）。ルールはこの構造だけを見る。

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


@dataclass
class DraRun(DraObject):
    experiment_ref: Optional[str] = None       # EXPERIMENT_REF@accession（DRX）
    experiment_refname: Optional[str] = None   # EXPERIMENT_REF@refname（alias）
    files: list = field(default_factory=list)  # [DraFile]


@dataclass
class DraAnalysis(DraObject):
    description: Optional[str] = None
    study_ref: Optional[str] = None            # STUDY_REF@accession（BioProject・必須）
    sample_refs: list = field(default_factory=list)  # TARGET[@sra_object_type='SAMPLE']@accession（1+ 必須）
    run_refs: list = field(default_factory=list)     # TARGET[@sra_object_type='RUN']@accession（0+ 任意）
    files: list = field(default_factory=list)  # [DraFile]


@dataclass
class DraSubmissionMeta(DraObject):
    """SUBMISSION 要素（submission そのもの）。"""
    lab_name: Optional[str] = None
    submission_date: Optional[str] = None
    hold_date: Optional[str] = None            # ACTIONS/HOLD@HoldUntilDate
    contacts: list = field(default_factory=list)


@dataclass
class DraSubmission:
    """1 セッション = 1 submission。submission は 1 つ、experiment/run は 1+、analysis は 0+。"""
    submission: Optional[DraSubmissionMeta] = None
    experiments: list = field(default_factory=list)
    runs: list = field(default_factory=list)
    analyses: list = field(default_factory=list)
    account: Optional[str] = None
    role_files: dict = field(default_factory=dict)  # role('submission'/'experiment'/'run'/'analysis') -> [filename]
    submission_id: Optional[str] = None             # submission alias 由来（例 amr_ddbj-0104_Submission → amr_ddbj-0104）
