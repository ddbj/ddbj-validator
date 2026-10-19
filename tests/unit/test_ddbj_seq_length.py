"""SEQ5050（2.14G 超 error）/ SEQ5052（1G 超 info）の閾値（2026-10-19）。

1G 超の配列が DB 投入できるようになったため SEQ5050 を 2.14G に緩和し、
1G 超は SEQ5052 の info でキュレータへ知らせる。巨大配列は fixture にできないので、
長さだけを返す配列オブジェクトで判定境界を確かめる。
"""
import pytest

from apps.ddbj.rules.sequence import SEQ5050, SEQ5052


class _Seq:
    def __init__(self, n):
        self.n = n

    def __len__(self):
        return self.n


class _Rec:
    def __init__(self, n, rid="seq1"):
        self.id, self.seq = rid, _Seq(n)


@pytest.mark.parametrize("n, e5050, e5052", [
    (1_000_000_000, [], []),                 # ちょうど 1G は何も出ない
    (1_000_000_001, [], ["info"]),           # 1G 超 → info
    (1_332_302_522, [], ["info"]),           # NSUB004087 LKA1ch01
    (2_140_000_000, [], ["info"]),           # ちょうど 2.14G は error にしない
    (2_140_000_001, ["error"], []),          # 2.14G 超 → error のみ（info は重ねない）
])
def test_thresholds(n, e5050, e5052):
    assert [r["level"] for r in SEQ5050().validate(_Rec(n), None)] == e5050
    assert [r["level"] for r in SEQ5052().validate(_Rec(n), None)] == e5052


def test_message_and_common_skip():
    r = SEQ5052().validate(_Rec(1_332_302_522), None)[0]
    assert r["message"] == "Sequence longer than 1Gbases. (Length: 1,332,302,522 bases)"
    assert SEQ5052().validate(_Rec(1_500_000_000, rid="COMMON"), None) == []
