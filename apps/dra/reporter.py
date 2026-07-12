"""DRA validator のレポート出力（MetaboBank / GEA と同様の見せ方）。

- ヘッダは object type ごとにファイル名＋オブジェクト件数（Submission/Experiment/Run、Analysis はある時だけ）。
- ERROR / WARNING セクションに分割。各セクション内は SUBMISSION→EXPERIMENT→RUN→ANALYSIS の順に object type で
  グルーピング。
- 各行は `{rule_id}:{OBJECT}:{accession or alias}:{message}`（object は accession/alias/target から導出）。
- summary は (rule_id, object) ごとに件数集約（`{first} etc ({N})`、メッセージが行ごとに違えば末尾に ' etc'）。
  details は全件展開。
共通の counts / write_text_reports / write_json_report は common/reporter を利用。
"""
from collections import OrderedDict

from common import reporter as _r

_TITLE = "DRA"
_DATA = "DRA"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports

# ヘッダの表示順とラベル
_ROLE_ROWS = [("submission", "Submission"), ("experiment", "Experiment"),
              ("run", "Run"), ("analysis", "Analysis")]
_ROLE_ATTR = {"experiment": "experiments", "run": "runs", "analysis": "analyses"}
# object type のグルーピング順
_OBJ_ORDER = ["SUBMISSION", "EXPERIMENT", "RUN", "ANALYSIS", "OTHER"]


def _obj_count(submission, role):
    if role == "submission":
        return 1 if submission.submission else 0
    return len(getattr(submission, _ROLE_ATTR[role]))


def _header_lines(submission):
    """object type ごとの「Label: file(s) (件数)」行。件数 0（＝提出なし）は省く（Analysis 対応）。"""
    out = []
    for role, label in _ROLE_ROWS:
        cnt = _obj_count(submission, role)
        files = submission.role_files.get(role, [])
        if cnt == 0 and not files:
            continue
        out.append(f"{label}: {', '.join(files) if files else '-'} ({cnt})")
    return out


def _obj_type(r):
    """結果の対象 object type を accession/alias/target から導出。"""
    s = (r.get("sample") or "")
    su = s.upper()
    if su.startswith("DRA"):
        return "SUBMISSION"
    if su.startswith("DRX"):
        return "EXPERIMENT"
    if su.startswith("DRR"):
        return "RUN"
    if su.startswith("DRZ"):
        return "ANALYSIS"
    sl = s.lower()
    for key, obj in (("_submission", "SUBMISSION"), ("_experiment", "EXPERIMENT"),
                     ("_run", "RUN"), ("_analysis", "ANALYSIS")):
        if key in sl:
            return obj
    t = (r.get("target") or "").upper()
    for o in ("SUBMISSION", "EXPERIMENT", "RUN", "ANALYSIS"):
        if t.startswith(o):
            return o
    return "OTHER"


def _fmt(r):
    """`{rule_id}:{OBJECT}:{accession or alias}:{message}`。"""
    return f"{r['rule_id']}:{_obj_type(r)}:{r.get('sample') or '-'}:{r.get('message','')}"


def _section(results, is_err):
    """指定レベルの行を object type 順にグルーピングして返す。"""
    picked = [r for r in results if (r.get("level") == "error") == is_err]
    out = []
    for obj in _OBJ_ORDER:
        out += [_fmt(r) for r in picked if _obj_type(r) == obj]
    return out


def _agg_line(rid, obj, rs):
    """(rule_id, object) の集約 1 行。N>1 は `{first} etc ({N})`、メッセージが行ごとに違えば末尾に ' etc'。"""
    n = len(rs)
    sample0 = rs[0].get("sample") or "-"
    msg0 = rs[0].get("message", "")
    if n == 1:
        return f"{rid}:{obj}:{sample0}:{msg0}"
    if len({r.get("message", "") for r in rs}) > 1:   # メッセージが揃わない（acc 等が行ごとに違う）
        msg0 = (msg0[:-1] + " etc)") if msg0.endswith(")") else f"{msg0} etc"
    return f"{rid}:{obj}:{sample0} etc ({n}):{msg0}"


def _detail_body(results):
    """details 本文（全件展開）。"""
    lines = []
    errs, wars = _section(results, True), _section(results, False)
    if errs:
        lines.append("[ ERROR ]"); lines += errs; lines.append("")
    if wars:
        lines.append("[ WARNING ]"); lines += wars
    return lines


def _summary_body(results):
    """summary 本文（(rule_id, object) 件数集約）。"""
    lines = []
    for is_err, hdr in ((True, "[ ERROR ]"), (False, "[ WARNING ]")):
        picked = [r for r in results if (r.get("level") == "error") == is_err]
        if not picked:
            continue
        section = []
        for obj in _OBJ_ORDER:
            groups = OrderedDict()
            for r in picked:
                if _obj_type(r) == obj:
                    groups.setdefault(r["rule_id"], []).append(r)
            for rid, rs in groups.items():
                section.append(_agg_line(rid, obj, rs))
        lines.append(hdr); lines += section; lines.append("")
    return lines


def _head(title, submission, version, when, elapsed, with_time):
    lines = [f"=== {_TITLE} Validation {title} ===", f"Validation Date: {when}"]
    if with_time:
        lines.append(f"Process Time: {elapsed}")
    lines += [f"Data: {_DATA}", f"Version: {version}", ""]
    lines += _header_lines(submission)
    lines.append("")
    return lines


def build_summary(results, submission, version, when, elapsed):
    c = _r.counts(results)
    lines = _head("Summary", submission, version, when, elapsed, with_time=True)
    lines += [f"Error: {c.get('error',0)}   Warning: {c.get('warning',0)}", ""]
    lines += _summary_body(results)
    return "\n".join(lines).rstrip("\n") + "\n"


def build_details(results, submission, version, when, elapsed):
    lines = _head("Details", submission, version, when, elapsed, with_time=False)
    lines += _detail_body(results)
    return "\n".join(lines).rstrip("\n") + "\n"


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="input", include_object=True)
