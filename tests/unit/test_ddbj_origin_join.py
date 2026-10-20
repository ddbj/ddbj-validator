"""circular 配列で origin を跨ぐ join（2026-10-20）。

`join(n..L,1..m)` / `complement(join(n..L,1..m))` はゲノム上は連続した領域。
minus 鎖は parser が parts を逆順に並べるため、鎖を見ずに判定すると
ANN2020（error）/ ANN4210 / AXS6810（intron 誤認）が出ていた。
"""
from Bio.SeqFeature import SeqFeature

from apps.ddbj.location_parser import _parse_location_string
from apps.ddbj.utils.location import crosses_origin, get_introns_from_join

L = 120


def _loc(s):
    return _parse_location_string(s, seq_length=L)


def test_origin_join_is_marked_not_error_on_both_strands():
    for s in ("join(90..120,1..21)", "complement(join(90..120,1..21))"):
        loc = _loc(s)
        assert getattr(loc, "_spans_origin", False), s
        assert not hasattr(loc, "_out_of_order_error"), s
        assert crosses_origin(loc, L), s
        assert get_introns_from_join(SeqFeature(loc), L) == [], s   # 継ぎ目は intron ではない


def test_end_not_at_sequence_length_is_still_error():
    loc = _loc("complement(join(90..119,1..21))")
    assert not getattr(loc, "_spans_origin", False)
    assert hasattr(loc, "_out_of_order_error")


def test_ordinary_join_touching_both_ends_is_not_origin():
    # 1 塩基目と L 塩基目を含むだけの普通の join（plus / minus）は跨ぎではない
    for s in ("join(1..10,50..120)", "complement(join(1..10,50..120))"):
        loc = _loc(s)
        assert not getattr(loc, "_spans_origin", False), s
        assert not crosses_origin(loc, L), s
        assert [(i["start"], i["end"]) for i in get_introns_from_join(SeqFeature(loc), L)] == [(10, 49)], s


def test_origin_and_real_intron_in_one_join():
    # origin 跨ぎ＋本物の intron（110..114 の間）を含む minus 鎖
    loc = _loc("complement(join(90..110,115..120,1..21))")
    assert crosses_origin(loc, L)
    assert [(i["start"], i["end"]) for i in get_introns_from_join(SeqFeature(loc), L)] == [(110, 114)]
