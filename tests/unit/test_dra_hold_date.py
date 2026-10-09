"""DRA の submission の公開予定日（DRA_R0006 が見る hold_date）の決め方を固定する。

ACTIONS は書かれた順に行われるので、@target の無い HOLD と RELEASE のうち最後のものが効いている。
DDBJ Record の submission.hold_date も同じ規則で決まる（ddbj/ddbj-record-specifications#14）。

実行: リポジトリルートで `.venv/bin/python -m pytest tests/unit`
"""
import pytest

from apps.dra import xml_reader


def _submission(tmp_path, actions):
    path = tmp_path / "sub.xml"
    path.write_text(f'<SUBMISSION alias="s"><ACTIONS>{actions}</ACTIONS></SUBMISSION>', encoding="utf-8")
    submission, _ = xml_reader.parse_files([str(path)])
    return submission.submission


@pytest.mark.parametrize("actions, expected", [
    ('<ACTION><HOLD HoldUntilDate="2030-01-01"/></ACTION>', "2030-01-01"),
    # 最後のものが効く。
    ('<ACTION><HOLD HoldUntilDate="2030-01-01"/></ACTION>'
     '<ACTION><HOLD HoldUntilDate="2031-01-01"/></ACTION>', "2031-01-01"),
    # 後から RELEASE すれば公開予定日は無い。
    ('<ACTION><HOLD HoldUntilDate="2030-01-01"/></ACTION><ACTION><RELEASE/></ACTION>', None),
    ('<ACTION><RELEASE/></ACTION><ACTION><HOLD HoldUntilDate="2030-01-01"/></ACTION>', "2030-01-01"),
    # @target の付いた HOLD は個々の object の話で、submission の日付ではない。
    ('<ACTION><HOLD target="DRX000001" HoldUntilDate="2040-01-01"/></ACTION>', None),
    ('<ACTION><HOLD HoldUntilDate="2030-01-01"/></ACTION>'
     '<ACTION><HOLD target="DRX000001" HoldUntilDate="2040-01-01"/></ACTION>', "2030-01-01"),
    # 日付の無い HOLD（期間だけ）は日付を残さない。
    ('<ACTION><HOLD HoldForPeriod="365"/></ACTION>', None),
    ('<ACTION><ADD source="exp.xml" schema="experiment"/></ACTION>', None),
])
def test_hold_date_is_the_last_untargeted_hold_or_release(tmp_path, actions, expected):
    assert _submission(tmp_path, actions).hold_date == expected
