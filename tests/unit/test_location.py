"""apps/ddbj/utils/location.py の純関数の挙動を固定するユニットテスト。

get_introns_from_join は既存の utils 関数。
get_feature_positions は提案 C で cross.py から utils へ移設する関数（移設後もここでテスト）。
"""
from Bio.SeqFeature import SeqFeature, FeatureLocation, CompoundLocation

from apps.ddbj.utils.location import get_introns_from_join, get_feature_positions


def test_get_introns_non_compound_returns_empty():
    feat = SeqFeature(FeatureLocation(0, 10, strand=1), type="CDS")
    assert get_introns_from_join(feat) == []


def test_get_introns_two_exon_join():
    feat = SeqFeature(
        CompoundLocation([FeatureLocation(0, 10, 1), FeatureLocation(20, 30, 1)]),
        type="CDS",
    )
    assert get_introns_from_join(feat) == [{"start": 10, "end": 20, "length": 10}]


def test_feature_positions_single_part_plus_strand():
    assert get_feature_positions(FeatureLocation(0, 3, strand=1)) == [0, 1, 2]


def test_feature_positions_single_part_minus_strand():
    # マイナス鎖は末尾から先頭に向かって列挙される
    assert get_feature_positions(FeatureLocation(0, 3, strand=-1)) == [2, 1, 0]


def test_feature_positions_compound_concatenates_parts():
    loc = CompoundLocation([FeatureLocation(0, 3, 1), FeatureLocation(10, 12, 1)])
    assert get_feature_positions(loc) == [0, 1, 2, 10, 11]


def test_feature_positions_none_returns_empty():
    assert get_feature_positions(None) == []
