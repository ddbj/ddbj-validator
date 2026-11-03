"""ddbj: 実行ごとに出力ディレクトリ（fixed/ aa/ reports/ biosample/）を空にする（2026-11-03）。

登録ファイル名を変えて再実行すると前回の fixed/ が残り、load-nsub で二重登録になっていた。
"""
import os

from apps.ddbj.cli import clear_output_dirs


def _touch(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_clears_previous_outputs(tmp_path):
    for rel in ["fixed/OLD.ann", "fixed/OLD.fasta", "aa/AA_OLD.faa",
                "reports/validation_report.json", "reports/sub/x.txt", "biosample/SSUB1_NSUB1.txt"]:
        _touch(tmp_path / rel)
    _touch(tmp_path / "NEW.ann")
    _touch(tmp_path / "NEW.fasta")
    pairs = [(str(tmp_path / "NEW.ann"), str(tmp_path / "NEW.fasta"))]
    cleared = dict(clear_output_dirs(tmp_path, pairs))
    assert cleared == {"fixed": 2, "aa": 1, "reports": 2, "biosample": 1}
    for name in ["fixed", "aa", "reports", "biosample"]:
        assert (tmp_path / name).is_dir() and not any((tmp_path / name).iterdir())
    # 入力ファイルは残る
    assert (tmp_path / "NEW.ann").exists() and (tmp_path / "NEW.fasta").exists()


def test_no_output_dirs(tmp_path):
    assert clear_output_dirs(tmp_path, []) == []


def test_keeps_dir_containing_inputs(tmp_path):
    # -o . fixed/ のように fixed/ の登録ファイル自体を検証する場合は消さない
    _touch(tmp_path / "fixed/A.ann")
    _touch(tmp_path / "fixed/A.fasta")
    _touch(tmp_path / "aa/AA_A.faa")
    pairs = [(str(tmp_path / "fixed/A.ann"), str(tmp_path / "fixed/A.fasta"))]
    assert dict(clear_output_dirs(tmp_path, pairs)) == {"aa": 1}
    assert (tmp_path / "fixed/A.ann").exists()


def test_does_not_follow_symlinked_dir(tmp_path):
    real = tmp_path / "elsewhere"
    _touch(real / "keep.ann")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(real, out / "fixed")
    assert clear_output_dirs(out, []) == []
    assert (real / "keep.ann").exists()


# ---- --clean option と前回の残りの警告 ----
import time

from apps.ddbj.cli import _build_parser, find_stale_outputs, warn_stale_outputs


def test_clean_option_default_off(monkeypatch):
    monkeypatch.delenv("DDBJ_VALIDATOR_CLEAN", raising=False)
    assert _build_parser().parse_args(["x"]).clean is False
    assert _build_parser().parse_args(["--clean", "x"]).clean is True


def test_clean_option_env_default_and_no_clean(monkeypatch):
    # curator 用 wrapper（ddbj-validator.sh）が設定する
    monkeypatch.setenv("DDBJ_VALIDATOR_CLEAN", "1")
    assert _build_parser().parse_args(["x"]).clean is True
    assert _build_parser().parse_args(["--no-clean", "x"]).clean is False


def test_stale_outputs_warned_not_removed(tmp_path, capsys):
    old = tmp_path / "fixed/SAMD00000001.ann"
    _touch(old)
    past = time.time() - 3600
    os.utime(old, (past, past))
    since = time.time() - 1
    _touch(tmp_path / "fixed/SAMD00000001a.ann")  # 今回書いたファイル
    assert find_stale_outputs(tmp_path, since) == {"fixed": ["SAMD00000001.ann"]}
    warn_stale_outputs(tmp_path, since)
    err = capsys.readouterr().err
    assert "fixed/ has 1 file(s) not written by this run" in err and "SAMD00000001.ann" in err
    assert "--clean" in err
    assert old.exists()


def test_stale_outputs_many_are_truncated(tmp_path, capsys):
    past = time.time() - 3600
    for i in range(7):
        p = tmp_path / f"aa/AA_{i}.faa"
        _touch(p)
        os.utime(p, (past, past))
    warn_stale_outputs(tmp_path, time.time())
    assert "and 2 more" in capsys.readouterr().err
