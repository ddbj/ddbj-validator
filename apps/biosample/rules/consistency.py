"""属性間の整合・必須群・値妥当性ルール（DB 非依存。フェーズ A 続き）。

- BS_R0036: 「いずれか1つ必須」群（either_one_mandatory）が 1 つも埋まっていない
- BS_R0073: organism / host / isolation_source に冗長（同一）値
- BS_R0135: strain に不適切な値
- BS_R0137: collection_date / geo_loc_name の reporting level term 欠落
"""
import re
from apps.biosample.rules.base import BsRule

_MISSING_RE = re.compile(r"^(not collected|not applicable|missing)(\s*:.*)?$", re.IGNORECASE)
# "missing: <reporting term>" の形（reporting level term あり）
_MISSING_WITH_TERM = re.compile(r"^missing\s*:\s*\S+", re.IGNORECASE)


def _empty(v):
    return v is None or str(v).strip() == ""


def _norm(v):
    return re.sub(r"\s+", " ", str(v).strip().lower()) if v else ""


# strain に使ってはいけない値（case-insensitive）
_INVALID_STRAIN = {
    "bacteria", "clinical isolate", "environmental", "microbial", "no", "soil",
    "sp", "sp.", "strain", "whole organism", "yes",
}


class BS_R0036(BsRule):
    rule_id = "BS_R0036"
    level = "error"
    target = "#attributes"
    description = "Sample has missing attribute(s), at least one of the following attributes is required."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if _empty(rec.package) or context.package_def(rec.package) is None:
                continue
            either = context.either_one_attributes(rec.package)
            if not either:
                continue
            if not any(not _empty(rec.attr(n)) for n in either):
                out.append(self.result(
                    sample=(rec.sample_name or rec.accession),
                    message=f"At least one of the following attributes is required: {', '.join(sorted(either))}"))
        return out


class BS_R0073(BsRule):
    rule_id = "BS_R0073"
    level = "warning"
    target = "organism, host, isolation_source"
    description = "Redundant values are detected in at least two of: organism; host; isolation source."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            vals = {
                "organism": _norm(rec.organism),
                "host": _norm(rec.attr("host")),
                "isolation_source": _norm(rec.attr("isolation_source")),
            }
            present = {k: v for k, v in vals.items() if v}
            seen = {}
            redundant = False
            for k, v in present.items():
                if v in seen:
                    redundant = True
                seen[v] = k
            if redundant:
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message="Redundant values detected among organism/host/isolation_source."))
        return out


class BS_R0135(BsRule):
    rule_id = "BS_R0135"
    level = "error"
    target = "strain"
    description = "Invalid strain value."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            v = rec.attr("strain")
            if _empty(v):
                continue
            low = v.strip().lower()
            bad = low in _INVALID_STRAIN or low.startswith("subsp.") or low.startswith("serovar")
            if not bad and rec.organism and low.startswith(rec.organism.strip().lower()):
                bad = True  # 生物名で始まる strain は不可
            if bad:
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Invalid strain value. (Found: '{v}')"))
        return out


class BS_R0024(BsRule):
    rule_id = "BS_R0024"
    level = "error"
    target = "#attributes"
    description = "Each BioSample must have differentiating information (excluding sample name, title, bioproject accession and description)."

    # 区別情報から除外する属性
    _EXCLUDE = {"sample_name", "sample_title", "bioproject_id", "description"}

    def validate(self, submission, context):
        # 各サンプルの「区別属性」集合（除外属性を除いた name->value）を作り、同一なら冗長
        def key(rec):
            items = []
            for name, vals in rec.attributes.items():
                if name in self._EXCLUDE:
                    continue
                for v in vals:
                    items.append((name, _norm(v)))
            return frozenset(items)

        from collections import Counter
        keys = [key(r) for r in submission.records]
        dup = {k for k, c in Counter(keys).items() if c > 1 and k}
        out = []
        for rec, k in zip(submission.records, keys):
            if k in dup:
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message="BioSample has no differentiating information from another sample in this submission."))
        return out


class BS_R0062(BsRule):
    rule_id = "BS_R0062"
    level = "warning"
    target = "specimen_voucher, culture_collection, bio_material"
    description = "Multiple voucher attributes detected with the same institution code. Only one value is allowed."

    _VOUCHERS = ("culture_collection", "specimen_voucher", "bio_material")

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            # 各 voucher 属性の institution-code（最初の ':' より前）を収集
            inst = {}
            for name in self._VOUCHERS:
                v = rec.attr(name)
                if _empty(v):
                    continue
                code = v.split(":", 1)[0].strip()
                if code:
                    inst.setdefault(code, []).append(name)
            for code, names in inst.items():
                if len(names) > 1:
                    out.append(self.result(sample=(rec.sample_name or rec.accession),
                                           message=f"Multiple voucher attributes with the same institution code '{code}': {', '.join(names)}"))
        return out


class BS_R0137(BsRule):
    rule_id = "BS_R0137"
    level = "error"
    target = "collection_date, geo_loc_name"
    description = 'Missing reporting level term. Provide "missing: reporting level term" when not reported.'

    _TARGETS = ("collection_date", "geo_loc_name")

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            for name in self._TARGETS:
                v = rec.attr(name)
                # 未入力、または missing 系だが reporting term を伴わない場合はエラー
                if _empty(v):
                    out.append(self.result(sample=(rec.sample_name or rec.accession), target=name,
                                           message=f"Missing reporting level term for '{name}'."))
                elif _MISSING_RE.match(v.strip()) and not _MISSING_WITH_TERM.match(v.strip()):
                    out.append(self.result(sample=(rec.sample_name or rec.accession), target=name,
                                           message=f"Missing reporting level term for '{name}'. (Found: '{v}')"))
        return out
