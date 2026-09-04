"""値形式ルール（DB 非依存。フェーズ A）。

- BS_R0007: collection_date が ISO8601 形式でない
- BS_R0040: collection_date が未来日
- BS_R0009: lat_lon の形式不正
- BS_R0093: 整数であるべき属性が非整数（taxonomy_id, host_spec_range, host_taxid, num_replicons）
missing 値（not collected / not applicable / missing[: term]）は値検証の対象外（別ルールで扱う）。
"""
import datetime
import re
from dateutil import parser as _dateutil_parser
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value
# collection_date の形式判定・autofix は ddbj と共通（共有属性は ddbj v に倣う）。
# INSDC_DATE_PATTERN は ddbj definitions.json の format_pattern と同一の共有定数。
from common.format import fix_insdc_date, fix_insdc_lat_lon, INSDC_DATE_PATTERN, latlon_in_range
from common.jst import today as jst_today

# lat_lon: "d[d.ddd] N|S d[dd.ddd] W|E"（範囲外 90/180 超は latlon_in_range で別途弾く）
_LATLON_RE = re.compile(r"^\d{1,3}(\.\d+)?\s+[NS]\s+\d{1,3}(\.\d+)?\s+[EW]$")

_INTEGER_ATTRS = ("taxonomy_id", "host_spec_range", "host_taxid", "num_replicons")

# publication identifier: PubMed(数字) / DOI(10.xxxx/...) / URL
_PUB_RE = re.compile(r"^(\d+|10\.\d+/\S+|https?://\S+)$", re.IGNORECASE)

# sample_name 許可文字: 英数字・空白・(){}[]+-_.（最大 100 文字）
_SAMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9 (){}\[\]+\-_.]{1,100}$")


class BS_R0101(BsRule):
    rule_id = "BS_R0101"
    level = "error"
    target = "sample_name"
    description = "Maximum length of Sample Name is 100 characters (alphanumeric, spaces and (){}[]+-_.)."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.sample_name
            if not v:
                continue
            if not _SAMPLE_NAME_RE.match(v):
                reason = "too long (>100)" if len(v) > 100 else "invalid characters"
                out.append(self.result(sample=rec.sample_id,
                                       message=f"Invalid Sample Name format ({reason})."))
        return out


def _date_valid(v):
    """collection_date が INSDC 形式（ddbj と共有の正規表現）に一致するか。
    ddbj v は形式チェックを正規表現マッチのみで行う（意味的な月日範囲は検証しない）。"""
    return bool(INSDC_DATE_PATTERN.match(v.strip()))


def _date_fixable(v):
    """autofix で INSDC 形式へ直せるなら補正値を返す（不可なら None）。fix_insdc_date は ddbj と共通。"""
    fixed = fix_insdc_date(v)
    if fixed and fixed != v and _date_valid(fixed):
        return fixed
    return None


class BS_R0007(BsRule):
    rule_id = "BS_R0007"
    level = "error"
    target = "collection_date"
    description = 'Invalid datetime. Follow ISO 8601 "YYYY", "YYYY-MM", "YYYY-MM-DD" or "YYYY-MM-DDThh:mm:ssZ".'

    def validate(self, submission, context):
        # 形式判定は ddbj と共通の INSDC_DATE_PATTERN。自動補正可能な値は R0136 に委ね R0007 は抑制。
        out = []
        for rec in submission.records:
            v = rec.attr("collection_date")
            if not v or is_missing_value(v):
                continue
            if _date_valid(v):
                continue
            if _date_fixable(v):
                continue  # 補正可能 → R0136 が扱う
            out.append(self.result(sample=rec.sample_id,
                                   attribute="collection_date", old_value=v,
                                   message=f"Invalid datetime. (Found: '{v}')"))
        return out


class BS_R0136(BsRule):
    rule_id = "BS_R0136"
    level = "warning"
    target = "collection_date"
    description = "Invalid datetime format."

    def validate(self, submission, context):
        # 形式不一致だが共通補正で INSDC 形式へ直せる場合の autofix 提案（R0007 の autofix 版）。
        out = []
        for rec in submission.records:
            v = rec.attr("collection_date")
            if not v or is_missing_value(v) or _date_valid(v):
                continue
            fixed = _date_fixable(v)
            if fixed:
                out.append(self.autofix_result(
                    sample=rec.sample_id,
                    message=f"Invalid datetime format. (Found: '{v}', Suggested: '{fixed}')",
                    attribute="collection_date", old_value=v, new_value=fixed))
        return out


class BS_R0040(BsRule):
    rule_id = "BS_R0040"
    level = "error"
    target = "collection_date"
    description = "Sample collection date is a future date, please specify a date from the past."

    def validate(self, submission, context):
        # 未来日判定は ddbj ANN1240 に倣う。範囲(/)・missing は対象外。粒度（年/年月/年月日）ごとに比較。
        out = []
        # 投稿日付は JST。コンテナが UTC だと JST 00:00〜09:00 の間だけ当日が未来日になる
        today = jst_today()
        for rec in submission.records:
            v = rec.attr("collection_date")
            if not v or is_missing_value(v):
                continue
            s = v.strip()
            if s.startswith("missing:") or "/" in s:
                continue
            if not re.search(r"\d{4}", s):
                continue  # 4桁年が無い（例 "Dec-16"）は年を推測できず未来日判定しない（R0007 の領分）
            try:
                dt = _dateutil_parser.parse(re.sub(r"[\s.,]+", "-", s))
            except Exception:
                continue
            has_time = "T" in s.upper() or ":" in s
            has_month_word = bool(re.search(r"[A-Za-z]{3,}", s))
            comp = 3 if has_time else len(re.findall(r"\d+", s)) + (1 if has_month_word else 0)
            if comp == 1:
                future = dt.year > today.year
            elif comp == 2:
                future = (dt.year, dt.month) > (today.year, today.month)
            else:
                future = (dt.year, dt.month, dt.day) > (today.year, today.month, today.day)
            if future:
                out.append(self.result(sample=rec.sample_id,
                                       attribute="collection_date", old_value=v,
                                       message=f"Sample collection date is a future date. (Found: '{v}')"))
        return out


class BS_R0009(BsRule):
    rule_id = "BS_R0009"
    level = "warning"
    target = "lat_lon"
    description = 'Invalid lat_lon format. Specify as "d[d.dddd] N|S d[dd.dddd] W|E".'

    def validate(self, submission, context):
        # 正準形式でないが共通補正（fix_insdc_lat_lon: 8桁切り捨て対応）で直せる場合、autofix 提案。
        # 直せない場合は R0139（error）が担当する（R0002/R0138 と同型の warning/error 分担）。
        out = []
        for rec in submission.records:
            v = rec.attr("lat_lon")
            if not v or is_missing_value(v):
                continue
            if latlon_in_range(v):
                continue  # 既に正準かつ範囲内
            fixed = fix_insdc_lat_lon(v)
            if fixed and latlon_in_range(fixed):
                out.append(self.autofix_result(
                    sample=rec.sample_id,
                    message=f"Invalid lat_lon format. (Found: '{v}', Suggested: '{fixed}')",
                    attribute="lat_lon", old_value=v, new_value=fixed))
        return out


class BS_R0139(BsRule):
    rule_id = "BS_R0139"
    level = "error"
    target = "lat_lon"
    description = 'Invalid lat_lon. Specify as "d[d.dddddddd] N|S d[dd.dddddddd] W|E".'

    def validate(self, submission, context):
        # 正準形式でなく、共通補正でも直せない lat_lon はエラー（R0009 の error 版）
        out = []
        for rec in submission.records:
            v = rec.attr("lat_lon")
            if not v or is_missing_value(v):
                continue
            if latlon_in_range(v):
                continue  # 正準かつ範囲内 → OK
            fixed = fix_insdc_lat_lon(v)
            if not (fixed and latlon_in_range(fixed)):
                # 形式不正、または範囲外（緯度>90/経度>180 の "200 N 400 E" 等）で補正不能 → error
                out.append(self.result(sample=rec.sample_id,
                                       attribute="lat_lon", old_value=v,
                                       message=f"Invalid lat_lon. (Found: '{v}')"))
        return out


class BS_R0011(BsRule):
    rule_id = "BS_R0011"
    level = "warning"
    target = "ref_biomaterial OR isol_growth_condt"
    description = "Invalid publication identifier, enter pubmed id, DOI or URL."

    _TARGETS = ("ref_biomaterial", "isol_growth_condt")

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for name in self._TARGETS:
                v = rec.attr(name)
                if not v or is_missing_value(v):
                    continue
                # "unpublished"（大文字小文字無視）は本ルール特異的に許容（pub id 未発表の慣用表記）
                if v.strip().lower() == "unpublished":
                    continue
                if not _PUB_RE.match(v.strip()):
                    out.append(self.result(sample=rec.sample_id, target=name,
                                           attribute=name, old_value=v,
                                           message=f"Invalid publication identifier. ({name}: '{v}')"))
        return out


class BS_R0093(BsRule):
    rule_id = "BS_R0093"
    level = "error"
    target = "taxonomy_id, host_spec_range, host_taxid, num_replicons"
    description = "Attribute value must be integer."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            checks = {name: rec.attr(name) for name in _INTEGER_ATTRS}
            checks["taxonomy_id"] = checks.get("taxonomy_id") or rec.taxonomy_id
            for name, v in checks.items():
                if not v or is_missing_value(v):
                    continue
                if not str(v).strip().isdigit():
                    out.append(self.result(sample=rec.sample_id, target=name,
                                           attribute=name, old_value=v,
                                           message=f"Attribute value must be integer. ({name}: '{v}')"))
        return out
