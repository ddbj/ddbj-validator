"""DRA 構造チェック（DRA_R0002）。

XSD を well-formed＋構造の粗いゲートに縮小する方針のため、値（enum 等）は cv.py に委ね、
ここでは各オブジェクトの必須コンテナの存在のみを構造チェックする（分かりやすいメッセージで）。
- EXPERIMENT: DESIGN / DESIGN/LIBRARY_DESCRIPTOR / PLATFORM。
- RUN: DATA_BLOCK。
- ANALYSIS: DATA_BLOCK。

「あるか」は reader が model へ持ち上げている（元は .raw の XML を直接辿っていたが、
それだと入力形式が XML に固定される）。
"""
from apps.dra.rules.base import DraRule


class DRA_R0002(DraRule):
    rule_id = "DRA_R0002"
    level = "error"
    target = "#structure"
    description = "XML document is invalid against the schema."

    def validate(self, submission, context):
        out = []
        for e in submission.experiments:
            for present, label in ((e.design_present, "DESIGN"),
                                   (e.library_descriptor_present, "LIBRARY_DESCRIPTOR"),
                                   (e.platform_present, "PLATFORM")):
                if not present:
                    out.append(self.result(sample=e.label,
                                           message=f"Experiment is missing required element '{label}'."))
        for r in submission.runs:
            if not r.data_block_present:
                out.append(self.result(sample=r.label,
                                       message="Run is missing required element 'DATA_BLOCK'."))
        for a in submission.analyses:
            if not a.data_block_present:
                out.append(self.result(sample=a.label,
                                       message="Analysis is missing required element 'DATA_BLOCK'."))
        return out
