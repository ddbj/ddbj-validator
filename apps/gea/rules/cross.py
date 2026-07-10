"""IDF↔SDRF 横断ルール（GEA_REF。ファイル内で判定できるもの）。

DRA/DB を要する参照整合（REF0002/0003/0004/0005/0007/0008）は今後（biosample.py／DB 参照で拡張）。
"""
import re
from apps.gea.rules.base import GeaRule


class GEA_REF0001(GeaRule):
    rule_id = "GEA_REF0001"; level = "warning"; target = "IDF and SDRF"
    description = "IDF should not contain protocol definitions that are not used in SDRF."

    def validate(self, sub, context):
        if not sub.idf or not sub.sdrf:
            return []
        defined = {n.strip() for n in sub.idf.get("Protocol Name") if n.strip()}
        refs = set()
        for i in sub.sdrf.col_indices("Protocol REF"):
            for row in sub.sdrf.rows:
                v = (row[i] if i < len(row) else "").strip()
                if v:
                    refs.add(v)
        unused = defined - refs
        return [self.result(message=f"{self.description} ({', '.join(sorted(unused))})")] if unused else []


class GEA_REF0006(GeaRule):
    rule_id = "GEA_REF0006"; level = "error"; target = "IDF and SDRF"; only_type = "microarray"
    description = "Array designs referenced in IDF and SDRF are not identical."

    def validate(self, sub, context):
        if not sub.idf or not sub.sdrf:
            return []
        idf_ad = {v.strip() for v in sub.idf.get("Comment[Array Design REF]") if v.strip()}
        sdrf_ad = {v.strip() for v in sub.sdrf.values("Array Design REF") if v.strip()}
        if not idf_ad and not sdrf_ad:
            return []
        if idf_ad != sdrf_ad:
            diff = (idf_ad ^ sdrf_ad)
            return [self.result(message=f"{self.description} ({', '.join(sorted(diff))})")]
        return []


class GEA_REF0007(GeaRule):
    rule_id = "GEA_REF0007"; level = "error"; target = "SDRF"; only_type = "sequencing"
    description = "Runs referenced in SDRF and Array Data File are not identical."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        runs = {v.strip().upper() for v in sub.sdrf.values("Comment[SRA_RUN]") if v.strip()}
        # Array Data File のうち DRR 形式のものを Run 参照として抽出
        adf = {v.strip().upper() for v in sub.sdrf.values("Array Data File")
               if re.match(r"^DRR\d+$", v.strip().upper())}
        if not runs or not adf:
            return []
        if runs != adf:
            diff = runs ^ adf
            return [self.result(message=f"{self.description} ({', '.join(sorted(diff))})")]
        return []
