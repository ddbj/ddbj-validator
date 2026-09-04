"""JST（日本標準時）の「現在」を返す共通ヘルパー。

DDBJ / MetaboBank などに投稿される日付（collection_date, Public Release Date, hold_date 等）は
JST で書かれる。一方 validator のコンテナは UTC で動くため、`datetime.date.today()` を使うと
JST 00:00〜09:00 の間は「今日」が前日になり、当日の日付が未来日と誤判定される。

未来日判定・締切判定はこのモジュールの `today()` を使うこと。
"""
import datetime

JST = datetime.timezone(datetime.timedelta(hours=9))


def now(at=None):
    """JST の現在時刻（tz-aware）。at にタイムゾーン付き datetime を渡すとそれを JST に変換する。"""
    return (at or datetime.datetime.now(datetime.timezone.utc)).astimezone(JST)


def today(at=None):
    """JST における「今日」の日付。コンテナの TZ に依存しない。"""
    return now(at).date()
