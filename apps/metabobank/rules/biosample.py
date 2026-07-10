"""BioSample 整合ルール（MB_SR0021/0022/0023）。DB 参照（内部 DB）。

SDRF の Characteristics[attr] を、参照 BioSample（Comment[BioSample]=SAMD）の DB 属性と突合。
context.biosample_attrs（SAMD -> {attr: value}）が None（未取得＝skip_db 等）ならスキップ。
比較対象は definitions.biosample_sync.sync_characteristics。
"""
import re
from apps.metabobank.rules.base import MbRule


def _bs_sync(context):
    return (context.definitions or {}).get("biosample_sync", {})


def _row_samd(sub, row):
    for col in _bs_sync_ref_cols(sub):
        for i in sub.sdrf.col_indices(col):
            v = (row[i] if i < len(row) else "").strip()
            if re.match(r"^SAMD\d+$", v):
                return v
    return None


def _bs_sync_ref_cols(sub):
    return ["Comment[BioSample]", "Characteristics[biosample_accession]"]


class MB_SR0021(MbRule):
    rule_id = "MB_SR0021"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "BioSample attribute referenced in Characteristics is missing in the BioSample."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        sync = _bs_sync(context).get("sync_characteristics", [])
        char_cols = {}
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Characteristics\[(.+)\]", h)
            if m and m.group(1) in sync:
                char_cols[m.group(1)] = sub.sdrf.col_indices(h)[0]
        out = []
        for row in sub.sdrf.rows:
            samd = _row_samd(sub, row)
            if not samd or samd not in attrs:
                continue
            bs = attrs[samd]
            for attr in char_cols:
                if attr not in bs:
                    out.append(self.result(message=f"{self.description} ({samd}: '{attr}')"))
        return out


class MB_SR0022(MbRule):
    rule_id = "MB_SR0022"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Referenced BioSample has no attribute (not found in the account/DB)."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        out, seen = [], set()
        for row in sub.sdrf.rows:
            samd = _row_samd(sub, row)
            if samd and samd not in seen:
                seen.add(samd)
                if samd not in attrs or not attrs[samd]:
                    out.append(self.result(message=f"{self.description} ({samd})"))
        return out


class MB_SR0023(MbRule):
    rule_id = "MB_SR0023"; level = "error"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Characteristics value and BioSample attribute value do not match."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        sync = _bs_sync(context).get("sync_characteristics", [])
        char_cols = {}
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Characteristics\[(.+)\]", h)
            if m and m.group(1) in sync:
                char_cols[m.group(1)] = sub.sdrf.col_indices(h)[0]
        out = []
        for row in sub.sdrf.rows:
            samd = _row_samd(sub, row)
            if not samd or samd not in attrs:
                continue
            bs = attrs[samd]
            for attr, idx in char_cols.items():
                sdrf_v = (row[idx] if idx < len(row) else "").strip()
                bs_v = str(bs.get(attr, "")).strip()
                if attr in bs and sdrf_v and bs_v and sdrf_v != bs_v:
                    out.append(self.result(message=f"{self.description} ({samd} {attr}: SDRF '{sdrf_v}' != BS '{bs_v}')"))
        return out
