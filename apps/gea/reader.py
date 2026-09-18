"""IDF / SDRF（MAGE-TAB TSV）のパーサ。共通実体は common/magetab に委譲。

戻り値は (GeaSubmission, pre_errors)。整形不正（読込失敗）は pre_errors に積む。
"""
from common.magetab import reader as base
from apps.gea.model import Idf, GeaSubmission


#: 旧い IDF フィールド名 → 今の名前（2026-09-18 に MetaboBank と揃えた）。登録済みの IDF は旧名のままなので読むときに直す
RENAMED_IDF_FIELDS = {
    "Comment[GEAAccession]": "Comment[GEA Accession]",
    "Comment[AEExperimentType]": "Comment[Experiment Type]",
    "Comment[Related study]": "Comment[Related Study]",
    "Comment[Public Release Date]": "Public Release Date",
}


def _known_idf_fields():
    try:
        from apps.gea.defs import load_definitions
        idf = load_definitions().get("idf", {})
        # legacy_fields = 旧い submission にだけあるフィールド（新規では書かないが読めるようにする）
        return set(idf.get("fields", [])) | set(idf.get("legacy_fields", []))
    except Exception:
        return set()


def parse(idf_path=None, sdrf_path=None, account=None):
    sub, pre = base.parse(
        idf_path, sdrf_path,
        submission_cls=GeaSubmission, idf_cls=Idf,
        known_fields=_known_idf_fields() | set(RENAMED_IDF_FIELDS),
        idf_err_id="GEA_ERR0001", sdrf_err_id="GEA_ERR0001",
        account=account,
    )
    base.rename_idf_fields(sub.idf, RENAMED_IDF_FIELDS)
    _rename_protocol_types(sub.idf)
    _rename_experiment_types(sub.idf)
    return sub, pre


#: 旧い experiment type の語 → 今の語（2026-09-18。移行で置換されるまでの後方互換）。
#: `Third-party reanalysis` は experiment type から外し Comment[Study Type] へ移すので、ここには入れない。
RENAMED_EXPERIMENT_TYPES = {
    "spatial transcriptomics by high-throughput sequencing": "spatial transcriptomics",
    "imaging based spatial transcriptomics": "spatial transcriptomics",
    # 「by high throughput sequencing」→「by sequencing」に短縮（2026-09-18）
    "genotyping by high throughput sequencing": "genotyping by sequencing",
    "methylation profiling by high throughput sequencing": "methylation profiling by sequencing",
    "microRNA profiling by high throughput sequencing": "microRNA profiling by sequencing",
}


def _rename_experiment_types(idf):
    """IDF の `Comment[Experiment Type]` の値を旧い語から今の語へ読み替える（in-place）。"""
    if idf is None:
        return idf
    vals = idf.fields.get("Comment[Experiment Type]")
    if vals:
        idf.fields["Comment[Experiment Type]"] = [RENAMED_EXPERIMENT_TYPES.get(v.strip(), v) for v in vals]
    return idf


def _rename_protocol_types(idf):
    """IDF の `Protocol Type` の値を旧名から今の名前へ読み替える（in-place。2026-09-18）。

    protocol type を GEA 新仕様の名前に揃えた（例: `nucleic acid extraction protocol` →
    `Extraction protocol`）。`high throughput sequence alignment protocol` と
    `normalization data transformation protocol` は `Data processing protocol` に統合される。
    **既に登録されている IDF は旧名のまま**なので、読んだ直後に値だけ差し替える。
    こうするとルール側は新名だけを見ればよく、SDRF の node グラフ（Protocol REF → Protocol Type）も
    同じ読み替え結果を使う。
    """
    if idf is None:
        return idf
    try:
        from apps.gea.defs import load_definitions
        mapping = load_definitions().get("protocols", {}).get("rename_map", {})
    except Exception:
        return idf
    vals = idf.fields.get("Protocol Type")
    if mapping and vals:
        idf.fields["Protocol Type"] = [mapping.get(v.strip(), v) for v in vals]
    return idf


def wrong_db_reason(sub):
    """IDF が GEA 以外（MetaboBank）の MAGE-TAB に見えれば理由文字列を返す（abort 用）。"""
    return base.check_flavor(sub.idf, "gea")
