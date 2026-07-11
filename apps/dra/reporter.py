"""DRA validator のレポート出力。共通実体は common/reporter に委譲。"""
from common import reporter as _r

_TITLE = "DRA"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports


def build_summary(results, counts_obj, fname, version, when, elapsed):
    extra = [f"Experiments: {counts_obj.get('experiments',0)}   Runs: {counts_obj.get('runs',0)}   "
             f"Analyses: {counts_obj.get('analyses',0)}"]
    return _r.build_summary(_TITLE, results, fname, version, when, elapsed, extra_lines=extra)


def build_details(results, fname, version, when, elapsed):
    return _r.build_details(_TITLE, results, fname, version, when, elapsed, middle_key="sample")


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="input", include_object=True)
