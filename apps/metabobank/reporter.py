"""MetaboBank validator のレポート出力（骨格は common/magetab/reporter に集約）。

MB 固有の差分のみここで定義する:
- 行単位判定: assay を持つ行が SDRF 行単位。
- detail の行単位形式: `{rule_id}:{tag}:SDRF:line {n}:{assay}:{message}`（target 無し）。
- summary の SDRF 行集約: samd を持つ行は SAMD を除いたメッセージで集約し、SAMD の違いを "first etc" に吸収。
"""
from collections import OrderedDict

from common import reporter as _r
from common.magetab import reporter as _mr
from apps.metabobank.rules.base import annotation_pattern as _annotation_pattern

_TITLE = "MetaboBank"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports


def _is_row_level(r):
    """SDRF 行単位のメッセージ（assay を持つ）か。"""
    return "assay" in r


def _row_fmt(r):
    """MB の行単位 detail 行（SDRF:line prefix・target 無し）。
    行番号:assay name（assay name だけだとユニークでない場合があるため行番号を併記）。"""
    return (f"{r['rule_id']}:{_mr.tag(r)}:SDRF:line {r.get('line', '-')}:"
            f"{r.get('assay') or '-'}:{r.get('message','')}")


def _row_summary(results, is_err):
    """MB の SDRF 行単位 summary 集約。
    samd を持つ行（SR0021/SR0023 等）は SAMD を除いたメッセージで集約し、SAMD の違いを "first etc" に吸収
    （sdrf 行数 x samd 数 x 属性数 で膨らむのを 1 行にまとめる）。samd 無しは message で集約（従来）。"""
    groups = OrderedDict()
    for r in results:
        if not (_is_row_level(r) and (r.get("level") == "error") == is_err):
            continue
        rid, tag, msg = r["rule_id"], _mr.tag(r), r.get("message", "")
        samd = r.get("samd")
        key = (rid, tag, msg.replace(samd, "<samd>") if samd else msg)
        g = groups.get(key)
        if g is None:
            g = {"rid": rid, "tag": tag, "msg": msg, "samd": samd, "n": 0}
            groups[key] = g
        g["n"] += 1
    out = []
    for g in groups.values():
        msg = g["msg"]
        if g["samd"] and g["n"] > 1:   # SAMD を「first etc」に（複数 SAMD をまとめた印）
            msg = msg.replace(g["samd"], f"{g['samd']} etc", 1)
        out.append(f"{g['rid']}:{g['tag']}:SDRF:{g['n']} lines:{msg}")
    return out


def build_summary(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    return _mr.build_summary(results, fname, version, when, elapsed, app_title=_TITLE, data=_TITLE,
                             is_row_level=_is_row_level, row_summary=_row_summary,
                             sample_count=sample_count, sub_type=sub_type)


def build_details(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    return _mr.build_details(results, fname, version, when, elapsed, app_title=_TITLE, data=_TITLE,
                             is_row_level=_is_row_level, row_fmt=_row_fmt,
                             sample_count=sample_count, sub_type=sub_type)


# ルール解説ページ（BS の reference と同じアンカー規約）
_DOC_BASE = "https://www.ddbj.nig.ac.jp/metabobank/validation-e.html#"


def _kv(key, value):
    return {"key": key, "value": "" if value is None else str(value)}


def _sdrf_cell(r):
    """行単位の値の問題。Line / Assay Name / Column / Value（＋ rule 固有の列）。"""
    anno = [_kv("Line", r.get("line")),
            # assay が無い SDRF（Assay Name 列を持たない投稿）では Source Name を出す
            _kv("Assay Name" if r.get("assay") else "Source Name",
                r.get("assay") or r.get("source_name"))]
    if r.get("column") is not None:
        anno.append(_kv("Column", r.get("column")))
    if r.get("value") is not None:
        anno.append(_kv("Value", r.get("value")))
    # MB_SR0021 / 0022 / 0023: 参照 BioSample と、その属性値
    if r.get("samd"):
        anno.append(_kv("BioSample", r["samd"]))
    if r.get("bs_value") is not None:
        anno.append(_kv("BioSample value", r["bs_value"]))
    # autofix（MB_SR0030 の非 ASCII 正規化 / MB_SR0023 の値同期）は BS と同じ形
    if r.get("autofix") and r.get("new_value") is not None:
        anno.append({"key": "Suggested value", "suggested_value": [r["new_value"]],
                     "target_key": r.get("target_key") or "Value", "is_auto_annotation": True})
    return anno


def _sdrf_column(r):
    """列の有無・列全体の問題。Column（＋ Rows）。"""
    anno = []
    if r.get("column") is not None:
        anno.append(_kv("Column", r["column"]))
    if r.get("rows") is not None:
        anno.append(_kv("Rows", r["rows"]))
    return anno


def _idf_field(r):
    """IDF 項目の問題。Field / Value。"""
    anno = []
    if r.get("field") is not None:
        anno.append(_kv("Field", r["field"]))
    if r.get("value") is not None:
        anno.append(_kv("Value", r["value"]))
    if r.get("autofix") and r.get("new_value") is not None:
        anno.append({"key": "Suggested value", "suggested_value": [r["new_value"]],
                     "target_key": r.get("target_key") or "Value", "is_auto_annotation": True})
    return anno


def _idf_protocol(r):
    """submission type ごとの protocol 要件。Protocol Type / Parameter。"""
    anno = []
    if r.get("protocol_type") is not None:
        anno.append(_kv("Protocol Type", r["protocol_type"]))
    if r.get("param") is not None:
        anno.append(_kv("Parameter", r["param"]))
    return anno


def _idf_sdrf(r):
    """IDF↔SDRF の突合。どちらにだけあるかを示す。"""
    anno = []
    if r.get("idf_only") is not None:
        anno.append(_kv("IDF", r["idf_only"]))
    if r.get("sdrf_only") is not None:
        anno.append(_kv("SDRF", r["sdrf_only"]))
    return anno


_BUILDERS = {
    "sdrf_cell": _sdrf_cell,
    "sdrf_column": _sdrf_column,
    "idf_field": _idf_field,
    "idf_protocol": _idf_protocol,
    "idf_sdrf": _idf_sdrf,
    "general": lambda r: [],
}


def annotation(r):
    """result dict から表示用 annotation 配列を組む（rules/base.py の パターン表に従う）。"""
    return _BUILDERS[_annotation_pattern(r["rule_id"])](r)


def _json_extra(r):
    """JSON の 1 message に足すフィールド。

    - `message` は rule の固定文（`desc`）に差し替え、括弧書きの個別情報は annotation へ
    - 従来の 1 行形式は `detail` に残す（CLI とテキストレポートが使っている形）
    - `reference` は BS と同じアンカー規約
    `line` / `assay` は common 側が従来どおり載せる（既存の MB JS と BSM が使うため維持）。
    """
    extra = {"reference": _DOC_BASE + r["rule_id"], "annotation": annotation(r)}
    desc = r.get("desc")
    if desc:
        extra["message"] = desc
        detail = r.get("message") or ""
        if detail and detail != desc:
            extra["detail"] = detail
    return extra


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="input",
                                include_object=False, extra_fields=_json_extra)
