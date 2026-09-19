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
        return (self.first("Comment[Number of Channel]") or "").strip()

    def protocols(self):
        """Protocol* の列並列を protocol 単位の dict にまとめて返す（GEA は Name/Type/Description）。"""
        return self.parallel("Protocol Name", ["Protocol Type", "Protocol Description"])


class GeaSubmission(Submission):
    def submission_type(self, definitions):
        """microarray / sequencing / xenium / other を判定。

        判定根拠は **IDF の `Comment[Submission Type]` だけ**（`submission_type_map` で変換）。
        値が無い・CV 外なら `other` を返す。

        - SDRF の `Technology Type` は廃止した（2026-09-18）。
        - `Comment[Experiment Type]` からの**推定はしない**（2026-09-18）。推定すると、移行で
          submission type を付け忘れた submission が experiment type 次第で microarray / sequencing と
          みなされ、本来と違うルール群で検査されてしまう。付いていなければ `other`（= Common の
          ルールだけ）に倒すほうが安全。
        """
        defs = definitions or {}
        if self.idf:
            smap = defs.get("submission_type_map", {})
            st = (self.idf.first("Comment[Submission Type]") or "").strip()
            if smap.get(st):
                return smap[st]
        return "other"
