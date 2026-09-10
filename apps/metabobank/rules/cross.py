"""IDF↔SDRF 横断ルール（MB_CR）。"""
import re
from apps.metabobank.rules.base import MbRule, null_values


class MB_CR0001(MbRule):
    rule_id = "MB_CR0001"; level = "error"; target = "IDF,SDRF"
    description = "Experimental factor in SDRF does not match IDF Experimental Factor Name."

    # 名前の無い Factor Value[] の表示名（そのまま出すと空文字で読めない）
    _UNNAMED = "(unnamed)"

    def validate(self, sub, context):
        r"""IDF Experimental Factor Name と SDRF Factor Value[...] を双方向に突き合わせる。

        factor 自体は任意項目なので「どちらにも無い」は無指摘。片側にしか無ければ向きを
        添えて指摘する（両方向あれば 2 件に分ける）。
        IDF 側の null value（missing 等）は集合から除くが、これは無指摘にするためではなく
        MB_IR0007（required_not_null）が同じ問題を指摘するので二重報告を避けるため。
        SDRF 側は除かないので Factor Value[missing] は only in SDRF として指摘される。

        `[]` の中身が空の `Factor Value[]` も拾う（正規表現は `.*`）。IDF の factor name は
        必ず非空なので照合で必ず余り、`only in SDRF: (unnamed)` として出る。`.+` だと
        素通しし、MB_SR0006 も sdrf.fields の `Factor Value\[.*\]` に当たるため
        誰も指摘しなくなる。
        """
        if not sub.idf or not sub.sdrf:
            return []
        nulls = null_values(context)
        idf_factors = {n.strip() for n in sub.idf.get("Experimental Factor Name")
                       if n.strip() and n.strip() not in nulls}
        sdrf_factors = set()
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Factor Value\[(.*)\]", h)
            if m:
                sdrf_factors.add(m.group(1).strip() or self._UNNAMED)
        out = []
        for label, bad in (("only in SDRF", sdrf_factors - idf_factors),
                           ("only in IDF", idf_factors - sdrf_factors)):
            if bad:
                joined = ", ".join(sorted(bad))
                side = {"sdrf_only" if label == "only in SDRF" else "idf_only": joined}
                out.append(self.result(
                    message=f"{self.description} ({label}: {joined})", **side))
        return out


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
        if not bad:
            return []
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})",
                            sdrf_only=", ".join(sorted(bad)))]


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
        if not bad:
            return []
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})",
                            sdrf_only=", ".join(sorted(bad)))]


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
        if not bad:
            return []
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})",
                            sdrf_only=", ".join(sorted(bad)),
                            idf_only=", ".join(sorted(idf_re)))]
