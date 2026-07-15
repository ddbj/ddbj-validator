"""GEA validator のレポート出力（骨格は common/magetab/reporter に集約）。

GEA 固有の差分のみここで定義する:
- 行単位判定: line または assay を持つ行が SDRF 行単位。
- detail の行単位形式: `{rule_id}:{tag}:line {n}:{assay}:{target}:{message}`。
- summary の SDRF 行集約: (rule_id, tag, message) ごとに "N lines"。
"""
from collections import OrderedDict

from common import reporter as _r
from common.magetab import reporter as _mr

_TITLE = "GEA"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports


def _is_row_level(r):
    """SDRF 行単位のメッセージ（line/assay を持つ）か。"""
    return "line" in r or "assay" in r


def _row_fmt(r):
    """GEA の行単位 detail 行（target を含む・SDRF prefix 無し）。"""
    return (f"{r['rule_id']}:{_mr.tag(r)}:line {r.get('line', '-')}:{r.get('assay') or '-'}:"
            f"{r.get('target') or '-'}:{r.get('message','')}")


def _row_summary(results, is_err):
    """GEA の SDRF 行単位 summary: (rule_id, tag, message) ごとに N lines 集約。"""
    groups = OrderedDict()
    for r in results:
        if _is_row_level(r) and (r.get("level") == "error") == is_err:
            key = (r["rule_id"], _mr.tag(r), r.get("message", ""))
            groups[key] = groups.get(key, 0) + 1
    return [f"{rid}:{tag}:SDRF:{n} lines:{msg}" for (rid, tag, msg), n in groups.items()]


def build_summary(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    return _mr.build_summary(results, fname, version, when, elapsed, app_title=_TITLE, data=_TITLE,
                             is_row_level=_is_row_level, row_summary=_row_summary,
                             sample_count=sample_count, sub_type=sub_type)


def build_details(results, fname, version, when, elapsed, sample_count=None, sub_type=None):
    return _mr.build_details(results, fname, version, when, elapsed, app_title=_TITLE, data=_TITLE,
                             is_row_level=_is_row_level, row_fmt=_row_fmt,
                             sample_count=sample_count, sub_type=sub_type)


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="input", include_object=False)
