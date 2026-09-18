"""GEA validator の内部表現（MAGE-TAB: IDF＋SDRF）。

汎用の Idf/Sdrf/Submission は common/magetab に集約。ここでは GEA 固有アクセサのみ追加する。
GEA は ArrayExpress 系のカラム名を用いる（Investigation Title / Comment[Experiment Type] /
Technology Type / Array Design REF 等）。
"""
from common.magetab.model import Idf as BaseIdf, Sdrf, Submission


class Idf(BaseIdf):
    @property
    def bioproject(self):
        return (self.first("Comment[BioProject]") or "").strip()

    @property
    def ae_experiment_type(self):
        return (self.first("Comment[Experiment Type]") or "").strip()

    @property
    def number_of_channel(self):
        return (self.first("Comment[Number of channel]") or "").strip()

    def protocols(self):
        """Protocol* の列並列を protocol 単位の dict にまとめて返す（GEA は Name/Type/Description）。"""
        return self.parallel("Protocol Name", ["Protocol Type", "Protocol Description"])


class GeaSubmission(Submission):
    def submission_type(self, definitions):
        """microarray / sequencing / other を判定。次の順に見る（2026-09-18）。

        1. SDRF の `Technology Type`（array assay→microarray / sequencing assay→sequencing）
        2. 1 が無ければ IDF の `Comment[Submission Type]`（submission_type_map。Xenium / Other は other）
        3. それも無ければ IDF の `Comment[Experiment Type]`（experiment_types の technology）
           ＝ Comment[Submission Type] を持たない旧 IDF のための後方互換
        """
        defs = definitions or {}
        tmap = defs.get("technology_type_map", {})
        # 1. Technology Type（SDRF）
        if self.sdrf:
            for v in self.sdrf.values("Technology Type"):
                t = tmap.get((v or "").strip())
                if t:
                    return t
        if self.idf:
            # 2. Comment[Submission Type]（IDF）
            smap = defs.get("submission_type_map", {})
            st = (self.idf.first("Comment[Submission Type]") or "").strip()
            if smap.get(st):
                return smap[st]
            # 3. Comment[Experiment Type]（IDF）＝旧 IDF 互換
            info = defs.get("experiment_types", {}).get(self.idf.ae_experiment_type)
            if info and info.get("technology"):
                return info["technology"]
        return "other"
