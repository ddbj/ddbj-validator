"""BioSample 検証結果のレポート出力（ddbj reporter と同様の体裁、独立実装）。"""
from collections import defaultdict
from pathlib import Path

_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}


def _fmt(r):
    sample = r.get("sample") or "-"
    return f"{r['rule_id']}:{r['level'].upper()}:{r.get('target','')}:{sample}: {r['message']}"


def write_reports(results, out_dir, input_name):
    """結果を標準出力＋ <out_dir>/reports/ に出力。戻り値: レベル別件数 dict。"""
    counts = defaultdict(int)
    for r in results:
        counts[r["level"]] += 1

    lines = [f"# BioSample validation report: {input_name}", ""]
    for r in sorted(results, key=lambda x: (_LEVEL_ORDER.get(x["level"], 9), x["rule_id"])):
        lines.append(_fmt(r))
    if not results:
        lines.append("No findings.")
    body = "\n".join(lines) + "\n"

    print(body)

    if out_dir:
        reports = Path(out_dir) / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "biosample_validation_report.txt").write_text(body, encoding="utf-8")

    return dict(counts)
