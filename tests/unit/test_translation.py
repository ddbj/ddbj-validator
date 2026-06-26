"""apps/ddbj/utils/translation.py の純関数の挙動を固定するユニットテスト。

提案 C では cross.py のローカル重複定義（get_cds_translation_params の二重定義、
未使用の get_conceptual_translation）を削除し、この utils 版に一本化する。
その一本化が安全であることを担保するため、utils 版の現挙動をここで固定する。
"""
import pytest

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature, FeatureLocation, AfterPosition, ExactPosition

from apps.ddbj.utils.translation import get_cds_translation_params, get_insdc_translation


class _FakeFeature:
    """get_cds_translation_params は feature.qualifiers しか参照しないため最小フェイクで十分。"""
    def __init__(self, qualifiers):
        self.qualifiers = qualifiers


@pytest.mark.parametrize(
    "qualifiers, default_table_id, expected",
    [
        ({}, 11, (11, 1)),                          # 既定値（クオリファイア無し）
        ({"transl_table": ["11"]}, 1, (11, 1)),     # transl_table が既定を上書き
        ({"transl_table": ["x"]}, 4, (4, 1)),       # 不正な transl_table は既定にフォールバック
        ({}, 0, (1, 1)),                            # table_id 0 は 1 に矯正
        ({"codon_start": ["2"]}, 1, (1, 2)),        # codon_start 解釈
        ({"codon_start": ["5"]}, 1, (1, 1)),        # 不正な codon_start は 1 に矯正
    ],
)
def test_get_cds_translation_params(qualifiers, default_table_id, expected):
    assert get_cds_translation_params(_FakeFeature(qualifiers), default_table_id) == expected


def _cds(seq, start=0, end=None, strand=1, qualifiers=None, end_after=False):
    """CDS フィーチャーと、その配列を持つ SeqRecord を生成する。"""
    end = end if end is not None else len(seq)
    end_pos = AfterPosition(end) if end_after else ExactPosition(end)
    feat = SeqFeature(FeatureLocation(ExactPosition(start), end_pos, strand=strand), type="CDS")
    feat.qualifiers = qualifiers or {}
    return feat, SeqRecord(Seq(seq))


def test_simple_complete_cds():
    # ATG(M) AAA(K) TAA(stop, 末尾除去)
    feat, rec = _cds("ATGAAATAA")
    assert get_insdc_translation(feat, rec, 1, 1) == "MK"


def test_alternative_start_codon_forced_to_m():
    # table 11 で GTG は開始コドン → 強制 M 変換
    feat, rec = _cds("GTGAAATAA")
    assert get_insdc_translation(feat, rec, 11, 1) == "MK"


def test_three_prime_partial_padding():
    # 3' 不完全（AfterPosition）。端数 "GG" → "GGN" は一意に G へ翻訳され付加される
    feat, rec = _cds("ATGGG", end_after=True)
    assert get_insdc_translation(feat, rec, 1, 1) == "MG"


def test_transl_except_selenocysteine():
    # pos:4..6 の TGT(Cys) を Sec(U) に置換 → "MU"（cv_terms 無しでも sec フォールバック）
    feat, rec = _cds("ATGTGTTAA", qualifiers={"transl_except": ["(pos:4..6,aa:Sec)"]})
    assert get_insdc_translation(feat, rec, 1, 1) == "MU"


def test_no_location_returns_none():
    feat = SeqFeature(None, type="CDS")
    feat.qualifiers = {}
    rec = SeqRecord(Seq("ATGAAATAA"))
    assert get_insdc_translation(feat, rec, 1, 1) is None
