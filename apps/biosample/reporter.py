"""BioSample 検証結果のレポート出力（ddbj reporter と同様の体裁、独立実装）。

- テキスト: reports/validation_report.txt（常時）。
- JSON: reports/validation_report.json（`-j` 指定時）。現行 web validator の result.json 互換の
  「素の（flat な）」構造（validity / stats / messages[]）。付帯情報（grouped_messages）は含めない
  — グルーピングは表示側（ブラウザ JS）が行う。
biosample はエントリ数が多くても 1000〜2000 程度のため、ddbj のような details/summary 分割はしない。
"""
import json
from collections import defaultdict
from pathlib import Path

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}
# ルール解説ページ（現行 validator の reference と同じアンカー規約）
_DOC_BASE = "https://www.ddbj.nig.ac.jp/biosample/validation-e.html#"


def _fmt(r):
    sample = r.get("sample") or "-"
    return f"{r['rule_id']}:{r['level'].upper()}:{r.get('target','')}:{sample}: {r['message']}"


def _sorted(results):
    return sorted(results, key=lambda x: (_LEVEL_ORDER.get(x["level"], 9), x["rule_id"]))


def write_reports(results, out_dir, input_name):
    """結果を標準出力＋ <out_dir>/reports/validation_report.txt に出力。戻り値: レベル別件数 dict。"""
    counts = defaultdict(int)
    for r in results:
        counts[r["level"]] += 1

    lines = [f"# BioSample validation report: {input_name}", ""]
    for r in _sorted(results):
        lines.append(_fmt(r))
    if not results:
        lines.append("No findings.")
    body = "\n".join(lines) + "\n"

    print(body)

    if out_dir:
        reports = Path(out_dir) / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "validation_report.txt").write_text(body, encoding="utf-8")

    return dict(counts)


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
