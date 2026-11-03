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
