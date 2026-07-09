#!/usr/bin/env python3
"""BioSample 実データ回帰スイート（本番 result.json を基準に現行 v の退行を検知）。

**要内部DB・opt-in**（--account dradev の実データを使うため。既定 E2E/make push には含めない）。
manifest.json の各 package について:
  現行 v を `-t <compare.txt> -s <SSUB> -p <package> -d --account <acct> -j` で実行し、
  本番 result.json と sample × rule 突合。既知の意図的差分（known_diffs.json）と比較し、
  **未知の差分（＝退行 or 本番仕様変更）** を検出したら終了コード 1。

使い方:
  python apps/biosample/tests/regression/run_regression.py            # 検証（既知差分と一致すれば PASS）
  python apps/biosample/tests/regression/run_regression.py --update   # 現状の差分を known_diffs.json に保存（基準更新）
  python apps/biosample/tests/regression/run_regression.py SSUB047754 # 単一 package
known_diffs.json は「本番と意図的に異なる差分」の基準。詳細は docs/biosample/known-differences.md 参照。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
from compare_prod import diff  # noqa: E402  （同ディレクトリのユーティリティ）

MANIFEST = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
KNOWN = HERE / "known_diffs.json"
PY = str(ROOT / ".venv" / "bin" / "python")
GREEN, RED, YEL, END = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def run_current(entry, outdir):
    """現行 v を実行し、生成された validation_report.json のパスを返す（失敗時 None）。"""
    cmd = [PY, str(ROOT / "main.py"), "biosample",
           "-t", str(HERE / entry["tsv"]),
           "-s", entry["ssub"], "-p", entry["package"],
           "-d", "--account", entry["account"], "-o", outdir, "-j"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    rep = Path(outdir) / "reports" / "validation_report.json"
    if not rep.is_file():
        print(f"  {RED}[ERROR]{END} 現行 v 実行失敗: {r.stderr.strip()[:200]}")
        return None
    return str(rep)


def diffs_as_set(diffs):
    return {(s, tuple(a), tuple(b)) for s, a, b in diffs}


def main(argv):
    update = "--update" in argv
    targets = [a for a in argv if not a.startswith("-")]
    known = json.loads(KNOWN.read_text(encoding="utf-8")) if KNOWN.is_file() else {}
    new_known = {}
    regressions = 0
    entries = [e for e in MANIFEST if not targets or e["ssub"] in targets]
    for e in entries:
        ssub = e["ssub"]
        with tempfile.TemporaryDirectory() as td:
            cur = run_current(e, td)
            if cur is None:
                regressions += 1
                continue
            res = diff(cur, str(HERE / e["prod_json"]))
        cur_diffs = diffs_as_set(res["diffs"])
        new_known[ssub] = [[s, a, b] for s, a, b in res["diffs"]]
        print(f"[{ssub}] {e['package']}: 一致={res['matched']} 現行のみ={res['cur_only']} 本番のみ={res['prod_only']} "
              f"(cur {res['cur_messages']} / prod {res['prod_messages']} msgs)")
        if update:
            continue
        base = diffs_as_set([tuple(x) for x in known.get(ssub, [])])
        new = cur_diffs - base           # 既知に無い新差分＝退行 or 本番変更
        gone = base - cur_diffs          # 既知だが消えた（改善 or fixture 変化）
        for s, a, b in sorted(new):
            print(f"  {RED}[REGRESSION]{END} sample {s}: 現行のみ={list(a) or '-'} / 本番のみ={list(b) or '-'}")
            regressions += 1
        for s, a, b in sorted(gone):
            print(f"  {YEL}[DRIFT]{END} 既知差分が消失 sample {s}: 現行のみ={list(a) or '-'} / 本番のみ={list(b) or '-'}")

    if update:
        KNOWN.write_text(json.dumps(new_known, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\n{GREEN}[UPDATED]{END} known_diffs.json を現状の差分で更新。")
        return 0
    if regressions:
        print(f"\n{RED}[FAIL]{END} 未知の差分（退行/本番変更）が {regressions} 件。")
        return 1
    print(f"\n{GREEN}[PASS]{END} 既知の意図的差分のみ。退行なし。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
