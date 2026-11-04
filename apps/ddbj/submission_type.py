"""submission type（WGS / TSA / EST など）の判定（2026-11-04）。

推定はしない。COMMON の DATATYPE/type と DIVISION/division に書かれた申告から決める
（context.analyze_records と同じ読み方）。COMMON だけで決まるので --common-only で返せる。
KEYWORD から逆引きした type が申告と合わないときは candidates に入れる（ANN0640 と同じ表）。
"""

# submission type として扱う DIVISION（context._DIVISION_FLAGS と同じ集合）
TYPE_DIVISIONS = {"CON", "ENV", "EST", "GSS", "HTC", "HTG", "STS", "SYN", "TSA"}

# TPA と組み合わせて複合型にする DATATYPE
_TPA_COMPOSABLE = ("WGS", "TSA", "TLS")


def _common_values(common_rec, feature_type, qualifier):
    vals = []
    if common_rec is None:
        return vals
    for feat in common_rec.features:
        if feat.type == feature_type:
            for v in feat.qualifiers.get(qualifier, []):
                v = v.strip()
                if v and v not in vals:
                    vals.append(v)
    return vals


def _compose(datatypes, divisions):
    """申告から submission type を 1 つ決める。DATATYPE を優先し、無ければ type 扱いの DIVISION。"""
    dts = list(datatypes)
    if "TPA" in dts:
        # DATATYPE を TPA と WGS のように分けて書いた場合は複合型にまとめる
        for base in _TPA_COMPOSABLE:
            if base in dts:
                dts = [d for d in dts if d not in ("TPA", base)] + [f"TPA-{base}"]
    if dts:
        return ",".join(sorted(set(dts)))
    divs = sorted({d for d in divisions if d in TYPE_DIVISIONS})
    if divs:
        return ",".join(divs)
    return None


def _keyword_candidates(keywords, declared, type_rules):
    """KEYWORD から逆引きした type のうち、申告（継承込み）に含まれないもの。"""
    expanded = set(declared)
    for t in declared:
        expanded.update(type_rules.get(t, {}).get("inherits", []))
    implied = set()
    for name, rule in type_rules.items():
        for group in rule.get("required_keywords", []):
            if any(kw in group for kw in keywords):
                implied.add(name)
                break
    if implied & expanded:
        # 申告と合う keyword がある（TPA 系の keyword が複数の TPA 型に掛かる場合など）
        return []
    return sorted(implied)


def detect_submission_type(records, ddbj_dict):
    """records（COMMON を含む）から submission type を返す。

    戻り値: {"submission_type": "WGS" | None, "datatypes": [...], "divisions": [...],
             "keywords": [...], "candidates": [...]}
    """
    common_rec = records.get("COMMON") if records else None
    datatypes = [v.upper() for v in _common_values(common_rec, "DATATYPE", "type")]
    divisions = [v.upper() for v in _common_values(common_rec, "DIVISION", "division")]
    keywords = _common_values(common_rec, "KEYWORD", "keyword")
    type_rules = (ddbj_dict or {}).get("submission_types", {})
    declared = set(datatypes) | {d for d in divisions if d in TYPE_DIVISIONS}
    return {
        "submission_type": _compose(datatypes, divisions),
        "datatypes": datatypes,
        "divisions": divisions,
        "keywords": keywords,
        "candidates": _keyword_candidates(keywords, declared, type_rules),
    }
