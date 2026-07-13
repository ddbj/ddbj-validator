"""MetaboBank の BioSample ↔ SDRF 双方向 autofix。共通実装は common/magetab/bs_autofix。

値不一致ルール = MB_SR0023。confirmation タイトル = "MetaboBank"。
"""
from common.magetab import bs_autofix as _af

_RULE_ID = "MB_SR0023"
_TITLE = "MetaboBank"

# 後方互換（既存 import 名を維持）
review = _af.review
apply_bs2sdrf = _af.apply_bs2sdrf
build_ssub_tsvs = _af.build_ssub_tsvs


def build_proposals(results):
    return _af.build_proposals(results, _RULE_ID)


def write_confirmation(proposals, out_dir):
    return _af.write_confirmation(proposals, out_dir, _TITLE)
