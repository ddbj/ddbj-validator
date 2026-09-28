"""互換の再エクスポート。実体は common/magetab/charnorm.py（2026-09-26 に移動）。

GEA でも同じ正規化を使うようになったため common へ寄せた。旧 import を壊さないための薄い層。
"""
from common.magetab.charnorm import (  # noqa: F401
    normalize, fix_warning_message, residual_error_message,
)
