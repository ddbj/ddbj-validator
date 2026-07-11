"""MetaboBank validator のレポート出力。共通実体は common/reporter に委譲。"""
from common import reporter as _r

_TITLE = "MetaboBank"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports


def build_summary(results, fname, version, when, elapsed):
    return _r.build_summary(_TITLE, results, fname, version, when, elapsed)


def build_details(results, fname, version, when, elapsed):
    return _r.build_details(_TITLE, results, fname, version, when, elapsed, middle_key="target")


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="input", include_object=False)
