"""NCBI API に届かなかったことの記録と表示（2026-11-05）。

NCBI に届かないのは検証エラーではないので、レポートに「届かなかった」と別に出し、
E2E ハーネスはその実行の不一致を mismatch に数えない（リリースを止めない）。
"""
import json

import pytest
import requests

import common.ncbi_api as ncbi_api
from apps.ddbj.reporter import ValidationReporter, NCBI_UNREACHABLE_MARK
from apps.biosample.reporter import write_json_report as bs_write_json_report


@pytest.fixture(autouse=True)
def _clear_failures(monkeypatch):
    monkeypatch.setattr(ncbi_api, "_failed_requests", [])
    monkeypatch.setattr(ncbi_api.time, "sleep", lambda s: None)


class _Resp:
    def __init__(self, status):
        self.status_code = status
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def test_failure_after_retries_is_recorded(monkeypatch):
    monkeypatch.setattr(ncbi_api.requests, "request", lambda *a, **k: _Resp(500))
    with pytest.raises(requests.HTTPError):
        ncbi_api.ncbi_request("GET", "https://eutils.example/esearch", retries=2)
    failures = ncbi_api.ncbi_failures()
    assert len(failures) == 1
    assert failures[0].startswith("https://eutils.example/esearch")


def test_success_after_retry_is_not_recorded(monkeypatch):
    seq = iter([_Resp(500), _Resp(200)])
    monkeypatch.setattr(ncbi_api.requests, "request", lambda *a, **k: next(seq))
    ncbi_api.ncbi_request("GET", "https://eutils.example/esearch", retries=2)
    assert ncbi_api.ncbi_failures() == []


def test_ddbj_report_header_and_json(tmp_path):
    rep = ValidationReporter(out_dir=tmp_path)
    rep.generate_report([], print_console=False, version="x", ncbi_failed=3)
    details = (tmp_path / "reports" / "validation_report_details.txt").read_text(encoding="utf-8")
    assert f"{NCBI_UNREACHABLE_MARK} (3 requests failed after retries)" in details

    out = rep.write_json_report([], version="x", ncbi_failed=1)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ncbi_unreachable"] == {"failed_requests": 1}
    assert payload["validity"] is True


def test_ddbj_report_without_failures_has_no_mark(tmp_path):
    rep = ValidationReporter(out_dir=tmp_path)
    rep.generate_report([], print_console=False, version="x")
    assert NCBI_UNREACHABLE_MARK not in (tmp_path / "reports" / "validation_report_details.txt").read_text(encoding="utf-8")
    payload = json.loads(rep.write_json_report([], version="x").read_text(encoding="utf-8"))
    assert "ncbi_unreachable" not in payload


def test_biosample_json(tmp_path):
    assert bs_write_json_report([], tmp_path, "in.xml", "x", ncbi_failed=2)["ncbi_unreachable"] == {"failed_requests": 2}
    assert "ncbi_unreachable" not in bs_write_json_report([], tmp_path, "in.xml", "x")
