"""SDRF node グラフ／属性名チェック（GEA_EX/LE/AN/ADN/ADMN/DADN/DADMN/SM/SC/NN/PN/PV/UA/CA/L/MT/FV/LC/G0011）。

node の incoming edge に付随する protocol type を graph.py で解決して判定する。
"""
import re
from apps.gea.rules.base import GeaRule
from apps.gea.graph import build_graph


def _empty(v):
    return v is None or str(v).strip() == ""


def _graph(sub):
    g = getattr(sub, "_gea_graph", None)
    if g is None:
        g = build_graph(sub)
        try:
            sub._gea_graph = g
        except Exception:
            pass
    return g


def _has_col(sdrf, name):
    return len(sdrf.col_indices(name)) > 0


def _all_empty(sdrf, name):
    """列 name が存在し、全行空か。"""
    idxs = sdrf.col_indices(name)
    if not idxs:
        return False
    for row in sdrf.rows:
        if not _empty(row[idxs[0]] if idxs[0] < len(row) else ""):
            return False
    return True


# ---------------- node incoming protocol ----------------
class _IncomingProtocol(GeaRule):
    """指定 node の incoming edge に必須 protocol type（いずれか）が含まれるか。"""
    _node = None
    _ptypes = ()   # このいずれかが incoming にあれば OK
    target = "SDRF"

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        g = _graph(sub)
        types = g.incoming(self._node)
        if types is None:   # node 自体が無い（別ルールで検出）
            return []
        return [] if (set(self._ptypes) & types) else [self.result()]


class GEA_EX0003(_IncomingProtocol):
    rule_id = "GEA_EX0003"; level = "error"; target = "SDRF/ExtractNode"; only_type = "microarray"
    _node = "Extract Name"; _ptypes = ("nucleic acid extraction protocol",)
    description = "A nucleic acid extraction protocol must be included."


class GEA_EX0004(_IncomingProtocol):
    rule_id = "GEA_EX0004"; level = "error"; target = "SDRF/ExtractNode"; only_type = "sequencing"
    _node = "Extract Name"; _ptypes = ("nucleic acid library construction protocol",)
    description = "A nucleic acid library construction protocol must be included."


class GEA_LE0005(_IncomingProtocol):
    rule_id = "GEA_LE0005"; level = "error"; target = "SDRF/LabeledExtractNode"; only_type = "microarray"
    _node = "Labeled Extract Name"; _ptypes = ("nucleic acid labeling protocol",)
    description = "A nucleic acid labeling protocol must be included."


class GEA_AN0003(_IncomingProtocol):
    rule_id = "GEA_AN0003"; level = "error"; target = "SDRF/ArrayNode"; only_type = "sequencing"
    _node = "Assay Name"; _ptypes = ("nucleic acid sequencing protocol",)
    description = "A nucleic acid sequencing protocol must be included."


class GEA_AN0004(_IncomingProtocol):
    rule_id = "GEA_AN0004"; level = "error"; target = "SDRF/ArrayNode"; only_type = "microarray"
    _node = "Assay Name"; _ptypes = ("nucleic acid hybridization to array protocol",)
    description = "A nucleic acid hybridization to array protocol must be included."


class GEA_DADN0004(_IncomingProtocol):
    rule_id = "GEA_DADN0004"; level = "error"; target = "SDRF/DerivedArrayDataNode"
    _node = "Derived Array Data File"; _ptypes = ("normalization data transformation protocol", "high throughput sequence alignment protocol")
    description = ("A normalization data transformation protocol that describes the analysis methods "
                   "used to generate the processed data file(s) must be included.")


class GEA_DADMN0004(_IncomingProtocol):
    rule_id = "GEA_DADMN0004"; level = "error"; target = "SDRF/DerivedArrayDataMatrixNode"
    _node = "Derived Array Data Matrix File"; _ptypes = ("normalization data transformation protocol", "high throughput sequence alignment protocol")
    description = ("A normalization data transformation protocol that describes the analysis methods "
                   "used to generate the processed data matrix file must be included.")


class _IncomingAny(GeaRule):
    """指定 node の incoming edge に protocol が 1 つ以上あるか。"""
    _node = None
    target = "SDRF"

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        types = _graph(sub).incoming(self._node)
        if types is None:
            return []
        return [] if types else [self.result()]


class GEA_ADN0004(_IncomingAny):
    rule_id = "GEA_ADN0004"; level = "error"; target = "SDRF/ArrayDataNode"; only_type = "microarray"
    _node = "Array Data File"
    description = "An array data node (raw data file) should be described by a protocol."


class GEA_ADMN0004(_IncomingAny):
    rule_id = "GEA_ADMN0004"; level = "error"; target = "SDRF/ArrayDataMatrixNode"; only_type = "microarray"
    _node = "Array Data Matrix File"
    description = "An array data matrix file should be described by a protocol."


class GEA_SM0003(_IncomingAny):
    rule_id = "GEA_SM0003"; level = "warning"; target = "SDRF/SampleNode"
    _node = "Sample Name"
    description = "A sample should be described by a protocol."


# ---------------- Assay incoming node type ----------------
class GEA_AN0006(GeaRule):
    rule_id = "GEA_AN0006"; level = "error"; target = "SDRF/ArrayNode"; only_type = "microarray"
    description = "For an array assay the incoming nodes must be 'Labeled Extract' nodes only."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        g = _graph(sub)
        if not g.has("Assay Name"):
            return []
        prev = g.prev_of("Assay Name")
        return [] if prev == "Labeled Extract Name" else [self.result(message=f"{self.description} (incoming: '{prev}')")]


class GEA_AN0008(GeaRule):
    rule_id = "GEA_AN0008"; level = "warning"; target = "SDRF/ArrayNode"; only_type = "microarray"
    description = ("An assay must be connected to a number of distinctly labeled extracts "
                   "that equals a number of channels.")

    def validate(self, sub, context):
        if not sub.sdrf or not sub.idf:
            return []
        ch = sub.idf.number_of_channel.lower()
        want = 2 if "dual" in ch else (1 if "single" in ch else None)
        if want is None:
            return []
        ai = sub.sdrf.col_indices("Assay Name")
        li = sub.sdrf.col_indices("Label")
        if not ai or not li:
            return []
        # assay ごとに dye トークン数。"Cy3 and Cy5" のような結合表記は分割して数える
        # （行分割・結合表記の両規約に対応）。
        by_assay = {}
        for row in sub.sdrf.rows:
            a = (row[ai[0]] if ai[0] < len(row) else "").strip()
            lab = (row[li[0]] if li[0] < len(row) else "").strip()
            if not a:
                continue
            by_assay.setdefault(a, set())
            for tok in re.split(r"\s+and\s+|\s*[,/]\s*", lab):
                tok = tok.strip()
                if tok:
                    by_assay[a].add(tok)
        bad = [a for a, labs in by_assay.items() if labs and len(labs) != want]
        return [self.result(message=f"{self.description} (channels={want}; mismatched assays: {len(bad)})")] if bad else []


# ---------------- Library info（HTS）----------------
class GEA_LC0001(GeaRule):
    rule_id = "GEA_LC0001"; level = "error"; target = "SDRF/LibraryConstructionAttribute"; only_type = "sequencing"
    description = "Library source, layout, selection and strategy must be specified for the ENA library info."

    _cols = ("Comment[LIBRARY_SOURCE]", "Comment[LIBRARY_LAYOUT]",
             "Comment[LIBRARY_SELECTION]", "Comment[LIBRARY_STRATEGY]")

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        miss = []
        for c in self._cols:
            idxs = sub.sdrf.col_indices(c)
            if not idxs:
                miss.append(c)
                continue
            # 1 行でも空があれば不足扱い
            if any(_empty(row[idxs[0]] if idxs[0] < len(row) else "") for row in sub.sdrf.rows):
                miss.append(c)
        return [self.result(message=f"{self.description} (missing/empty: {', '.join(miss)})")] if miss else []


# ---------------- Factor value が変動するか ----------------
class GEA_FV0004(GeaRule):
    rule_id = "GEA_FV0004"; level = "error"; target = "SDRF/FactorValueAttribute"
    description = "Values of an experimental variable must vary (for compound+dose at least one must vary)."

    def validate(self, sub, context):
        if not sub.sdrf or len(sub.sdrf.rows) < 2:
            return []
        fv_cols = [h for h in sub.sdrf.header if re.fullmatch(r"Factor Value\[.+\]", h)]
        if not fv_cols:
            return []
        varies = False
        for h in fv_cols:
            idxs = sub.sdrf.col_indices(h)
            vals = {(row[idxs[0]].strip() if idxs[0] < len(row) else "") for row in sub.sdrf.rows}
            if len(vals) > 1:
                varies = True
                break
        return [] if varies else [self.result(message=f"{self.description} ({', '.join(fv_cols)})")]


# ---------------- Array Design File 必須（microarray）----------------
class GEA_G0011(GeaRule):
    rule_id = "GEA_G0011"; level = "error"; target = "IDF/General"; only_type = "microarray"
    description = "Array Design File (or Array Design REF) is required for micro-array submissions."

    def validate(self, sub, context):
        if not sub.idf:
            return []
        idf_ad = any(not _empty(v) for v in sub.idf.get("Comment[Array Design REF]"))
        sdrf_ad = False
        if sub.sdrf:
            sdrf_ad = any(not _empty(v) for v in sub.sdrf.values("Array Design REF"))
        return [] if (idf_ad or sdrf_ad) else [self.result()]


# ---------------- 属性名（attribute should have name）----------------
class _EmptyBracket(GeaRule):
    """ヘッダに空カテゴリ（例 Characteristics[]）が無いか。"""
    _prefix = None
    target = "SDRF"

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        bad = [h for h in sub.sdrf.header if re.fullmatch(re.escape(self._prefix) + r"\[\s*\]", h)]
        return [self.result(message=f"{self.description} ({len(bad)})")] if bad else []


class GEA_CA0001(_EmptyBracket):
    rule_id = "GEA_CA0001"; level = "warning"; target = "SDRF/CharacteristicAttribute"; _prefix = "Characteristics"
    description = "A characteristic attribute should have name specified."


class GEA_PV0001(_EmptyBracket):
    rule_id = "GEA_PV0001"; level = "warning"; target = "SDRF/ParameterValueAttribute"; _prefix = "Parameter Value"
    description = "A parameter value attribute should have a name specified."


class GEA_UA0001(_EmptyBracket):
    rule_id = "GEA_UA0001"; level = "warning"; target = "SDRF/UnitAttribute"; _prefix = "Unit"
    description = "A unit attribute should have name specified."


class GEA_FV0001(_EmptyBracket):
    rule_id = "GEA_FV0001"; level = "warning"; target = "SDRF/FactorValueAttribute"; _prefix = "Factor Value"
    description = "An experimental variable attribute should have a name specified."


class _ColPresentButEmpty(GeaRule):
    """value 列が存在するが全行空（属性が名前無しで置かれている）。"""
    _col = None
    target = "SDRF"

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        return [self.result()] if _all_empty(sub.sdrf, self._col) else []


class GEA_L0001(_ColPresentButEmpty):
    rule_id = "GEA_L0001"; level = "warning"; target = "SDRF/LabelNode"; only_type = "microarray"; _col = "Label"
    description = "A label attribute should have name specified."


class GEA_MT0001(_ColPresentButEmpty):
    rule_id = "GEA_MT0001"; level = "warning"; target = "SDRF/MaterialTypeAttribute"; _col = "Material Type"
    description = "A material type attribute should have a name specified."


class GEA_SC0001(_ColPresentButEmpty):
    rule_id = "GEA_SC0001"; level = "warning"; target = "SDRF/ScanNode"; _col = "Scan Name"
    description = "A scan should have a name specified."


class GEA_NN0001(_ColPresentButEmpty):
    rule_id = "GEA_NN0001"; level = "warning"; target = "SDRF/NormalizationNode"; _col = "Normalization Name"
    description = "A normalization node should have a name."


# ---------------- Sample node ----------------
class GEA_SM0001(GeaRule):
    rule_id = "GEA_SM0001"; level = "error"; target = "SDRF/SampleNode"
    description = "A sample must have name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        idxs = sub.sdrf.col_indices("Sample Name")
        if not idxs:
            return []  # Sample Name 列は任意
        for row in sub.sdrf.rows:
            if _empty(row[idxs[0]] if idxs[0] < len(row) else ""):
                return [self.result()]
        return []


# ---------------- Data node name（列があるのに全行空＝名前なし）----------------
class GEA_ADN0001(_ColPresentButEmpty):
    rule_id = "GEA_ADN0001"; level = "error"; target = "SDRF/ArrayDataNode"; _col = "Array Data File"
    description = "An array data node (raw data file) must have a name."


class GEA_ADMN0001(_ColPresentButEmpty):
    rule_id = "GEA_ADMN0001"; level = "error"; target = "SDRF/ArrayDataMatrixNode"; _col = "Array Data Matrix File"
    description = "An array data matrix file must have name specified."


class GEA_DADN0001(_ColPresentButEmpty):
    rule_id = "GEA_DADN0001"; level = "error"; target = "SDRF/DerivedArrayDataNode"; _col = "Derived Array Data File"
    description = "A derived array data node (processed data file) must have name specified."


class GEA_DADMN0001(_ColPresentButEmpty):
    rule_id = "GEA_DADMN0001"; level = "error"; target = "SDRF/DerivedArrayDataMatrixNode"; _col = "Derived Array Data Matrix File"
    description = "A derived array data matrix file must have a name specified."


# ---------------- Source に growth/treatment/sample collection protocol ----------------
class GEA_SR0008(GeaRule):
    rule_id = "GEA_SR0008"; level = "error"; target = "SDRF/SourceNode"
    description = "A growth, treatment or sample collection protocol must be included."
    _accept = ("growth protocol", "treatment protocol", "sample collection protocol")

    def validate(self, sub, context):
        if not sub.idf:
            return []
        have = {t.strip() for t in sub.idf.get("Protocol Type") if t.strip()}
        return [] if (set(self._accept) & have) else [self.result()]


# ---------------- Protocol node ----------------
class GEA_PN0001(GeaRule):
    rule_id = "GEA_PN0001"; level = "error"; target = "SDRF/ProtocolNode"
    description = "A protocol must have a name specified."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        idxs = sub.sdrf.col_indices("Protocol REF")
        # 全行空の Protocol REF 列（プロトコール未参照の空列）を検出
        empties = 0
        for i in idxs:
            if all(_empty(row[i] if i < len(row) else "") for row in sub.sdrf.rows):
                empties += 1
        return [self.result(message=f"{self.description} ({empties} empty Protocol REF column(s))")] if empties else []


class GEA_PN0003(GeaRule):
    rule_id = "GEA_PN0003"; level = "error"; target = "SDRF/ProtocolNode"
    description = "A protocol's date must be in 'YYYY-MM-DD' format."

    def validate(self, sub, context):
        if not sub.sdrf:
            return []
        out = []
        for i in sub.sdrf.col_indices("Date"):
            for row in sub.sdrf.rows:
                v = (row[i] if i < len(row) else "").strip()
                if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                    out.append(self.result(message=f"{self.description} ('{v}')"))
                    break
        return out
