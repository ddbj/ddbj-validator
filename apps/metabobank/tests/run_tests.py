#!/usr/bin/env python3
"""MetaboBank validator E2E（in-process・実データ回帰）。

apps/metabobank/tests/data/ の実例 3 studies（-l ローカル）を検証し、発火 rule_id 集合が
期待集合（EXPECTED）と一致するかを判定する。ルール改修時の退行検知用。
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from apps.metabobank.context import ValidationContext
from apps.metabobank.validator import Validator
from apps.metabobank import reader

GREEN, RED, END = "\033[92m", "\033[91m", "\033[0m"
DATA = HERE / "data"

# -l（DB 非依存）での期待発火 rule_id（ignore 含む）。conf 由来の既知発火。
EXPECTED = {
    # 実データ 3 studies は ° / µ / × 等を含むため MB_IR0024（正規化 warning）が発火する。
    "MTBKS210": {"MB_IR0024", "MB_IR0037"},
    # MTBKS230 は IDF factor name/type が "missing"。factor 任意化に伴い null value は不許可に
    # したので、Name は MB_IR0007（error/ignore）、Type は MB_IR0023（任意項目の null warning）
    # で受ける。Factor Value 列が無いことは MB_SR0005 の対象外になった（任意化）。
    # MB_IR0018 は LC-MS Chromatography: Temperature を必須から外したので出なくなった
    # （両 study とも LC-MS。MB_IR0018 自体は LC-DAD-MS 等で現役。担保は unit 側）。
    "MTBKS230": {"MB_IR0007", "MB_IR0023", "MB_IR0024", "MB_IR0037", "MB_SR0046"},
    "MTBKS240": {"MB_IR0024", "MB_IR0037"},
    # 非 ASCII 正規化 autofix ＋ 残存 error の合成ケース（IDF=MB_IR0024 / SDRF=MB_SR0030）。
    "MTBKS_charnorm": {"MB_IR0024", "MB_SR0030", "MB_IR0037"},
    # MB_SR0003（列名重複）は singleton_columns のみが対象。Unit[...] のような修飾列は
    # 同名で複数回現れても発火しない（Sample Name の重複だけが検出される）。
    "MTBKS_dupcol": {"MB_IR0024", "MB_IR0037", "MB_SR0003"},
    # Protocol REF の type 参照（MB_SR0034/0035）とデータファイル名・ディレクトリ名の
    # 禁則文字（MB_SR0036/0037）。実データには違反が無いため合成ケースで担保する。
    "MTBKS_protofile": {"MB_IR0024", "MB_IR0037",
                        "MB_SR0034", "MB_SR0035", "MB_SR0036", "MB_SR0037"},
    # MSI（imaging）は抽出工程が無く投稿テンプレートにも Extract Name 列が無いため、
    # 必須列から除外される（MB_SR0004 が出ない）。実データ MTBKS212 をそのまま使用。
    "MTBKS_msi": {"MB_IR0024", "MB_IR0037", "MB_SR0046"},
    # 同じ SDRF でも MSI 以外（FIA-MS）で Extract Name が無ければ MB_SR0004 は出る。
    "MTBKS_noextract": {"MB_IR0024", "MB_IR0037", "MB_SR0004"},
    # MB_CR0001 の双方向照合。IDF が dose のみ・SDRF が Factor Value[tissue] のみなので
    # only in IDF と only in SDRF の 2 件が出る（rule_id 集合では 1 件に畳まれるため、
    # 件数と向きの担保は tests/unit/test_metabobank_factor.py 側）。
    # Experimental Factor Type は値なし＝任意・無検証なので何も出ない。
    "MTBKS_factor": {"MB_CR0001", "MB_IR0024", "MB_IR0037"},
    # Factor Value[tissue] 列はあるが全行空。任意列になったので factor が無いなら列自体を
    # 書かなければよく、列だけ作って値が無いのは MB_SR0047。MB_SR0017（全行で一定）は
    # 同じ列を二重に指摘しないよう抑止されるので、期待集合に入らないことが担保になる。
    "MTBKS_factorval": {"MB_IR0024", "MB_IR0037", "MB_SR0047"},
}


def _fired(study):
    sub, pre = reader.parse(str(DATA / f"{study}.idf.txt"), str(DATA / f"{study}.sdrf.txt"))
    ctx = ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True)
    results = list(pre) + Validator(ctx).run(sub)
    return {r["rule_id"] for r in results}


def main(argv):
    matched = mismatched = 0
    for study, expected in EXPECTED.items():
        fired = _fired(study)
        ok = fired == expected
        if ok:
            matched += 1
            print(f"  [{GREEN}Matched{END}]  {study}: {sorted(fired)}")
        else:
            mismatched += 1
            print(f"  [{RED}MISMATCH{END}] {study}: fired={sorted(fired)} expected={sorted(expected)}"
                  f" (+{sorted(fired - expected)} / -{sorted(expected - fired)})")
    print(f"\n  Matched: {matched}   Mismatched: {mismatched}")
    if mismatched:
        print(f"{RED}[FAIL]{END}"); return 1
    print(f"{GREEN}[SUCCESS] All MetaboBank tests passed.{END}"); return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
