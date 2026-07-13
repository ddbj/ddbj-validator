"""GEA の BioSample ↔ SDRF 双方向 autofix。共通実装は common/magetab/bs_autofix。

値不一致ルール = GEA_BS0003。confirmation タイトル = "GEA"。mb と同じ仕様。
"""
from common.magetab import bs_autofix as _af

_RULE_ID = "GEA_BS0003"
_TITLE = "GEA"

review = _af.review
apply_bs2sdrf = _af.apply_bs2sdrf
build_ssub_tsvs = _af.build_ssub_tsvs


def build_proposals(results):
    return _af.build_proposals(results, _RULE_ID)


def write_confirmation(proposals, out_dir):
    return _af.write_confirmation(proposals, out_dir, _TITLE)
