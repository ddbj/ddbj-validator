"""GEA validator の内部表現（MAGE-TAB: IDF＋SDRF）。

汎用の Idf/Sdrf/Submission は common/magetab に集約。ここでは GEA 固有アクセサのみ追加する。
GEA は ArrayExpress 系のカラム名を用いる（Investigation Title / Comment[AEExperimentType] /
Technology Type / Array Design REF 等）。
"""
from common.magetab.model import Idf as BaseIdf, Sdrf, Submission


class Idf(BaseIdf):
    @property
    def bioproject(self):
        return (self.first("Comment[BioProject]") or "").strip()

    @property
    def ae_experiment_type(self):
        return (self.first("Comment[AEExperimentType]") or "").strip()

    @property
    def number_of_channel(self):
        return (self.first("Comment[Number of channel]") or "").strip()

    def protocols(self):
        """Protocol* の列並列を protocol 単位の dict にまとめて返す（GEA は Name/Type/Description）。"""
        return self.parallel("Protocol Name", ["Protocol Type", "Protocol Description"])


class GeaSubmission(Submission):
    def submission_type(self, definitions):
        """microarray / sequencing / other を判定。
        主: SDRF の Technology Type（array assay→microarray / sequencing assay→sequencing）。
        補: IDF の Comment[AEExperimentType]（experiment_types の technology）。"""
        defs = definitions or {}
        tmap = defs.get("technology_type_map", {})
        # 主: Technology Type
        if self.sdrf:
            for v in self.sdrf.values("Technology Type"):
                t = tmap.get((v or "").strip())
                if t:
                    return t
        # 補: AEExperimentType
        if self.idf:
            et = self.idf.ae_experiment_type
            info = defs.get("experiment_types", {}).get(et)
            if info and info.get("technology"):
                return info["technology"]
        return "other"
