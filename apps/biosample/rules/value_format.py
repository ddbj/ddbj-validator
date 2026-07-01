"""値形式ルール（DB 非依存。フェーズ A）。

- BS_R0007: collection_date が ISO8601 形式でない
- BS_R0040: collection_date が未来日
- BS_R0009: lat_lon の形式不正
- BS_R0093: 整数であるべき属性が非整数（taxonomy_id, host_spec_range, host_taxid, num_replicons）
missing 値（not collected / not applicable / missing[: term]）は値検証の対象外（別ルールで扱う）。
"""
import datetime
import re
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value as _is_missing
from common.format import fix_insdc_date, fix_insdc_lat_lon

# ISO8601: YYYY-mm-dd / YYYY-mm / YYYY-mm-ddThh:mm:ssZ
_DATE_FULL = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_YM = re.compile(r"^\d{4}-\d{2}$")
_DATE_DT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# lat_lon: "d[d.ddd] N|S d[dd.ddd] W|E"
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
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Invalid Sample Name format ({reason})."))
        return out


def _parse_date(v):
    """collection_date を date へ。解釈不能なら None。"""
    try:
        if _DATE_FULL.match(v):
            return datetime.datetime.strptime(v, "%Y-%m-%d").date()
        if _DATE_YM.match(v):
            return datetime.datetime.strptime(v + "-01", "%Y-%m-%d").date()
        if _DATE_DT.match(v):
            return datetime.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").date()
    except ValueError:
        return None
    return None


class BS_R0007(BsRule):
    rule_id = "BS_R0007"
    level = "error"
    target = "collection_date"
    description = 'Invalid datetime. Follow ISO 8601 "YYYY-mm-dd", "YYYY-mm" or "YYYY-mm-ddThh:mm:ssZ".'

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("collection_date")
            if not v or _is_missing(v):
                continue
            if _parse_date(v) is None:
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Invalid datetime. (Found: '{v}')"))
        return out


class BS_R0136(BsRule):
    rule_id = "BS_R0136"
    level = "warning"
    target = "collection_date"
    description = "Invalid datetime format."

    def validate(self, submission, context):
        # collection_date が ISO8601 でないが共通補正で妥当な形式に直せる場合、autofix 提案（R0007 の autofix 版）
        out = []
        for rec in submission.records:
            v = rec.attr("collection_date")
            if not v or _is_missing(v):
                continue
            if _parse_date(v) is not None:
                continue  # 既に妥当
            fixed = fix_insdc_date(v)
            if fixed and fixed != v and _parse_date(fixed) is not None:
                out.append(self.result(
                    sample=(rec.sample_name or rec.accession),
                    message=f"Invalid datetime format. (Found: '{v}', Suggested: '{fixed}')",
                    autofix=True, attribute="collection_date", old_value=v, new_value=fixed))
        return out


class BS_R0040(BsRule):
    rule_id = "BS_R0040"
    level = "error"
    target = "collection_date"
    description = "Sample collection date is a future date, please specify a date from the past."

    def validate(self, submission, context):
        out = []
        today = datetime.date.today()
        for rec in submission.records:
            v = rec.attr("collection_date")
            if not v or _is_missing(v):
                continue
            d = _parse_date(v)
            if d is not None and d > today:
                out.append(self.result(sample=(rec.sample_name or rec.accession),
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
            if not v or _is_missing(v):
                continue
            if _LATLON_RE.match(v):
                continue  # 既に正準
            fixed = fix_insdc_lat_lon(v)
            if fixed and _LATLON_RE.match(fixed):
                out.append(self.result(
                    sample=(rec.sample_name or rec.accession),
                    message=f"Invalid lat_lon format. (Found: '{v}', Suggested: '{fixed}')",
                    autofix=True, attribute="lat_lon", old_value=v, new_value=fixed))
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
            if not v or _is_missing(v):
                continue
            if _LATLON_RE.match(v):
                continue
            fixed = fix_insdc_lat_lon(v)
            if not (fixed and _LATLON_RE.match(fixed)):
                out.append(self.result(sample=(rec.sample_name or rec.accession),
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
                if not v or _is_missing(v):
                    continue
                if not _PUB_RE.match(v.strip()):
                    out.append(self.result(sample=(rec.sample_name or rec.accession), target=name,
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
                if not v or _is_missing(v):
                    continue
                if not str(v).strip().isdigit():
                    out.append(self.result(sample=(rec.sample_name or rec.accession), target=name,
                                           message=f"Attribute value must be integer. ({name}: '{v}')"))
        return out
