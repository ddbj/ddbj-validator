"""BioSample 検証結果のレポート出力（ddbj reporter と同様の体裁、独立実装）。検証は SSUB 単位。

出力（CLI の -j で切替）:
- 既定（テキスト）: reports/validation_report_summary.txt（info ヘッダ＋レベル別集計）
  ＋ validation_report_details.txt（サンプル別）。summary は標準出力にも表示する。
- JSON（`-j`）: reports/validation_report.json（web validator の result.json 互換 flat 構造）。
- autofix があれば reports/autofix_confirmation_summary.txt を -j の有無に関わらず出力する。
サンプル数は "(N sample(s))" 表記。summary/details とも先頭に info ヘッダ（Validation Date/Process Time/Data/Version）。
"""
import json
from collections import OrderedDict
from pathlib import Path

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}
_LEVEL_SECTIONS = ["info", "warning", "error"]  # 表示順（info→warning→error）
# ルール解説ページ（現行 validator の reference と同じアンカー規約）
_DOC_BASE = "https://www.ddbj.nig.ac.jp/biosample/validation-e.html#"


def _sorted(results):
    return sorted(results, key=lambda x: (_LEVEL_ORDER.get(x["level"], 9), x["rule_id"]))


def _sample_count_str(n):
    return f"{n} sample" if n == 1 else f"{n} samples"


def _info_header(kind, sample_count, input_name, package, version, when, elapsed):
    return [
        f"=== Validation {kind} ({_sample_count_str(sample_count)}) ===",
        f"Validation Date: {when}",
        f"Process Time: {elapsed} seconds",
        "Data: biosample",
        f"Version: {version}",
        "",
        f"File: {input_name}",
        f"Package: {package or '-'}",
        "",
    ]


def _by_level(results):
    by = {lv: [] for lv in _LEVEL_SECTIONS}
    for r in _sorted(results):
        by.setdefault(r["level"], []).append(r)
    return by


def build_summary(results, sample_count, input_name, package, version, when, elapsed):
    """summary 本文（info ヘッダ＋レベル別のルール:メッセージ、同一行は重複排除）。標準出力/ファイル共通。"""
    lines = _info_header("Summary", sample_count, input_name, package, version, when, elapsed)
    by = _by_level(results)
    for lv in _LEVEL_SECTIONS:
        rs = by.get(lv) or []
        if not rs:
            continue
        lines.append(f"[ {lv.upper()} ]")
        seen = set()
        for r in rs:
            line = f"{r['rule_id']}:{r['message']}"
            if line in seen:
                continue
            seen.add(line)
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_details(results, records, sample_count, input_name, package, version, when, elapsed):
    """details 本文（サンプル別）。行: rule_id:(SAMD があれば):sample_name:message。"""
    idmap = {}
    for rec in records or []:
        idmap[rec.sample_id] = (rec.accession, rec.sample_name)
    lines = _info_header("Details", sample_count, input_name, package, version, when, elapsed)
    by = _by_level(results)
    for lv in _LEVEL_SECTIONS:
        rs = by.get(lv) or []
        if not rs:
            continue
        lines.append(f"[ {lv.upper()} ]")
        for r in rs:
            sid = r.get("sample")
            acc, name = idmap.get(sid, (None, sid))
            parts = [r["rule_id"]]
            if acc:
                parts.append(acc)          # あれば SAMD アクセッション
            parts.append(name or sid or "-")  # sample name
            parts.append(r["message"].replace("\n", " "))
            lines.append(":".join(parts))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_autofix_lines(results):
    """autofix 提案を (rule_id, old, new) で集約し 'N sample(s): 'old' -> 'new' [Rule: X]' の行リストを返す。"""
    agg = OrderedDict()
    for r in results:
        if not r.get("autofix"):
            continue
        old = r.get("old_value") or ""
        new = r.get("new_value")
        if new is None and r.get("new_taxid"):
            new = f"taxonomy_id={r.get('new_taxid')}"
        key = (r["rule_id"], old, new)
        agg.setdefault(key, set()).add(r.get("sample"))
    return [f"{_sample_count_str(len(s))}: '{old}' -> '{new}' [Rule: {rid}]"
            for (rid, old, new), s in agg.items()]


def write_text_reports(summary_text, details_text, out_dir):
    """summary/details テキストをファイルへ書き出す。"""
    if not out_dir:
        return
    reports = Path(out_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "validation_report_summary.txt").write_text(summary_text, encoding="utf-8")
    (reports / "validation_report_details.txt").write_text(details_text, encoding="utf-8")


def write_autofix_confirmation(autofix_lines, out_dir):
    """autofix の内容を reports/autofix_confirmation_summary.txt に出力（-j の有無に関わらず）。"""
    if not out_dir or not autofix_lines:
        return
    reports = Path(out_dir) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    body = "[ Auto-Fix ]\n" + "\n".join(autofix_lines) + "\n"
    (reports / "autofix_confirmation_summary.txt").write_text(body, encoding="utf-8")


def _annotation(r):
    """result dict から表示用 annotation 配列を構築（Sample name ＋ autofix 提案）。"""
    anno = [{"key": "Sample name", "value": r.get("sample") or ""}]
    attr = r.get("attribute")
    if attr:
        anno.append({"key": "Attribute", "value": attr})
        if r.get("old_value") is not None:
            anno.append({"key": "Attribute value", "value": r.get("old_value")})
    # autofix 提案（属性値置換 / organism 補正）
    if r.get("autofix") and r.get("new_value") is not None:
        target_key = "Attribute value" if attr else ("organism" if r.get("kind") == "organism" else "value")
        anno.append({
            "key": "Suggested value",
            "suggested_value": [r.get("new_value")],
            "target_key": target_key,
            "is_auto_annotation": True,
        })
    # organism 補正で taxonomy_id も補完する場合
    if r.get("new_taxid"):
        anno.append({
            "key": "Suggested value (taxonomy_id)",
            "suggested_value": [str(r.get("new_taxid"))],
            "target_key": "taxonomy_id",
            "is_auto_annotation": True,
        })
    return anno


def _error_obj(r, source):
    """result dict を web validator 互換の error_obj へ写像。"""
    return {
        "id": r["rule_id"],
        "message": r["message"],
        "reference": _DOC_BASE + r["rule_id"],
        "level": r["level"],
        "external": bool(r.get("external", False)),
        "method": "biosample",
        "object": "BioSample",
        "source": source,
        "annotation": _annotation(r),
    }


def _stats(results):
    error_count = sum(1 for r in results if r["level"] == "error")
    warning_count = sum(1 for r in results if r["level"] == "warning")
    ext_err = sum(1 for r in results if r["level"] == "error" and r.get("external"))
    ext_warn = sum(1 for r in results if r["level"] == "warning" and r.get("external"))
    return {
        "error_count": error_count,
        "warning_count": warning_count,
        "error_type_count": {
            "common_error": error_count - ext_err,
            "common_warning": warning_count - ext_warn,
            "external_error": ext_err,
            "external_warning": ext_warn,
        },
        # biosample 単一 filetype。autofix 提案が1件でもあれば自動補正可
        "autocorrect": {"biosample": any(r.get("autofix") for r in results)},
    }


def build_result_json(results, input_name, version="unknown"):
    """web validator の result.json 互換（flat）な結果オブジェクトを返す。"""
    stats = _stats(results)
    return {
        "version": version,
        "validity": stats["error_count"] == 0,  # warning は validity を落とさない（ddbj と同じ）
        "stats": stats,
        "messages": [_error_obj(r, input_name) for r in _sorted(results)],
    }


def write_json_report(results, out_dir, input_name, version="unknown"):
    """<out_dir>/reports/validation_report.json に result.json 互換の JSON を出力。戻り値: 結果 dict。"""
    result = build_result_json(results, input_name, version)
    if out_dir:
        reports = Path(out_dir) / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "validation_report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
