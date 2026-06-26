"""common/format.py の純関数（日付・lat_lon フォーマット補正）の挙動を固定するユニットテスト。

提案 C（翻訳/位置ロジックの一本化）に着手する前の安全網（提案 F.1）として、
副作用のない純関数の現挙動をゴールデン値で固定する。
実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import pytest

from common.format import fix_insdc_date, fix_insdc_lat_lon, _parse_and_format_date


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2021", "2021"),                       # 年のみ
        ("2021-03", "2021-03"),                 # 年月
        ("2021-03-05", "2021-03-05"),           # 年月日
        ("2021/03/05", "2021-03-05"),           # '/' は区切り正規化（範囲扱いしない）
        ("05-Mar-2021", "2021-03-05"),          # 月名表記
        ("2020/2021", "2020/2021"),             # 範囲（昇順）
        ("2021/2020", "2020/2021"),             # 範囲（逆順 → 並べ替え）
        ("not a date", "not a date"),           # 解釈不能 → 原文返し
        ("", ""),                               # 空文字
    ],
)
def test_fix_insdc_date(value, expected):
    assert fix_insdc_date(value) == expected


def test_parse_and_format_date_returns_none_on_failure():
    s, dt = _parse_and_format_date("not a date")
    assert s is None
    assert dt is None


def test_parse_and_format_date_year_granularity():
    s, _ = _parse_and_format_date("2021")
    assert s == "2021"


@pytest.mark.parametrize(
    "value, expected",
    [
        ("35 39 29 N 139 41 30 E", "35.6581 N 139.6917 E"),   # DMS → 10進
        ("35.6581 N 139.6917 E", "35.6581 N 139.6917 E"),     # INSDC 10進そのまま
        ("N 35.6581 E 139.6917", "35.6581 N 139.6917 E"),     # 半球前置 → 並べ替え
        (None, None),                                          # None
        ("", None),                                            # 空
        ("garbage", None),                                     # 認識不能
    ],
)
def test_fix_insdc_lat_lon(value, expected):
    assert fix_insdc_lat_lon(value) == expected
