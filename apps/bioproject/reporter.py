"""BioProject validator のレポート出力。共通実体は common/reporter に委譲。"""
from common import reporter as _r

_TITLE = "BioProject"

# 後方互換（既存 import 用）
_counts = _r.counts
write_text_reports = _r.write_text_reports


def build_summary(results, n_projects, fname, version, when, elapsed):
    return _r.build_summary(_TITLE, results, fname, version, when, elapsed,
                            input_label="File", extra_lines=[f"Projects: {n_projects}"])


def build_details(results, fname, version, when, elapsed):
    return _r.build_details(_TITLE, results, fname, version, when, elapsed,
                            input_label="File", middle_key="sample")


def write_json_report(results, out_dir, fname, version):
    return _r.write_json_report(results, out_dir, fname, version, stats_key="file", include_object=True)
