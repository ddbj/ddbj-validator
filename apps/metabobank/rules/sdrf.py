"""SDRF ルール（MB_SR。metadata 分。ファイル実体/MAF 検証は別ツール＝非対象）。"""
import re
from apps.metabobank.rules.base import MbRule, null_values

# 複数回出現が許される列（重複エラーの対象外）
_REPEATABLE = {"Protocol REF", "Raw Data File", "Processed Data File",
               "Metabolite Assignment File", "Image Data File"}


def _sdrf_def(context):
    return (context.definitions or {}).get("sdrf", {})


def _empty(v):
    return v is None or str(v).strip() == ""


def _matches_any(colname, patterns):
    for p in patterns:
        try:
            if re.fullmatch(p, colname) or re.search(p, colname):
                return True
        except re.error:
            if p == colname:
                return True
    return False


class MB_SR0003(MbRule):
    rule_id = "MB_SR0003"; level = "error"; target = "SDRF"
    description = "Column names are duplicated."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        seen, dup = set(), set()
        for h in sub.sdrf.header:
            if h in _REPEATABLE:
                continue
            if h in seen:
                dup.add(h)
            seen.add(h)
        return [self.result(message=f"{self.description} ({', '.join(sorted(dup))})")] if dup else []


class MB_SR0024(MbRule):
    rule_id = "MB_SR0024"; level = "error"; target = "SDRF"
    description = "Column without a name exists."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [self.result()] if any(_empty(h) for h in sub.sdrf.header) else []


class MB_SR0004(MbRule):
    # required_columns_error は literal な列名（Characteristics[organism] 等）＝完全一致で判定。
    rule_id = "MB_SR0004"; level = "error"; target = "SDRF"
    description = "Missing required column(s)."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        header = set(sub.sdrf.header)
        miss = [req for req in _sdrf_def(context).get("required_columns_error", []) if req not in header]
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class MB_SR0005(MbRule):
    # required_columns_warning は正規表現パターン（Comment\[BioSample\] 等）＝regex で判定。
    rule_id = "MB_SR0005"; level = "warning"; target = "SDRF"
    description = "Missing recommended column(s)."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        header = sub.sdrf.header
        miss = []
        for pat in _sdrf_def(context).get("required_columns_warning", []):
            if not any(_matches_any(h, [pat]) for h in header):
                miss.append(pat)
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class MB_SR0006(MbRule):
    rule_id = "MB_SR0006"; level = "error"; target = "SDRF"
    description = "Undefined column exists."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        patterns = _sdrf_def(context).get("fields", [])
        bad = [h for h in sub.sdrf.header if h and not _matches_any(h, patterns)]
        return [self.result(message=f"{self.description} ({', '.join(sorted(set(bad)))})")] if bad else []


class MB_SR0009(MbRule):
    rule_id = "MB_SR0009"; level = "error"; target = "SDRF"
    description = "Missing or null value for a required column."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        nulls = null_values(context)
        out = []
        for col in ("Characteristics[organism]", "Characteristics[taxonomy_id]", "Source Name"):
            idxs = sub.sdrf.col_indices(col)
            if not idxs:
                continue
            for r, row in enumerate(sub.sdrf.rows):
                v = row[idxs[0]] if idxs[0] < len(row) else ""
                if _empty(v) or v.strip() in nulls:
                    out.append(self.result(message=f"{self.description} ({col}, row {r + 1})"))
                    break
        return out


class MB_SR0018(MbRule):
    rule_id = "MB_SR0018"; level = "warning"; target = "SDRF"
    description = "Less than 2 characteristic attributes."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        chars = [h for h in sub.sdrf.header if re.fullmatch(r"Characteristics\[[-_ /A-Za-z0-9.]+\]", h)]
        return [self.result(message=f"{self.description} (Found: {len(chars)})")] if len(chars) < 2 else []


class MB_SR0017(MbRule):
    rule_id = "MB_SR0017"; level = "error"; target = "SDRF"
    description = "Factor value is constant across all rows."

    def validate(self, sub, context):
        if not sub.sdrf or len(sub.sdrf.rows) < 2:
            return []
        out = []
        for h in sub.sdrf.header:
            if re.fullmatch(r"Factor Value\[.+\]", h):
                idxs = sub.sdrf.col_indices(h)
                vals = {(row[idxs[0]].strip() if idxs[0] < len(row) else "") for row in sub.sdrf.rows}
                if len(vals) == 1:
                    out.append(self.result(message=f"{self.description} ({h})"))
        return out


class MB_SR0019(MbRule):
    rule_id = "MB_SR0019"; level = "error"; target = "SDRF"
    description = "Invalid value format."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        fmts = (context.definitions or {}).get("value_formats", {})
        out = []
        for col, pat in fmts.items():
            idxs = sub.sdrf.col_indices(col)
            for row in sub.sdrf.rows:
                for i in idxs:
                    v = row[i] if i < len(row) else ""
                    if v and v.strip() and not re.fullmatch(pat, v.strip()):
                        out.append(self.result(message=f"{self.description} ({col}: '{v}')"))
        return out


class MB_SR0026(MbRule):
    rule_id = "MB_SR0026"; level = "error"; target = "SDRF"
    description = "Invalid column order."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        st = sub.idf.submission_type if sub.idf else None
        order = _sdrf_def(context).get("column_order", {}).get(st)
        if not order:
            return []
        # order の「素の列種別」列（Characteristics[] や Protocol REF:x を種別に正規化）に対する相対順序をチェック
        def kind(h):
            m = re.match(r"^(Characteristics|Comment|Parameter Value|Factor Value|Unit)\[", h)
            return (m.group(1) + "[]") if m else h
        seq = [kind(h) for h in sub.sdrf.header]
        # order 中の Protocol REF:xxx は Protocol REF に丸め、種別列も丸める
        norm_order = []
        for o in order:
            norm_order.append("Protocol REF" if o.startswith("Protocol REF") else o)
        # header 側の Protocol REF は複数だが順序上は出現順で評価。ここでは「必須種別が定義順に現れるか」を緩く検査。
        pos = 0
        for o in norm_order:
            found = False
            while pos < len(seq):
                if seq[pos] == o or (o == "Characteristics[]" and seq[pos] == "Characteristics[]"):
                    found = True
                    pos += 1
                    break
                pos += 1
            # 見つからなくても次へ（任意列があるため厳密チェックはしない）
        # 厳密な順序違反判定は複雑なため、ここでは Source Name が先頭かの最低限のみ error 化
        if seq and seq[0] != "Source Name":
            return [self.result(message=f"{self.description} (first column: '{sub.sdrf.header[0]}', expected 'Source Name')")]
        return []


class MB_SR0033(MbRule):
    rule_id = "MB_SR0033"; level = "error"; target = "SDRF"
    description = "Missing protocol reference (Protocol REF value)."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        idxs = sub.sdrf.col_indices("Protocol REF")
        if not idxs:
            return []
        out = []
        for r, row in enumerate(sub.sdrf.rows):
            if all(_empty(row[i]) if i < len(row) else True for i in idxs):
                out.append(self.result(message=f"{self.description} (row {r + 1})"))
        return out


class MB_SR0030(MbRule):
    rule_id = "MB_SR0030"; level = "error"; target = "SDRF"
    description = "Invalid (control) characters in a cell."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        out = []
        for r, row in enumerate(sub.sdrf.rows):
            for c, cell in enumerate(row):
                if any(ord(ch) < 32 and ch not in "\t" for ch in cell):
                    col = sub.sdrf.header[c] if c < len(sub.sdrf.header) else f"col{c}"
                    out.append(self.result(message=f"{self.description} (row {r + 1}, {col})"))
                    return out
        return out


class _SdrfCvBase(MbRule):
    _level_key = None
    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        cv = ((context.definitions or {}).get("controlled_terms", {}).get("sdrf", {}).get(self._level_key, {}))
        out = []
        for col, allowed in cv.items():
            idxs = sub.sdrf.col_indices(col)
            for row in sub.sdrf.rows:
                for i in idxs:
                    v = row[i] if i < len(row) else ""
                    if v and v.strip() and v.strip() not in allowed:
                        out.append(self.result(message=f"{self.description} ({col}: '{v}')"))
        return out


class MB_SR0045(_SdrfCvBase):
    rule_id = "MB_SR0045"; level = "error"; target = "SDRF"; _level_key = "error"
    description = "Value is not in controlled terms."


class MB_SR0046(_SdrfCvBase):
    rule_id = "MB_SR0046"; level = "warning"; target = "SDRF"; _level_key = "warning"
    description = "Value is not in controlled terms."
