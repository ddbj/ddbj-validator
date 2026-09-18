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
        """microarray / sequencing / xenium / other を判定。次の順に見る（2026-09-18）。

        1. IDF の `Comment[Submission Type]`（submission_type_map）
        2. 無ければ IDF の `Comment[Experiment Type]`（experiment_types の technology）
           ＝ `Comment[Submission Type]` を持たない旧 IDF のための後方互換

        SDRF の `Technology Type` は廃止した（2026-09-18）。submission type は IDF 側だけで決める。
        """
        defs = definitions or {}
        if self.idf:
            # 1. Comment[Submission Type]（IDF）
            smap = defs.get("submission_type_map", {})
            st = (self.idf.first("Comment[Submission Type]") or "").strip()
            if smap.get(st):
                return smap[st]
            # 2. Comment[Experiment Type]（IDF）＝旧 IDF 互換
            info = defs.get("experiment_types", {}).get(self.idf.ae_experiment_type)
            if info and info.get("technology"):
                return info["technology"]
        return "other"
