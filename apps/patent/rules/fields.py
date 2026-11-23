"""entry から特許の項目（KEYWORD / REFERENCE / COMMENT / source）を取り出す共通処理。

規則ごとに同じ走査を繰り返さないよう、結果を record に持たせて使い回す（数百万 entry を回すため）。
"""
import re
from datetime import date

from apps.patent.constants import DATE_NOT_PROVIDED

_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_DATE_RE = re.compile(r"^(\d{2})-([A-Z]{3})-(\d{4})$")

# 公報番号つきの配列の名前: <庁 2 文字> <番号>-<種別>/<配列番号>（例 `JP 2026524816-A/1`、種別は A や A5）
KEYWORD_RE = re.compile(r"^([A-Z]{2}) ([0-9A-Za-z]+)-([A-Z][0-9]?)/([0-9]+)$")
# REFERENCE の最初の journal: Patent: <庁> <番号>-<種別> <配列番号> DD-MON-YYYY;
JOURNAL_RE = re.compile(r"^Patent: ([A-Z]{2}) ([0-9A-Za-z]+)-([A-Z][0-9]?) ([0-9]+) (\d{2}-[A-Z]{3}-\d{4});$")


def parse_date(text):
    """`DD-MON-YYYY`（月は大文字の英 3 文字）を date にする。形が違う・実在しない日は None。"""
    m = _DATE_RE.match(text)
    if not m or m.group(2) not in _MONTHS:
        return None
    try:
        return date(int(m.group(3)), _MONTHS[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


class PatentFields:
    """1 entry の特許の項目。値は parser が読んだまま（前後の空白だけ取れている）。"""
    __slots__ = ("keyword_feats", "reference_feats", "comment_feats", "source_feats",
                 "keywords", "titles", "journals", "lines", "tags")

    def __init__(self, record):
        by_type = getattr(record, "features_by_type", None) or {}
        self.keyword_feats = by_type.get("KEYWORD", [])
        self.reference_feats = by_type.get("REFERENCE", [])
        self.comment_feats = by_type.get("COMMENT", [])
        self.source_feats = by_type.get("source", [])
        self.keywords = [v for f in self.keyword_feats for v in f.qualifiers.get("keyword", [])]
        self.titles = [v for f in self.reference_feats for v in f.qualifiers.get("title", [])]
        self.journals = [v for f in self.reference_feats for v in f.qualifiers.get("journal", [])]
        self.lines = [v for f in self.comment_feats for v in f.qualifiers.get("line", [])]
        # タグ（行の頭 2 文字）→ 値のリスト（タグと空白を除いた残り）
        self.tags = {}
        for line in self.lines:
            self.tags.setdefault(line[:2], []).append(line[2:].strip())

    def first_token(self, tag):
        """タグの最初の行の、最初の語（日付の欄）。行が無ければ None。"""
        values = self.tags.get(tag)
        if not values:
            return None
        return values[0].split(None, 1)[0] if values[0] else ""

    def date_of(self, tag):
        """タグの最初の行の日付。行が無い・NOT_PROVIDED・読めないときは None。"""
        token = self.first_token(tag)
        if not token or token == DATE_NOT_PROVIDED:
            return None
        return parse_date(token)


def patent_fields(record):
    fields = getattr(record, "_patent_fields", None)
    if fields is None:
        fields = PatentFields(record)
        record._patent_fields = fields
    return fields
