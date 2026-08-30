"""バリデータ共通のレポート出力（TSV summary/details ＋ --json）。

bp/dra/mb/gea が共有する。各 app は薄いラッパで TITLE・input ラベル・中間キー等の差分だけ渡す。
ddbj/bs は出力形態が異なるため対象外。
"""
import json
from pathlib import Path


def counts(results):
    c = {"error": 0, "warning": 0}
    for r in results:
        lvl = r.get("level", "error")
        c[lvl] = c.get(lvl, 0) + 1
    return c


def build_summary(title, results, fname, version, when, elapsed, input_label="Input", extra_lines=None):
    """サマリ本文。extra_lines は input 行と Validity 行の間に挿入する追加行のリスト。"""
    c = counts(results)
    validity = "false" if c.get("error", 0) else "true"
    body = (
        f"=== {title} Validation Summary ===\n"
        f"Validation Date: {when}\nProcess Time: {elapsed}\nVersion: {version}\n"
        f"{input_label}: {fname}\n"
    )
    for ln in (extra_lines or []):
        body += ln + "\n"
    body += f"Validity: {validity}\nError: {c.get('error',0)}   Warning: {c.get('warning',0)}\n"
    return body


def build_details(title, results, fname, version, when, elapsed, input_label="Input", middle_key="target"):
    """詳細本文。1 行 = rule_id:{中間キーの値 or '-'}:message。中間キーは app により sample/target。"""
    lines = [f"=== {title} Validation Details ===",
             f"Validation Date: {when}", f"Version: {version}", f"{input_label}: {fname}", ""]
    for r in results:
        lines.append(f"{r['rule_id']}:{r.get(middle_key) or '-'}:{r.get('message','')}")
    return "\n".join(lines) + "\n"


def write_text_reports(summary, details, out_dir):
    d = Path(out_dir) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "validation_report_summary.txt").write_text(summary, encoding="utf-8")
    (d / "validation_report_details.txt").write_text(details, encoding="utf-8")


def write_json_report(results, out_dir, fname, version, stats_key="input", include_object=False):
    """JSON レポート。stats_key は "file"/"input"、include_object 時は messages に object(=sample) を含める。"""
    c = counts(results)

    def _msg(r):
        m = {"id": r["rule_id"], "level": r.get("level", "error"),
             "message": r.get("message", ""), "target": r.get("target", "")}
        if include_object:
            m["object"] = r.get("sample")
        m["external"] = r.get("external", False)
        # 行位置（magetab: mb/gea の SDRF 行単位メッセージ）。存在時のみ付与し、
        # 登録システムの JS が該当行（line）・assay で位置特定/ハイライトできるようにする。
        # target は IDF / SDRF（＝ファイル種別）を表す。
        for k in ("line", "assay"):
            if r.get(k) is not None:
                m[k] = r[k]
        return m

    payload = {
        "version": version,
        "validity": c.get("error", 0) == 0,
        "stats": {stats_key: fname, "error": c.get("error", 0), "warning": c.get("warning", 0)},
        "messages": [_msg(r) for r in results],
    }
    d = Path(out_dir) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / "validation_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
