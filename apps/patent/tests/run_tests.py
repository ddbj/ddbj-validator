#!/usr/bin/env python3
"""patent の E2E ハーネス。

`apps/patent/tests/<規則>/` の fixture（ann + FASTA の組）ごとに CLI を丸ごと実行し
（`patent -l --json`）、JSON の報告を見て判定する。期待はファイル名で決まる。
- `<名前>.fail_na.ann` / `.fail_aa.ann` … そのディレクトリ名の rule id がそのファイルに出ること。
- `<名前>.pass_na.ann` / `.pass_aa.ann` … そのファイルに何も出ないこと（どの rule も。誤検出の検査を兼ねる）。

    .venv/bin/python apps/patent/tests/run_tests.py            # 全部
    .venv/bin/python apps/patent/tests/run_tests.py PAT0035    # ディレクトリ名で絞る

taxonomy を引く PAT0043 は内部 DB が要るので、ここでは回さない（tests/unit/test_patent.py で見る）。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from common.e2e import E2ERunner, GREEN, RED, END  # noqa: E402

TESTS_DIR = Path(__file__).resolve().parent


def run_cli(target_dir, out_dir):
    cmd = [sys.executable, str(ROOT / "main.py"), "patent", "-l", "--json", "-j", "1", "-o", str(out_dir), str(target_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    report = Path(out_dir) / "reports" / "validation_report.json"
    if proc.returncode != 0 or not report.exists():
        raise RuntimeError(f"CLI failed for {target_dir.name}: rc={proc.returncode}\n{proc.stderr[-2000:]}")
    return json.loads(report.read_text(encoding="utf-8"))


def main():
    filters = sys.argv[1:]
    runner = E2ERunner("patent")
    dirs = sorted(d for d in TESTS_DIR.iterdir() if d.is_dir() and not d.name.startswith((".", "_")))
    if filters:
        dirs = [d for d in dirs if any(f in d.name for f in filters)]
    for d in dirs:
        print(f"\n--- {d.name} ---")
        with tempfile.TemporaryDirectory(prefix="patent_e2e_") as tmp:
            report = run_cli(d, tmp)
        fired = {}
        for m in report["messages"]:
            fired.setdefault(m["file"], set()).add(m["id"])
        for ann in sorted(d.glob("*.ann")):
            ids = fired.get(ann.name, set())
            if ".fail" in ann.name:
                runner.check_rule(ann.name, d.name, "fail", ids)
            elif ".pass" in ann.name:
                # 正常な set には何も出ないこと
                if ids:
                    runner.mismatched += 1
                    print(f"  [{RED}MISMATCH{END}] {ann.name}: expected no message, fired={sorted(ids)}")
                else:
                    runner.matched += 1
                    print(f"  [{GREEN}Matched{END}]  {ann.name} (no message)")
    return runner.finish()


if __name__ == "__main__":
    sys.exit(main())
