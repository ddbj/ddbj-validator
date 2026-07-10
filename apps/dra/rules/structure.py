"""DRA 構造チェック（DRA_R0002）。

XSD を well-formed＋構造の粗いゲートに縮小する方針のため、値（enum 等）は cv.py に委ね、
ここでは各オブジェクトの必須コンテナの存在のみを構造チェックする（分かりやすいメッセージで）。
- EXPERIMENT: DESIGN / DESIGN/LIBRARY_DESCRIPTOR / PLATFORM。
- RUN: DATA_BLOCK。
- ANALYSIS: DATA_BLOCK。
"""
from apps.dra.rules.base import DraRule


class DRA_R0002(DraRule):
    rule_id = "DRA_R0002"
    level = "error"
    target = "#structure"
    description = "XML document is invalid against the schema."

    def _missing(self, raw, path):
        return raw is None or raw.find(path) is None

    def validate(self, submission, context):
        out = []
        for e in submission.experiments:
            for path, label in (("./DESIGN", "DESIGN"),
                                ("./DESIGN/LIBRARY_DESCRIPTOR", "LIBRARY_DESCRIPTOR"),
                                ("./PLATFORM", "PLATFORM")):
                if self._missing(e.raw, path):
                    out.append(self.result(sample=e.label,
                                           message=f"Experiment is missing required element '{label}'."))
        for r in submission.runs:
            if self._missing(r.raw, "./DATA_BLOCK"):
                out.append(self.result(sample=r.label,
                                       message="Run is missing required element 'DATA_BLOCK'."))
        for a in submission.analyses:
            if self._missing(a.raw, "./DATA_BLOCK"):
                out.append(self.result(sample=a.label,
                                       message="Analysis is missing required element 'DATA_BLOCK'."))
        return out
