#!/usr/bin/env python3
"""DRA validator E2E（in-process）。

apps/dra/tests/<RULEID>/ 配下の 1 シナリオ = 1 ディレクトリ。ディレクトリ内の *.xml を
まとめて 1 submission として検証し、`.pass`/`.fail` をディレクトリ名（＝ルール）で判定する。
ディレクトリに record.json（DDBJ Record v3）があれば、XML の代わりにそれを検証する。
そのシナリオと XML との parity は `--record` を付けたときだけ。XML 側のルールを変えても、
Record への追随を待たずに通せるように。
- ディレクトリ名末尾が `.pass` なら当該ルールが発火しないこと、`.fail` なら発火することを期待。
- level=info（Record 入力で「読まなかった」を知らせる注記）は発火に数えない。
"""
import sys
import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from apps.dra.context import ValidationContext
from apps.dra.validator import Validator
from apps.dra import record_reader, xml_reader

from common.e2e import E2ERunner

# DB 依存ルール（R0004/0009/0015/0016）＋ 日付基準（R0006）の決定的 mock。
MOCK_ORG = "NIG Center"
MOCK_BP = {"PRJDB1"}
MOCK_BS = {"SAMD00000001"}
MOCK_RUNS = {"DRR0000001"}
MOCK_OBJ_NAMES = {"DUP_ALIAS"}
MOCK_HOLD_REF = datetime.date(2026, 1, 1)

RECORD = "record.json"   # シナリオが DDBJ Record のとき、ディレクトリ内のファイル名


def _context():
    return ValidationContext(skip_db=False, skip_ncbi=False, skip_auth=False,
                             account_org_name=MOCK_ORG,
                             account_bioprojects=set(MOCK_BP),
                             account_biosamples=set(MOCK_BS),
                             account_runs=set(MOCK_RUNS),
                             account_object_names=set(MOCK_OBJ_NAMES),
                             hold_ref_date=MOCK_HOLD_REF)


def _fired(scenario_dir):
    record = scenario_dir / RECORD
    if record.exists():
        sub, pre = record_reader.parse_record(str(record))
    else:
        sub, pre = xml_reader.parse_files(sorted(str(p) for p in scenario_dir.glob("*.xml")))
    results = list(pre)
    if sub is not None:
        results += Validator(_context()).run(sub)
    return {r["rule_id"] for r in results if r["level"] != "info"}


def main(argv):
    targets = [a for a in argv if not a.startswith("-")]
    record  = "--record" in argv

    # 打ち間違い（--recrod）を黙って XML だけの実行にしない。
    unknown = [a for a in argv if a.startswith("-") and a != "--record"]
    if unknown:
        print(f"unknown option(s): {' '.join(unknown)} (only --record)", file=sys.stderr)
        return 2
    dirs = sorted(d for d in HERE.iterdir() if d.is_dir() and d.name.startswith("DRA_R")
                  and (not targets or any(t in d.name for t in targets)))
    runner = E2ERunner("DRA rule")
    for d in dirs:
        # ディレクトリ名: DRA_R00xx_n.pass / DRA_R00xx_n.fail
        parts = d.name.split(".")
        if parts[-1] not in ("pass", "fail"):
            continue
        if (d / RECORD).exists() and not record:
            continue
        rid = parts[0].split("_")[0] + "_" + parts[0].split("_")[1]  # DRA_R00xx
        runner.check_rule(d.name, rid, parts[-1], _fired(d))
    rule_status = runner.finish()

    # Record を含めた全件実行のときだけ、XML と Record の同値性も確かめる。
    parity_ok = True
    if record and not targets:
        print("\n--- XML / DDBJ Record parity test ---")
        import importlib.util
        path = HERE / "run_record_parity_test.py"
        spec = importlib.util.spec_from_file_location("run_record_parity_test", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        parity_ok = mod.main() == 0

    return 0 if (rule_status == 0 and parity_ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
