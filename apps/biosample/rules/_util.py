"""biosample ルール共通の小ヘルパ（空・missing 判定・正規化）。

複数ルールで重複していた定義をここへ集約（Tier 1 リファクタ）。挙動は従来どおり。
"""
import re

# missing 値表記: "not collected" / "not applicable" / "missing" / "missing: <reporting term>"
MISSING_RE = re.compile(r"^(not collected|not applicable|missing)(\s*:.*)?$", re.IGNORECASE)
# "missing: <reporting term>"（reporting level term を伴う形）
MISSING_WITH_TERM_RE = re.compile(r"^missing\s*:\s*\S+", re.IGNORECASE)


def is_empty(v):
    """None または空白のみなら True。"""
    return v is None or str(v).strip() == ""


def is_missing_value(v):
    """値が missing 系表記（not collected/not applicable/missing[: term]）なら True。"""
    return bool(MISSING_RE.match(v.strip())) if v else False


def is_missing_without_term(v):
    """missing 系だが reporting level term（"missing: xxx"）を伴わない場合 True。"""
    if not v:
        return False
    s = v.strip()
    return bool(MISSING_RE.match(s)) and not MISSING_WITH_TERM_RE.match(s)


def norm(v):
    """空白正規化＋小文字化（値の同一性比較用）。"""
    return re.sub(r"\s+", " ", str(v).strip().lower()) if v else ""
