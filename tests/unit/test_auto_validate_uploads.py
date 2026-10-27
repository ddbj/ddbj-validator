"""deploy/auto_validate_uploads.py の対象選択（2026-10-23）。

最新の日時ディレクトリだけ・--since 以降・アップロード直後は待つ・disable-upload と印があれば実行しない。
印と結果は出力側（--out-root）にだけ置き、アップロード先には何も書かない（mss form で見えるため）。
"""
import importlib.util
import json
import os
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "auto_validate_uploads", Path(__file__).resolve().parents[2] / "deploy/auto_validate_uploads.py")
av = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(av)

OLD = time.time() - 3600   # 1 時間前（quiet を過ぎている）


def _upload(root, nsub, name, files=("a.ann", "a.fasta"), mtime=OLD):
    d = root / nsub / name
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("x")
        os.utime(d / f, (mtime, mtime))
    os.utime(d, (mtime, mtime))
    return d


def _out(root):
    return root.parent / (root.name + "_out")


def _cands(root, since="20261023"):
    return [str(p.relative_to(root)) for p in av.find_candidates(root, _out(root), since, 600)]


def test_latest_only_and_since(tmp_path):
    _upload(tmp_path, "NSUB000001", "20261023-090000")
    _upload(tmp_path, "NSUB000001", "20261023-100000")     # 最新だけ
    _upload(tmp_path, "NSUB000002", "20261022-235959")     # since より前
    assert _cands(tmp_path) == ["NSUB000001/20261023-100000"]


def test_old_nsub_dir_is_not_scanned(tmp_path):
    _upload(tmp_path, "NSUB000003", "20261023-100000")
    old = time.mktime((2026, 10, 1, 0, 0, 0, 0, 0, -1))
    os.utime(tmp_path / "NSUB000003", (old, old))          # NSUB の mtime が since より前なら見ない
    assert _cands(tmp_path) == []


def test_disable_upload_and_marks(tmp_path):
    _upload(tmp_path, "NSUB000001", "20261023-100000")
    (tmp_path / "NSUB000001" / "disable-upload").write_text("")
    for nsub, mark in (("NSUB000002", av.DONE_MARK), ("NSUB000003", av.RUNNING_MARK)):
        d = _upload(tmp_path, nsub, "20261023-100000")
        o = av.out_dir_for(_out(tmp_path), d)
        o.mkdir(parents=True)
        (o / mark).write_text("{}")
    assert _cands(tmp_path) == []


def test_wait_while_uploading(tmp_path):
    _upload(tmp_path, "NSUB000001", "20261023-100000", mtime=time.time() - 60)
    assert _cands(tmp_path) == []


def test_no_pair_is_marked_done_without_running(tmp_path):
    d = _upload(tmp_path, "NSUB000001", "20261023-100000", files=("a.ann.txt", "memo.xlsx"))
    rec = av.run_one(d, _out(tmp_path), jobs=1, timeout_sec=10)
    assert rec["status"] == "skipped_no_pair"
    assert sorted(p.name for p in d.iterdir()) == ["a.ann.txt", "memo.xlsx"]   # アップロード先は変えない
    done = _out(tmp_path) / "NSUB000001" / "20261023-100000" / av.DONE_MARK
    assert json.loads(done.read_text())["files"] == [
        {"name": "a.ann.txt", "size": 1, "mtime": int(OLD)}]
    assert _cands(tmp_path) == []


def test_has_pair_extensions():
    assert av.has_pair([("x.ann.txt", 1, 0), ("x.fa", 1, 0)])
    assert not av.has_pair([("x.ann.txt", 1, 0)])


# --- autofix の有無の記録（2026-10-27）---
# validator は autofix 提案があるときだけ reports/autofix_confirmation_summary.txt を書く。
# その有無を .validator.done・validator.log・cron ログに出す。

_SUMMARY = """=== Auto-Fix Confirmation ===

[ Target: collection_date ]
  ANN1130_1.fail
    1 entry, 1 feature, 1 qualifier: '2019-01-01' -> '2020-01-01' (SAMD00133774) [Rule: ANN1130]
  ANN1130_4.fail
    1 entry, 1 feature, 1 qualifier: '2019-01-01' -> '2020-01-01' (SAMD00133774) [Rule: ANN1130]

[ Target: ecotype ]
  ANN1130_1.fail
    1 entry, 1 feature, 1 qualifier: 'none' -> 'Col-0' (SAMD00133774) [Rule: ANN1130]
"""


def _write_summary(out, text=_SUMMARY, mtime=None):
    p = out / av.CONFIRMATION_REPORT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if mtime is not None:
        os.utime(p, (mtime, mtime))


def test_autofix_result_counts_change_lines(tmp_path):
    _write_summary(tmp_path)
    assert av.autofix_result(tmp_path, 0) == (True, 3)


def test_autofix_result_none_when_no_summary(tmp_path):
    assert av.autofix_result(tmp_path, 0) == (False, 0)


def test_autofix_result_ignores_summary_from_previous_run(tmp_path):
    # 印を消して再実行したとき、前回の確認サマリーを今回の autofix と数えない
    _write_summary(tmp_path, mtime=OLD)
    assert av.autofix_result(tmp_path, int(time.time()) - 10) == (False, 0)


def test_autofix_message():
    assert av.autofix_message({"autofix": False, "autofix_changes": 0}) == "autofix=none"
    assert av.autofix_message({"autofix": None, "autofix_changes": None}) == "autofix=unknown"
    assert av.autofix_message({"autofix": True, "autofix_changes": 1}) == \
        "autofix=applied (1 change, see reports/autofix_confirmation_summary.txt)"
    assert av.autofix_message({"autofix": True, "autofix_changes": 3}).startswith("autofix=applied (3 changes,")


def _fake_validator(write_summary):
    """subprocess.run の代わり。-o の出力 dir に、必要なら確認サマリーを書く。"""
    def run(cmd, stdout=None, **kw):
        out = Path(cmd[cmd.index("-o") + 1])
        stdout.write("validator output\n")
        if write_summary:
            _write_summary(out)
        return type("P", (), {"returncode": 0})()
    return run


def test_run_one_records_autofix_applied(tmp_path, monkeypatch, capsys):
    d = _upload(tmp_path, "NSUB000001", "20261023-100000")
    monkeypatch.setattr(av.subprocess, "run", _fake_validator(write_summary=True))
    rec = av.run_one(d, _out(tmp_path), jobs=1, timeout_sec=10)
    out = av.out_dir_for(_out(tmp_path), d)
    done = json.loads((out / av.DONE_MARK).read_text())
    assert (done["autofix"], done["autofix_changes"]) == (True, 3)
    assert rec["autofix"] is True
    assert (out / av.RUN_LOG).read_text().endswith(
        "[auto_validate_uploads] autofix=applied (3 changes, see reports/autofix_confirmation_summary.txt)\n")
    assert "autofix=applied (3 changes" in capsys.readouterr().out


def test_run_one_records_no_autofix(tmp_path, monkeypatch, capsys):
    d = _upload(tmp_path, "NSUB000001", "20261023-100000")
    monkeypatch.setattr(av.subprocess, "run", _fake_validator(write_summary=False))
    av.run_one(d, _out(tmp_path), jobs=1, timeout_sec=10)
    out = av.out_dir_for(_out(tmp_path), d)
    done = json.loads((out / av.DONE_MARK).read_text())
    assert (done["autofix"], done["autofix_changes"]) == (False, 0)
    assert (out / av.RUN_LOG).read_text().endswith("[auto_validate_uploads] autofix=none\n")
    assert "autofix=none" in capsys.readouterr().out


def test_run_one_timeout_autofix_unknown(tmp_path, monkeypatch):
    d = _upload(tmp_path, "NSUB000001", "20261023-100000")

    def run(cmd, **kw):
        raise av.subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(av.subprocess, "run", run)
    av.run_one(d, _out(tmp_path), jobs=1, timeout_sec=1)
    out = av.out_dir_for(_out(tmp_path), d)
    done = json.loads((out / av.DONE_MARK).read_text())
    assert done["status"] == "timeout" and done["autofix"] is None
    assert (out / av.RUN_LOG).read_text().endswith("[auto_validate_uploads] autofix=unknown\n")
