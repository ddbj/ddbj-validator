"""web API の run dir 上のファイルの扱い（アップロード保存・入力列挙・失敗の検出）。

PR #7（DDBJ Record 入力対応）のレビューで見つかった 3 件の既存不具合を固定する。
いずれも入力形式とは無関係で、XML しか受けていなかった間は表に出にくかったもの。

1. アップロードが run 自身の出力（result.json 等）と同名だと上書きし合う
2. `GET /validation/{uuid}/input` が `*.xml` 決め打ちで、TSV 入力を取り出せない
3. レポートを出さずに落ちた run が `finished` に化ける（未捕捉例外も終了コード 1 のため）

実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import json
import types

import pytest

from apps.webapi import runner
from common import run_event


# --- run 自身の出力の判別 -----------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("result.json", True),
    ("status.json", True),
    ("validation.log", True),
    ("result.json.4242.a1b2c3d4.tmp", True),    # 原子的書き換えの一時ファイル
    ("status.json.4242.a1b2c3d4.tmp", True),
    ("SSUB000001.xml", False),
    ("SSUB000001.Human.txt", False),
    ("biosample", False),                        # 拡張子なしのフォールバック名
    ("x.tmp", False),                            # 無関係な .tmp は入力として扱う
])
def test_is_run_output(name, expected):
    assert run_event.is_run_output(name) is expected


# --- 1. アップロードの予約名回避 ----------------------------------------

def test_save_upload_keeps_normal_name(tmp_path):
    p = runner.save_upload(tmp_path, "biosample", "SSUB000001.xml", b"<x/>")
    assert p.name == "SSUB000001.xml"


@pytest.mark.parametrize("name", ["result.json", "status.json", "validation.log"])
def test_save_upload_avoids_run_output_names(tmp_path, name):
    """run の出力と同名で送られても上書きしない（入力が検証結果として読み出されるのを防ぐ）。"""
    p = runner.save_upload(tmp_path, "biosample", name, b"payload")
    assert p.name == f"biosample_{name}"
    assert not (tmp_path / name).exists()


def test_save_upload_falls_back_to_role_name(tmp_path):
    p = runner.save_upload(tmp_path, "bioproject", None, b"<x/>")
    assert p.name == "bioproject.xml"


def test_save_upload_strips_directory_components(tmp_path):
    """ファイル名は呼び出し側から来るので、パスが混ざっていても run dir の外に出さない。"""
    p = runner.save_upload(tmp_path, "biosample", "../../etc/passwd", b"x")
    assert p.parent == tmp_path and p.name == "passwd"


# --- 2. 入力ファイルの列挙（GET /validation/{uuid}/input）---------------

def _list_inputs(rdir):
    """app.get_file の input 分岐と同じ選び方。"""
    return sorted(p.name for p in rdir.iterdir()
                  if p.is_file() and not run_event.is_run_output(p.name))


def test_input_listing_picks_non_xml(tmp_path):
    """TSV 入力（および JSON など将来の形式）も取り出せること。"""
    (tmp_path / "SSUB000001.Human.txt").write_text("a\tb\n")
    run_event.write_status(tmp_path, uuid="u", status=run_event.FINISHED)
    (tmp_path / "result.json").write_text("{}")
    (tmp_path / "validation.log").write_text("log")
    (tmp_path / "reports").mkdir()
    assert _list_inputs(tmp_path) == ["SSUB000001.Human.txt"]


def test_input_listing_excludes_run_outputs(tmp_path):
    (tmp_path / "SSUB000001.xml").write_text("<x/>")
    (tmp_path / "result.json").write_text("{}")
    (tmp_path / "status.json").write_text("{}")
    (tmp_path / "validation.log").write_text("")
    assert _list_inputs(tmp_path) == ["SSUB000001.xml"]


def test_input_listing_picks_extensionless_fallback(tmp_path):
    """D-way が拡張子なし "biosample" で送ったときの後方互換。"""
    (tmp_path / "biosample").write_text("<x/>")
    (tmp_path / "status.json").write_text("{}")
    assert _list_inputs(tmp_path) == ["biosample"]


# --- 3. レポートが出なかった run の検出 ---------------------------------

class _Proc:
    def __init__(self, returncode=1, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run(monkeypatch, tmp_path, proc, report=None):
    """run_validation を、validator を起動せずに走らせる。report を渡すとレポートを書いたことにする。"""
    monkeypatch.setattr(runner.config, "VALIDATOR_CMD", ["true"])

    def fake_run(cmd, **kw):
        if report is not None:
            d = tmp_path / "reports"
            d.mkdir(parents=True, exist_ok=True)
            (d / "validation_report.json").write_text(json.dumps(report), encoding="utf-8")
        return proc

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    saved = {"biosample": tmp_path / "SSUB000001.xml"}
    final = runner.run_validation(tmp_path, saved, {})
    return final, run_event.read_status(tmp_path)


def test_no_report_is_error_even_on_exit_1(monkeypatch, tmp_path):
    """未捕捉例外は終了コード 1。レポートが無いのに finished にしない。"""
    final, status = _run(monkeypatch, tmp_path,
                         _Proc(returncode=1, stderr="Traceback...\nValueError: boom"))
    assert final == run_event.ERROR
    assert status["status"] == run_event.ERROR
    assert "boom" in status["message"] and "exit=1" in status["message"]


def test_no_report_is_error_on_exit_0(monkeypatch, tmp_path):
    final, status = _run(monkeypatch, tmp_path, _Proc(returncode=0, stdout="nothing to do"))
    assert final == run_event.ERROR
    assert "nothing to do" in status["message"]


def test_report_present_is_finished(monkeypatch, tmp_path):
    """error 級の検証結果があって終了コード 1 でも、レポートが出ていれば finished。"""
    final, status = _run(monkeypatch, tmp_path, _Proc(returncode=1),
                         report={"stats": {"error": 3}})
    assert final == run_event.FINISHED
    assert status["status"] == run_event.FINISHED
    assert "message" not in status          # 正常時は message を書かない


def test_report_present_ignores_exit_code(monkeypatch, tmp_path):
    """レポートが出ていれば終了コードは見ない（修正前後で不変であることの固定）。"""
    final, _ = _run(monkeypatch, tmp_path, _Proc(returncode=2), report={"stats": {"error": 0}})
    assert final == run_event.FINISHED


def test_report_with_error_status_is_error(monkeypatch, tmp_path):
    final, _ = _run(monkeypatch, tmp_path, _Proc(returncode=1), report={"status": "error"})
    assert final == run_event.ERROR


def test_failure_message_is_bounded(monkeypatch, tmp_path):
    """status.json が肥大しないよう、添える出力は頭打ちにする。"""
    _, status = _run(monkeypatch, tmp_path, _Proc(returncode=1, stderr="x" * 5000))
    assert len(status["message"]) < 700 and status["message"].endswith("...")
