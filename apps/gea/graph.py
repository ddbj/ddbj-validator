"""SDRF の node フロー解析。

SDRF は左→右に Source → (Protocol REF)→ Sample/Extract → ... → Assay → Data File と流れる。
各 node 列（*Name / *Data File）に対し、直前 node 列との間にある Protocol REF 列が
その node への「incoming edge」に付随するプロトコルとなる。Protocol REF の値（P-GEAD… や一時 ID）を
IDF の Protocol Name→Type で引いて incoming protocol type 集合を得る。
"""
import re

NODE_NAMES = [
    "Source Name", "Sample Name", "Extract Name", "Labeled Extract Name",
    "Assay Name", "Scan Name", "Normalization Name",
    "Array Data File", "Derived Array Data File",
    "Array Data Matrix File", "Derived Array Data Matrix File",
]


def protocol_type_map(idf):
    """Protocol REF 値（Protocol Name / 一時 ID）→ Protocol Type。"""
    m = {}
    if not idf:
        return m
    for p in idf.protocols():
        nm = (p.get("Protocol Name") or "").strip()
        ty = (p.get("Protocol Type") or "").strip()
        if nm:
            m[nm] = ty
    return m


class _Node:
    def __init__(self, name, col, prev_name, incoming_types):
        self.name = name
        self.col = col
        self.prev_name = prev_name
        self.incoming_types = incoming_types


class Graph:
    def __init__(self, nodes):
        self.nodes = nodes  # header 出現順の _Node リスト

    def has(self, name):
        return any(n.name == name for n in self.nodes)

    def incoming(self, name):
        """name の（最初の）node への incoming protocol type 集合。node が無ければ None。"""
        for n in self.nodes:
            if n.name == name:
                return n.incoming_types
        return None

    def prev_of(self, name):
        for n in self.nodes:
            if n.name == name:
                return n.prev_name
        return None


def build_graph(sub):
    """SDRF から node フローの Graph を構築。"""
    sdrf = sub.sdrf
    ptmap = protocol_type_map(sub.idf)
    # node 列（header 出現順）
    node_cols = [(i, h) for i, h in enumerate(sdrf.header) if h in NODE_NAMES]
    pref_cols = sdrf.col_indices("Protocol REF")
    nodes = []
    prev_col = -1
    prev_name = None
    for col, name in node_cols:
        types = set()
        for i in pref_cols:
            if prev_col < i < col:
                for row in sdrf.rows:
                    v = (row[i] if i < len(row) else "").strip()
                    t = ptmap.get(v)
                    if t:
                        types.add(t)
        nodes.append(_Node(name, col, prev_name, types))
        prev_col = col
        prev_name = name
    return Graph(nodes)
