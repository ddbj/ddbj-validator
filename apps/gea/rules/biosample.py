"""BioSample 整合ルール（GEA_BS0001/0002/0003）。DB 参照（内部 DB）。

SDRF の Characteristics[attr] を、参照 BioSample（Comment[BioSample]=SAMD）の DB 属性と突合。
context.biosample_attrs（SAMD -> {attr: value}）が None（未取得＝skip_db 等）ならスキップ。
比較対象は definitions.biosample_sync.sync_characteristics。
※これらは legacy rules.txt に無い GEA 追加ルール（MB_SR0021-0023 相当）。
"""
import re
from apps.gea.rules.base import GeaRule


def _bs_sync(context):
    return (context.definitions or {}).get("biosample_sync", {})


def _ref_cols(context):
    return _bs_sync(context).get("biosample_ref_columns", ["Comment[BioSample]"])


def _row_samd(sub, context, row):
    for col in _ref_cols(context):
        for i in sub.sdrf.col_indices(col):
            v = (row[i] if i < len(row) else "").strip()
            if re.match(r"^SAMD\d+$", v):
                return v
    return None


def _char_cols(sub, context):
    sync = _bs_sync(context).get("sync_characteristics", [])
    out = {}
    for h in sub.sdrf.header:
        m = re.fullmatch(r"Characteristics\[(.+)\]", h)
        if m and m.group(1) in sync:
            out[m.group(1)] = sub.sdrf.col_indices(h)[0]
    return out


class GEA_BS0002(GeaRule):
    rule_id = "GEA_BS0002"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Referenced BioSample is not found in the account/DB."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        out, seen = [], set()
        for row in sub.sdrf.rows:
            samd = _row_samd(sub, context, row)
            if samd and samd not in seen:
                seen.add(samd)
                if samd not in attrs or not attrs[samd]:
                    out.append(self.result(message=f"{self.description} ({samd})"))
        return out


class GEA_BS0001(GeaRule):
    rule_id = "GEA_BS0001"; level = "warning"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "BioSample attribute referenced in Characteristics is missing in the BioSample."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        char_cols = _char_cols(sub, context)
        out = []
        for row in sub.sdrf.rows:
            samd = _row_samd(sub, context, row)
            if not samd or samd not in attrs:
                continue
            bs = attrs[samd]
            for attr in char_cols:
                if attr not in bs:
                    out.append(self.result(message=f"{self.description} ({samd}: '{attr}')"))
        return out


class GEA_BS0003(GeaRule):
    rule_id = "GEA_BS0003"; level = "error"; target = "SDRF"; requires_rdb = True; requires_auth = True
    description = "Characteristics value and BioSample attribute value do not match."

    def validate(self, sub, context):
        attrs = getattr(context, "biosample_attrs", None)
        if attrs is None or not sub.sdrf:
            return []
        char_cols = _char_cols(sub, context)
        out = []
        for row in sub.sdrf.rows:
            samd = _row_samd(sub, context, row)
            if not samd or samd not in attrs:
                continue
            bs = attrs[samd]
            for attr, idx in char_cols.items():
                sdrf_v = (row[idx] if idx < len(row) else "").strip()
                bs_v = str(bs.get(attr, "")).strip()
                if attr in bs and sdrf_v and bs_v and sdrf_v != bs_v:
                    out.append(self.result(
                        message=f"{self.description} ({samd} {attr}: SDRF '{sdrf_v}' != BS '{bs_v}')",
                        autofix=True, samd=samd, attr=attr, new_value=bs_v))
        return out
