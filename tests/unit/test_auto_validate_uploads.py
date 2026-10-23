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
