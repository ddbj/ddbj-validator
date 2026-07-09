"""BioProject validator のレポート出力（TSV サマリ/詳細 ＋ -j で JSON）。biosample と同形式。"""
import json
from pathlib import Path


def _counts(results):
    c = {"error": 0, "warning": 0}
    for r in results:
        c[r.get("level", "error")] = c.get(r.get("level", "error"), 0) + 1
    return c


def build_summary(results, n_projects, fname, version, when, elapsed):
    c = _counts(results)
    validity = "false" if c.get("error", 0) else "true"
    return (
        "=== BioProject Validation Summary ===\n"
        f"Validation Date: {when}\nProcess Time: {elapsed}\nVersion: {version}\n"
        f"File: {fname}\nProjects: {n_projects}\n"
        f"Validity: {validity}\nError: {c.get('error',0)}   Warning: {c.get('warning',0)}\n"
    )


def build_details(results, fname, version, when, elapsed):
    lines = ["=== BioProject Validation Details ===",
             f"Validation Date: {when}", f"Version: {version}", f"File: {fname}", ""]
    for r in results:
        lines.append(f"{r['rule_id']}:{r.get('sample') or '-'}:{r.get('message','')}")
    return "\n".join(lines) + "\n"


def write_text_reports(summary, details, out_dir):
    d = Path(out_dir) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "validation_report_summary.txt").write_text(summary, encoding="utf-8")
    (d / "validation_report_details.txt").write_text(details, encoding="utf-8")


def write_json_report(results, out_dir, fname, version):
    c = _counts(results)
    payload = {
        "version": version,
        "validity": c.get("error", 0) == 0,
        "stats": {"file": fname, "error": c.get("error", 0), "warning": c.get("warning", 0)},
        "messages": [
            {"id": r["rule_id"], "level": r.get("level", "error"),
             "message": r.get("message", ""), "target": r.get("target", ""),
             "object": r.get("sample"), "external": r.get("external", False)}
            for r in results
        ],
    }
    d = Path(out_dir) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "validation_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
