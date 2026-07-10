"""IDF↔SDRF 横断ルール（MB_CR）。"""
import re
from apps.metabobank.rules.base import MbRule


class MB_CR0001(MbRule):
    rule_id = "MB_CR0001"; level = "error"; target = "IDF,SDRF"
    description = "Experimental factor in SDRF does not match IDF Experimental Factor Name."

    def validate(self, sub, context):
        if not sub.idf or not sub.sdrf:
            return []
        idf_factors = {n.strip() for n in sub.idf.get("Experimental Factor Name") if n.strip()}
        sdrf_factors = set()
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Factor Value\[(.+)\]", h)
            if m:
                sdrf_factors.add(m.group(1).strip())
        bad = sdrf_factors - idf_factors
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})")] if bad else []


class MB_CR0002(MbRule):
    rule_id = "MB_CR0002"; level = "error"; target = "IDF,SDRF"
    description = "Protocol referenced in SDRF is not defined in IDF Protocol Name."

    def validate(self, sub, context):
        if not sub.idf or not sub.sdrf:
            return []
        idf_protocols = {n.strip() for n in sub.idf.get("Protocol Name") if n.strip()}
        idxs = sub.sdrf.col_indices("Protocol REF")
        refs = set()
        for row in sub.sdrf.rows:
            for i in idxs:
                v = (row[i] if i < len(row) else "").strip()
                if v:
                    refs.add(v)
        bad = refs - idf_protocols
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})")] if bad else []


class MB_CR0003(MbRule):
    rule_id = "MB_CR0003"; level = "error"; target = "IDF,SDRF"
    description = "Parameter Value in SDRF is not declared as a Protocol Parameter in IDF."

    def validate(self, sub, context):
        if not sub.idf or not sub.sdrf:
            return []
        idf_params = set()
        for p in sub.idf.protocols():
            for x in (p["Protocol Parameters"] or "").split(";"):
                if x.strip():
                    idf_params.add(x.strip())
        sdrf_params = set()
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Parameter Value\[(.+)\]", h)
            if m:
                sdrf_params.add(m.group(1).strip())
        bad = sdrf_params - idf_params
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})")] if bad else []


class MB_CR0004(MbRule):
    rule_id = "MB_CR0004"; level = "warning"; target = "IDF,SDRF"
    description = "Re-analysis accession differs between IDF and SDRF."

    def validate(self, sub, context):
        if not sub.idf or not sub.sdrf:
            return []
        idf_re = {v.strip() for v in sub.idf.get("Comment[Related study]") if v.strip()}
        sdrf_re = set()
        for i in sub.sdrf.col_indices("Comment[Reanalysis of]"):
            for row in sub.sdrf.rows:
                v = (row[i] if i < len(row) else "").strip()
                m = re.match(r"^(MTBKS\d+):", v)
                if m:
                    sdrf_re.add(m.group(1))
        bad = sdrf_re - idf_re if idf_re else set()
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})")] if bad else []
