"""INSDC の missing/null 値判定（ddbj / biosample 共通）。

CV は common/resources/definitions.json の cv_terms を単一ソースとする:
- missing_terms          : "missing" / "not applicable" / "not collected" / "not provided" / "restricted access"
- missing_reporting_terms: "missing: control sample" 等（missing に付く reporting level term）

従来 biosample 側は正規表現をハードコードしており、'not provided'/'restricted access' を取りこぼす齟齬が発生した。
JSON を単一ソースにして両 app で共有する。
"""
import re
from common.definitions import load_common_cv_terms

# definitions.json が読めない場合のフォールバック（INSDC 既定の missing base terms）
_FALLBACK_MISSING = ["missing", "not applicable", "not collected", "not provided", "restricted access"]


def _build():
    cv = load_common_cv_terms()
    base = [t.lower() for t in cv.get("missing_terms", [])] or _FALLBACK_MISSING
    reporting = {t.lower() for t in cv.get("missing_reporting_terms", [])}
    # base term（長いものから）で始まり、任意で ": ..."（reporting term）が続く形にマッチ
    alt = "|".join(re.escape(t) for t in sorted(base, key=len, reverse=True))
    pattern = re.compile(rf"^({alt})(\s*:.*)?$", re.IGNORECASE)
    return base, reporting, pattern


_BASE, _REPORTING, MISSING_RE = _build()
# "missing: <reporting term>"（term を伴う形）
MISSING_WITH_TERM_RE = re.compile(r"^missing\s*:\s*\S+", re.IGNORECASE)


def is_missing_value(v):
    """v が INSDC の missing/null 値（base term、または "missing: <term>" 形）なら True。"""
    return bool(MISSING_RE.match(v.strip())) if v else False


def is_missing_without_term(v):
    """missing 系だが reporting level term（"missing: xxx"）を伴わない場合 True。"""
    if not v:
        return False
    s = v.strip()
    return bool(MISSING_RE.match(s)) and not MISSING_WITH_TERM_RE.match(s)


def reporting_terms():
    """有効な "missing: <reporting term>" 集合（小文字）。R0137 / ddbj date reporting term で共用。"""
    return set(_REPORTING)


def is_valid_reporting_term(v):
    """v が有効な "missing: <reporting term>"（CV: missing_reporting_terms）なら True。"""
    return bool(v) and v.strip().lower() in _REPORTING


# 空白を除去した reporting term 集合（"missing:humanidentifiable" 形）。
# スペースだけの差を吸収した照合に使う。
_REPORTING_NS = {re.sub(r"\s+", "", t.lower()) for t in _REPORTING}


def is_reporting_term_normalizable(v):
    """v が「空白を補えば有効な "missing: <reporting term>" になる」値なら True。

    例: "missing:human-identifiable"（コロン後スペース無し）→ True。
    これは R0001 の autofix（normalize_null）が正規表記へ直せる値と一致する。
    完全に無効な term（"missing" 単独 / "missing: 無効語" / "missing:"）は False。
    """
    return bool(v) and re.sub(r"\s+", "", v.strip().lower()) in _REPORTING_NS


def normalize_null(val, null_accepted, null_not_recommended, date_or_geo):
    """missing 値の表記揺れ/非推奨値を正規表記へ補正した値を返す（不要なら None）。Ruby rule:1 準拠。
    biosample R0001（必須属性の missing 値正規化）で使用。null_accepted / null_not_recommended は呼び出し側から渡す。
    """
    result = None
    low = val.lower()
    low_ns = low.replace(" ", "")
    # 推奨 null 値（"missing: control sample" 等）の表記を揃える
    for accepted in null_accepted:
        prefix = accepted.split(":")[0].lower()
        suffix = "".join(accepted.split(":")[1:]).replace(" ", "").lower()
        if low.startswith(prefix) and low_ns.endswith(suffix):
            if date_or_geo and not accepted.startswith("missing:"):
                continue  # date/geo は "missing" 等の無用な置換をしない
            result = accepted
    # 非推奨 null 値（"N.A." 等）を "missing" へ（date/geo は対象外）
    if not date_or_geo:
        for pat in null_not_recommended:
            try:
                if re.fullmatch(pat, val, re.I):
                    result = "missing"
                    break
            except re.error:
                continue
    if result is None or result == val:
        return None
    return result
