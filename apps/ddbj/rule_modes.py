"""実行モード（skip_db/skip_ncbi/skip_auth）でスキップされるルール ID の正本。

スキップは 2 系統で決まる:
  1) 動的: 各ルールの能力フラグ（requires_rdb / requires_network / requires_auth）。
     validator.py がこれで active_rules をフィルタするのと同じ条件を再現する。
  2) ハードコード補完: フラグでは表現されない「オーケストレータ直接スキップ」や、
     データ未取得で発火しないルール群（DRA/BioSample DB 系・Taxonomy 系・アカウント権限系）。

このモジュールが唯一の正本。テストハーネス（run_tests.py）はここを import し、
独自にリストを持たない（= 二重管理によるドリフトを防ぐ）。新しくモード依存スキップを
追加する場合はここを更新する。
"""

# オーケストレータが直接スキップするアカウント権限チェックルール（requires_auth フラグでは拾えない）
AUTH_CHECK_RULES = {"ANN0422", "ANN0463", "ANN0481"}

# DRA/BioSample 等の内部 DB 必須ルール（skip_db でスキップ。フラグ未設定分の補完）
RDB_HARDCODED = [
    "ANN0500", "ANN0510", "ANN0520", "ANN0530", "ANN0540", "ANN0550",
    "ANN1130",
]

# Taxonomy / ネットワーク必須ルール（skip_ncbi でスキップ。フラグ未設定分の補完）
TAX_HARDCODED = [
    "ANN1025",
    "ANN1070",
    "ANN1430", "ANN1440", "ANN1450", "ANN1460",
    "ANN1810",
    "ANN4210", "ANN4240",
]


import functools
import json
from pathlib import Path

# -w（NSSS web submission）モードで適用しないルール ID の正本は resources/nsss_skip_rules.json。
# 一般ユーザに無関係な内部設定のため、definitions.json とは分離した専用 JSON に置く。
_NSSS_SKIP_PATH = Path(__file__).parent / "resources" / "nsss_skip_rules.json"


@functools.lru_cache(maxsize=1)
def get_web_mode_skip_rules():
    """-w モードで適用しないルール ID の集合を返す（resources/nsss_skip_rules.json の nsss_skip_rules）。"""
    try:
        with open(_NSSS_SKIP_PATH, encoding="utf-8") as f:
            return frozenset(json.load(f).get("nsss_skip_rules", []))
    except Exception as e:
        print(f"Warning: Failed to load nsss_skip_rules.json: {e}")
        return frozenset()


def get_mode_skipped_rules(skip_db=False, skip_ncbi=False, skip_auth=False):
    """指定モードでスキップされるべきルール ID 集合を返す（動的フラグ＋ハードコード補完）。"""
    skipped_rules = set()

    # --- 動的取得: ルールの能力フラグから（validator の active_rules フィルタと同条件） ---
    try:
        from apps.ddbj.validator import Validator
        from apps.ddbj.context import ValidationContext
        val = Validator(ValidationContext(skip_db=False, skip_ncbi=False, skip_auth=False))
        for r in val.active_rules:
            should_skip = (skip_db and getattr(r, 'requires_rdb', False)) or \
                          (skip_ncbi and getattr(r, 'requires_network', False)) or \
                          (skip_auth and (getattr(r, 'requires_auth', False) or getattr(r, 'auth_required', False)))
            if should_skip:
                skipped_rules.add(r.rule_id)
                if hasattr(r, 'sub_rules') and isinstance(r.sub_rules, list):
                    skipped_rules.update(r.sub_rules)
    except Exception as e:
        print(f"Warning: Failed to fetch skipped rules dynamically: {e}")

    # --- ハードコード補完 ---
    if skip_db:
        skipped_rules.update(RDB_HARDCODED)
    if skip_ncbi:
        skipped_rules.update(TAX_HARDCODED)
    if skip_auth:
        skipped_rules.update(AUTH_CHECK_RULES)

    return skipped_rules
