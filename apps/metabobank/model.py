"""MetaboBank validator の内部表現（MAGE-TAB: IDF＋SDRF）。

汎用の Idf/Sdrf/Submission は common/magetab に集約。ここでは MB 固有アクセサのみ追加する。
"""
from common.magetab.model import Idf as BaseIdf, Sdrf, Submission


class Idf(BaseIdf):
    @property
    def submission_type(self):
        return (self.first("Comment[Submission type]") or "").strip()

    @property
    def bioproject(self):
        return (self.first("Comment[BioProject]") or "").strip()

    def protocols(self):
        """Protocol* の列並列を protocol 単位の dict にまとめて返す。"""
        return self.parallel("Protocol Name", [
            "Protocol Type", "Protocol Description", "Protocol Parameters",
            "Protocol Hardware", "Protocol Software",
        ])


class MbSubmission(Submission):
    pass
