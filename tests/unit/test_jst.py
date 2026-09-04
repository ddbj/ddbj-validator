"""JST の「今日」判定（common/jst.py）と、それを使う未来日ルールのユニットテスト。

投稿日付は JST で書かれるが validator のコンテナは UTC で動く。`datetime.date.today()` を
使っていると JST 00:00〜09:00 の間だけ当日が「未来日」と誤判定され、毎朝 9 時間だけ
公開済み study の更新が全部 error になっていた（MetaboBank MB_IR0033 で顕在化）。

実行: リポジトリルートで `.venv/bin/python -m pytest`
"""
import datetime

import pytest

from common.jst import JST, now, today

UTC = datetime.timezone.utc


def test_jst_offset_is_plus_9():
    assert JST.utcoffset(None) == datetime.timedelta(hours=9)


@pytest.mark.parametrize("utc_instant, expected", [
    # JST 00:00〜09:00 は UTC ではまだ前日。ここが誤判定の起きていた窓。
    (datetime.datetime(2026, 9, 4, 15, 0, tzinfo=UTC), datetime.date(2026, 9, 5)),   # JST 09-05 00:00
    (datetime.datetime(2026, 9, 4, 23, 30, tzinfo=UTC), datetime.date(2026, 9, 5)),  # JST 09-05 08:30
    (datetime.datetime(2026, 9, 4, 14, 59, tzinfo=UTC), datetime.date(2026, 9, 4)),  # JST 09-04 23:59
    (datetime.datetime(2026, 9, 5, 0, 30, tzinfo=UTC), datetime.date(2026, 9, 5)),   # JST 09-05 09:30
])
def test_today_converts_utc_instant_to_jst_date(utc_instant, expected):
    assert today(utc_instant) == expected


def test_now_returns_jst_aware_datetime():
    assert now(datetime.datetime(2026, 9, 4, 23, 30, tzinfo=UTC)) == \
        datetime.datetime(2026, 9, 5, 8, 30, tzinfo=JST)


def test_today_is_tz_independent(monkeypatch):
    """プロセスの TZ 設定を変えても JST の日付が返ること（コンテナが UTC でも同じ）。"""
    import time
    for tz in ("Asia/Tokyo", "UTC", "America/New_York"):
        monkeypatch.setenv("TZ", tz)
        time.tzset()
        assert today() == datetime.datetime.now(JST).date()
    monkeypatch.undo()
    time.tzset()


# --- MB_IR0033（未来日）が JST 基準で判定されること ---------------------------

def _mb_sub(public_release_date):
    from common.magetab.model import Idf, Submission
    idf = Idf()
    idf.fields = {"Public Release Date": [public_release_date]}
    idf.field_order = ["Public Release Date"]
    return Submission(idf=idf, sdrf=None)


def _mb_fired(date_str, fake_today):
    from apps.metabobank.context import ValidationContext
    from apps.metabobank.rules import idf as idf_rules
    rule = idf_rules.MB_IR0033()
    orig = idf_rules.jst_today
    idf_rules.jst_today = lambda: fake_today
    try:
        return rule.validate(_mb_sub(date_str), ValidationContext(skip_db=True, skip_ncbi=True, skip_auth=True))
    finally:
        idf_rules.jst_today = orig


def test_mb_ir0033_allows_today_jst():
    """JST の当日は未来日ではない（UTC 基準だと前日扱いで誤検出していたケース）。"""
    assert _mb_fired("2026-09-05", datetime.date(2026, 9, 5)) == []


def test_mb_ir0033_flags_tomorrow():
    """翌日以降は従来どおり error。"""
    res = _mb_fired("2026-09-06", datetime.date(2026, 9, 5))
    assert len(res) == 1 and res[0]["rule_id"] == "MB_IR0033"
