"""SDRF ルール（GEA_SR / EX / AN / TT / MT / LE / AD / DF / CN / RC / MAN / REGEX）。

ヘッダ＋行から判定できる metadata チェックを実装（node グラフ全走査を要する一部の属性注釈チェックは今後）。
"""
import re
from apps.gea.rules.base import GeaRule, null_values

# 複数回出現が許される列（重複エラーの対象外）
_REPEATABLE = {"Protocol REF", "Array Data File", "Derived Array Data File",
               "Array Data Matrix File", "Derived Array Data Matrix File",
               "Parameter Value", "Comment", "Unit", "Term Source REF", "Term Accession Number",
               "Performer", "Date", "Factor Value"}


def _sdrf_def(context):
    return (context.definitions or {}).get("sdrf", {})


def _empty(v):
    return v is None or str(v).strip() == ""


def _kind(h):
    """列名の種別（Characteristics[x]→Characteristics, Protocol REF→Protocol REF 等）。"""
    m = re.match(r"^(Characteristics|Comment|Parameter Value|Factor Value|Unit)\[", h)
    return m.group(1) if m else h


def _matches_any(colname, patterns):
    for p in patterns:
        try:
            if re.fullmatch(p, colname):
                return True
        except re.error:
            if p == colname:
                return True
    return False


def _has_col(sdrf, name):
    return len(sdrf.col_indices(name)) > 0


def _col_nonempty_all_rows(sdrf, name):
    """列 name が存在し、全行で非空か。"""
    idxs = sdrf.col_indices(name)
    if not idxs:
        return None  # 列なし
    for row in sdrf.rows:
        if _empty(row[idxs[0]] if idxs[0] < len(row) else ""):
            return False
    return True


# ---------------- Source / Sample ----------------
class GEA_SR0001(GeaRule):
    rule_id = "GEA_SR0001"; level = "error"; target = "SDRF/SourceNode"
    description = "A source (starting sample) must have name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        res = _col_nonempty_all_rows(sub.sdrf, "Source Name")
        if res is None:
            return [self.result(message="Source Name column is missing.")]
        return [] if res else [self.result()]


class GEA_SR0004(GeaRule):
    rule_id = "GEA_SR0004"; level = "error"; target = "SDRF/SourceNode"
    description = "A source must have an 'organism' characteristic specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        res = _col_nonempty_all_rows(sub.sdrf, "Characteristics[organism]")
        if res is None:
            return [self.result(message="Characteristics[organism] column is missing.")]
        return [] if res else [self.result()]


class GEA_SR0009(GeaRule):
    rule_id = "GEA_SR0009"; level = "warning"; target = "SDRF/SourceNode"
    description = "A source should have a 'taxonomy_id' characteristic specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [] if _has_col(sub.sdrf, "Characteristics[taxonomy_id]") else [self.result()]


class GEA_SR0005(GeaRule):
    rule_id = "GEA_SR0005"; level = "warning"; target = "SDRF/SourceNode"
    description = "A source should have more than 2 characteristic attributes."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        chars = [h for h in sub.sdrf.header if re.fullmatch(r"Characteristics\[.+\]", h)]
        return [self.result(message=f"{self.description} (Found: {len(chars)})")] if len(chars) < 2 else []


class GEA_SR0006(GeaRule):
    rule_id = "GEA_SR0006"; level = "warning"; target = "SDRF/SourceNode"
    description = "Characteristic types should be unique (case-insensitive)."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        seen, dup = set(), set()
        for h in sub.sdrf.header:
            m = re.fullmatch(r"Characteristics\[(.+)\]", h)
            if m:
                k = m.group(1).strip().lower()
                if k in seen:
                    dup.add(m.group(1))
                seen.add(k)
        return [self.result(message=f"{self.description} ({', '.join(sorted(dup))})")] if dup else []


class GEA_SR0012(GeaRule):
    rule_id = "GEA_SR0012"; level = "error"; target = "SDRF/SourceNode"
    description = "A source should have a 'sample_title' characteristic/comment."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        if _has_col(sub.sdrf, "Comment[sample_title]") or _has_col(sub.sdrf, "Characteristics[sample_title]"):
            return []
        return [self.result()]


# ---------------- Extract ----------------
class GEA_EX0001(GeaRule):
    rule_id = "GEA_EX0001"; level = "error"; target = "SDRF/ExtractNode"
    description = "An extract must have name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        res = _col_nonempty_all_rows(sub.sdrf, "Extract Name")
        if res is None:
            return [self.result(message="Extract Name column is missing.")]
        return [] if res else [self.result()]


class GEA_EX0002(GeaRule):
    rule_id = "GEA_EX0002"; level = "warning"; target = "SDRF/ExtractNode"
    description = "An extract should have a 'Material Type' attribute specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [] if _has_col(sub.sdrf, "Material Type") else [self.result()]


# ---------------- Assay / Technology Type ----------------
class GEA_AN0001(GeaRule):
    rule_id = "GEA_AN0001"; level = "error"; target = "SDRF/ArrayNode"
    description = "An assay must have a name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        res = _col_nonempty_all_rows(sub.sdrf, "Assay Name")
        if res is None:
            return [self.result(message="Assay Name column is missing.")]
        return [] if res else [self.result()]


class GEA_AN0002(GeaRule):
    rule_id = "GEA_AN0002"; level = "error"; target = "SDRF/ArrayNode"
    description = "An assay must have a 'Technology Type' attribute specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [] if _has_col(sub.sdrf, "Technology Type") else [self.result()]


class GEA_TT0001(GeaRule):
    rule_id = "GEA_TT0001"; level = "error"; target = "SDRF/TechnologyType"
    description = "Technology type attribute must have name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        res = _col_nonempty_all_rows(sub.sdrf, "Technology Type")
        if res is None:
            return []  # 列自体の不在は AN0002 で扱う
        return [] if res else [self.result()]


class GEA_AN0005(GeaRule):
    rule_id = "GEA_AN0005"; level = "error"; target = "SDRF/ArrayNode"; only_type = "microarray"
    description = "'Technology Type' must be equal to 'array assay' in micro-array submissions."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        vals = {v.strip() for v in sub.sdrf.values("Technology Type") if v.strip()}
        bad = [v for v in vals if v != "array assay"]
        return [self.result(message=f"{self.description} (Found: {', '.join(sorted(bad))})")] if bad else []


class GEA_AN0009(GeaRule):
    rule_id = "GEA_AN0009"; level = "error"; target = "SDRF/ArrayNode"; only_type = "sequencing"
    description = "'Technology Type' must be equal to 'sequencing assay' in HTS submissions."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        vals = {v.strip() for v in sub.sdrf.values("Technology Type") if v.strip()}
        bad = [v for v in vals if v != "sequencing assay"]
        return [self.result(message=f"{self.description} (Found: {', '.join(sorted(bad))})")] if bad else []


# ---------------- Material Type CV ----------------
class GEA_MT0004(GeaRule):
    rule_id = "GEA_MT0004"; level = "error"; target = "SDRF/MaterialTypeAttribute"
    description = "A 'Material Type' attribute should have a controlled term."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        allowed = ((context.definitions or {}).get("controlled_terms", {})
                   .get("sdrf", {}).get("warning", {}).get("Material Type", []))
        if not allowed:
            return []
        bad = {v.strip() for v in sub.sdrf.values("Material Type") if v.strip() and v.strip() not in allowed}
        return [self.result(message=f"{self.description} ({', '.join(sorted(bad))})")] if bad else []


# ---------------- Labeled Extract / Label（Micro-array / HTS）----------------
class GEA_LE0002(GeaRule):
    rule_id = "GEA_LE0002"; level = "error"; target = "SDRF/LabeledExtractNode"; only_type = "microarray"
    description = "A labeled extract must have name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [] if _has_col(sub.sdrf, "Labeled Extract Name") else [self.result()]


class GEA_LE0004(GeaRule):
    rule_id = "GEA_LE0004"; level = "error"; target = "SDRF/LabeledExtractNode"; only_type = "microarray"
    description = "A labeled extract must have 'Label' attribute specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [] if _has_col(sub.sdrf, "Label") else [self.result()]


class GEA_LE0001(GeaRule):
    rule_id = "GEA_LE0001"; level = "error"; target = "SDRF/LabeledExtractNode"; only_type = "sequencing"
    description = "There must not be a labeled extract in a sequencing experiment."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [self.result()] if _has_col(sub.sdrf, "Labeled Extract Name") else []


class GEA_AD0004(GeaRule):
    rule_id = "GEA_AD0004"; level = "error"; target = "SDRF/ArrayDesignAttribute"; only_type = "sequencing"
    description = "There must not be any array design attributes in a sequencing experiment."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [self.result()] if _has_col(sub.sdrf, "Array Design REF") else []


class GEA_AD0001(GeaRule):
    rule_id = "GEA_AD0001"; level = "error"; target = "SDRF/ArrayDesignAttribute"; only_type = "microarray"
    description = "An array design attribute must have a name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        res = _col_nonempty_all_rows(sub.sdrf, "Array Design REF")
        if res is None:
            return [self.result(message="Array Design REF column is missing.")]
        return [] if res else [self.result()]


# ---------------- Data files ----------------
class GEA_DF0001(GeaRule):
    rule_id = "GEA_DF0001"; level = "error"; target = "SDRF"
    description = "Either one of Array Data File and Array Data Matrix File nodes are required."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        grp = _sdrf_def(context).get("required_data_file_group", {}).get("raw", [])
        return [] if any(_has_col(sub.sdrf, c) for c in grp) else [self.result()]


class GEA_DF0002(GeaRule):
    rule_id = "GEA_DF0002"; level = "error"; target = "SDRF"
    description = "Either one of Derived Array Data File and Derived Array Data Matrix File nodes are required."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        grp = _sdrf_def(context).get("required_data_file_group", {}).get("derived", [])
        return [] if any(_has_col(sub.sdrf, c) for c in grp) else [self.result()]


# ---------------- 一意性 / 未定義 ----------------
class GEA_CN0001(GeaRule):
    rule_id = "GEA_CN0001"; level = "error"; target = "SDRF"
    description = "Characteristics column names must be unique."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        seen, dup = set(), set()
        for h in sub.sdrf.header:
            if re.fullmatch(r"Characteristics\[.+\]", h):
                if h in seen:
                    dup.add(h)
                seen.add(h)
        return [self.result(message=f"{self.description} ({', '.join(sorted(dup))})")] if dup else []


class GEA_RC0002(GeaRule):
    rule_id = "GEA_RC0002"; level = "error"; target = "SDRF"
    description = "Predefined comment columns must be unique."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        seen, dup = set(), set()
        for h in sub.sdrf.header:
            if re.fullmatch(r"Comment\[.+\]", h):
                if h in seen:
                    dup.add(h)
                seen.add(h)
        return [self.result(message=f"{self.description} ({', '.join(sorted(dup))})")] if dup else []


class GEA_UNDEF(GeaRule):
    rule_id = "GEA_SR0002"; level = "error"; target = "SDRF"
    description = "Undefined column exists."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        patterns = _sdrf_def(context).get("fields", [])
        bad = [h for h in sub.sdrf.header if h and not _matches_any(h, patterns)]
        return [self.result(message=f"{self.description} ({', '.join(sorted(set(bad)))})")] if bad else []


# ---------------- 必須列（type 別）----------------
class GEA_MAN0011(GeaRule):
    rule_id = "GEA_MAN0011"; level = "error"; target = "SDRF"; only_type = "microarray"
    description = "Mandatory node (column) is required."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        req = _sdrf_def(context).get("required_columns_microarray", [])
        miss = [p for p in req if not _matches_any_header(sub.sdrf.header, p)]
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


class GEA_MAN0012(GeaRule):
    rule_id = "GEA_MAN0012"; level = "error"; target = "SDRF"; only_type = "sequencing"
    description = "Mandatory node (column) is required."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        req = _sdrf_def(context).get("required_columns_sequencing", [])
        miss = [p for p in req if not _matches_any_header(sub.sdrf.header, p)]
        return [self.result(message=f"{self.description} ({', '.join(miss)})")] if miss else []


def _matches_any_header(header, pattern):
    for h in header:
        try:
            if re.fullmatch(pattern, h):
                return True
        except re.error:
            if pattern == h:
                return True
    return False


# ---------------- SDRF 形式（Comment 系 accession）----------------
class GEA_SDRF_REGEX(GeaRule):
    """value_formats のうち SDRF 側 Comment 列の形式検査（GEA_REGEX0010-0051 相当を一括）。"""
    rule_id = "GEA_REGEX0010"; level = "error"; target = "SDRF"
    description = "Format Error"

    _sdrf_fields = (
        "Comment[BioSample]", "Comment[SRA_EXPERIMENT]", "Comment[SRA_RUN]", "Comment[SRA_ANALYSIS]",
        "Comment[JGA_STUDY]", "Comment[JGA_SAMPLE]", "Comment[JGA_EXPERIMENT]", "Comment[JGA_DATA]",
        "Comment[JGA_ANALYSIS]", "Comment[GEO_SAMPLE]", "Comment[GEO_SERIES]",
        "Comment[ArrayExpress_Experiment]", "Protocol REF",
    )

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        fmts = (context.definitions or {}).get("value_formats", {})
        nulls = null_values(context)
        out = []
        from common.magetab.biosample import assay_name
        for col in self._sdrf_fields:
            pat = fmts.get(col)
            if not pat:
                continue
            for i in sub.sdrf.col_indices(col):
                for ri, row in enumerate(sub.sdrf.rows):
                    v = (row[i] if i < len(row) else "").strip()
                    if v and v not in nulls and not re.fullmatch(pat, v):
                        out.append(self.result(message=f"Format Error '{col}' ('{v}')",
                                               line=ri + 1, assay=assay_name(sub, ri)))
        return out
