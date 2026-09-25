"""ANN4240 の 5' partial autofix が codon_start も合わせて直すこと。

`<2..532` を `<1..532` に伸ばしたとき、codon_start を 1 のままにすると読み枠が 1 ずれ、
autofix の結果が AXS6050（不正な停止コドン）/ AXS6060（内部停止コドン）で落ちていた
（2026-09-25 の報告 NSUB003929）。codon_start を 2 にすると両方消えることを実測で確認済み。

ここでは (1) ずらし幅の計算 (2) 5' 端が鎖で決まること (3) writer の feature 単位の
qualifier 更新、の 3 つを固定する。
"""
from types import SimpleNamespace

from apps.ddbj.autofix.format import _shifted_codon_start
from apps.ddbj.autofix.proposal import update_qualifier_in_feature_action
from apps.ddbj.autofix.writer import write_autofix_to_file


def _cds(codon_start=None):
    q = {"codon_start": [codon_start]} if codon_start is not None else {}
    return SimpleNamespace(qualifiers=q)


# ---------------- ずらし幅の計算 ----------------
def test_codon_start_shifts_with_the_five_prime_extension():
    """new = ((old - 1) + shift) % 3 + 1。"""
    assert _shifted_codon_start(_cds("1"), 1) == (1, 2)   # 報告の実ケース
    assert _shifted_codon_start(_cds("1"), 2) == (1, 3)
    assert _shifted_codon_start(_cds("2"), 1) == (2, 3)
    assert _shifted_codon_start(_cds("2"), 2) == (2, 1)
    assert _shifted_codon_start(_cds("3"), 1) == (3, 1)


def test_codon_start_is_not_touched_when_it_would_not_change():
    # 3' 側だけ伸ばした（5' は動いていない）
    assert _shifted_codon_start(_cds("1"), 0) == (None, None)
    # ずらし幅が 3 の倍数なら値は変わらない
    assert _shifted_codon_start(_cds("1"), 3) == (1, None)
    assert _shifted_codon_start(_cds("2"), 6) == (2, None)


def test_missing_codon_start_defaults_to_one_and_gets_added():
    """省略時は 1。伸ばした後は 1 では枠が合わないので追加対象になる。"""
    assert _shifted_codon_start(_cds(), 1) == (1, 2)
    assert _shifted_codon_start(_cds(), 3) == (1, None)


def test_broken_codon_start_is_left_alone():
    """1/2/3 以外は AXS6420 の担当。こちらで直さない。"""
    assert _shifted_codon_start(_cds("x"), 1) == ("x", None)
    assert _shifted_codon_start(_cds("0"), 1) == ("0", None)


# ---------------- writer の feature 単位の更新 ----------------
# preprocessor が渡す形に合わせて行末の改行は持たせない
_ANN = [
    "seq1\tsource\t1..300\torganism\tEscherichia coli",
    "\tCDS\t<1..100\tproduct\thypothetical protein",   # 2 行目: 直したい CDS
    "\t\t\tcodon_start\t1",
    "\t\t\tlocus_tag\tTAG_0001",
    "\tCDS\t150..250\tproduct\tanother protein",       # 5 行目: 別の CDS
    "\t\t\tcodon_start\t1",                            # 同じ qualifier・同じ値
    "\t\t\tlocus_tag\tTAG_0002",
]


def test_update_qualifier_in_feature_touches_only_that_feature(tmp_path):
    """codon_start は entry 内に同じ値が多数あるので、feature 行で範囲を絞る。

    絞らないと（既存の update_qualifier のように qualifier 名＋旧値だけで一致を見ると）
    同じ entry の codon_start 1 が全部書き換わる。
    """
    out = tmp_path / "out.ann"
    updates = [update_qualifier_in_feature_action(
        "seq1", "CDS", "codon_start", "1", "2", feature_line=2, feature_id=2)]
    assert write_autofix_to_file(_ANN, updates, out)
    lines = out.read_text().splitlines()
    assert lines[2] == "\t\t\tcodon_start\t2"     # 対象の CDS だけ
    assert lines[5] == "\t\t\tcodon_start\t1"     # 別の CDS は元のまま


def test_update_qualifier_in_feature_ignores_a_wrong_feature_line(tmp_path):
    out = tmp_path / "out.ann"
    updates = [update_qualifier_in_feature_action(
        "seq1", "CDS", "codon_start", "1", "2", feature_line=5, feature_id=5)]
    write_autofix_to_file(_ANN, updates, out)
    lines = out.read_text().splitlines()
    assert lines[2] == "\t\t\tcodon_start\t1"
    assert lines[5] == "\t\t\tcodon_start\t2"
