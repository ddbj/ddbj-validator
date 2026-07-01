"""属性間の整合・必須群・値妥当性ルール（DB 非依存。フェーズ A 続き）。

- BS_R0036: 「いずれか1つ必須」群（either_one_mandatory）が 1 つも埋まっていない
- BS_R0073: organism / host / isolation_source に冗長（同一）値
- BS_R0135: strain に不適切な値
- BS_R0137: collection_date / geo_loc_name の reporting level term 欠落
"""
import re
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import (
    is_empty as _empty,
    norm as _norm,
    is_missing_without_term,
    is_missing_value as _is_missing,
)


def _normalize_missing_value(val, null_accepted, null_not_recommended, date_or_geo):
    """missing 値の表記揺れ/非推奨値を正規表記へ補正した値を返す（不要なら None）。Ruby rule:1 準拠。"""
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
                elif is_missing_without_term(v):
                    out.append(self.result(sample=(rec.sample_name or rec.accession), target=name,
                                           message=f"Missing reporting level term for '{name}'. (Found: '{v}')"))
        return out


def _no_meaningful_identifier(rec, attrs):
    """attrs のいずれにも「意味のある値」（非空・非 missing）が無ければ True。"""
    for a in attrs:
        v = rec.attr(a)
        if not _empty(v) and not _is_missing(v):
            return False
    return True


class BS_R0001(BsRule):
    rule_id = "BS_R0001"
    level = "warning"
    target = "#attributes"
    description = "Invalid missing value."

    def validate(self, submission, context):
        # 必須属性（either_one 含む）の値が missing 値の表記揺れ/非推奨値なら正規表記へ補正（autofix）。
        # 任意属性は R0100 の領分のため対象外。
        na = list(context.cv_terms.get("missing_terms", [])) + \
            list(context.cv_terms.get("missing_reporting_terms", []))
        nnr = context.null_not_recommended or []
        if not na and not nnr:
            return []
        out = []
        for rec in submission.records:
            if not rec.package or context.package_def(rec.package) is None:
                continue
            mandatory = context.mandatory_attributes(rec.package) | context.either_one_attributes(rec.package)
            for name in sorted(mandatory):
                date_or_geo = name in ("collection_date", "geo_loc_name")
                for v in rec.attr_values(name):
                    if _empty(v):
                        continue
                    fixed = _normalize_missing_value(v, na, nnr, date_or_geo)
                    if fixed:
                        out.append(self.result(
                            sample=(rec.sample_name or rec.accession), target=name,
                            message=f"Invalid missing value. ({name}: '{v}', Suggested: '{fixed}')",
                            autofix=True, attribute=name, old_value=v, new_value=fixed))
        return out


class BS_R0132(BsRule):
    rule_id = "BS_R0132"
    level = "error"
    target = "strain, isolate, cultivar and ecotype"
    description = "Null value for infraspecific identifier."

    # ゲノム/clinical 系パッケージ（前方一致）で、種以下識別子に意味のある値が必須
    _PKG = {
        "MIGS.ba": ["strain"],
        "MIGS.eu": ["strain", "isolate", "cultivar", "ecotype"],
        "MIGS.vi": ["strain", "isolate"],
        "MIMAG": ["isolate"],
        "MISAG": ["isolate"],
        "MIUVIG": ["isolate"],
        "SARS-CoV-2.cl": ["isolate"],
        "Pathogen.cl": ["strain", "isolate"],
    }

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.package:
                continue
            for pfx, attrs in self._PKG.items():
                if rec.package.startswith(pfx) and _no_meaningful_identifier(rec, attrs):
                    out.append(self.result(
                        sample=(rec.sample_name or rec.accession),
                        message=f"Null value for infraspecific identifier. (package: {rec.package}, attributes: {'/'.join(attrs)})"))
        return out


class BS_R0133(BsRule):
    rule_id = "BS_R0133"
    level = "warning"
    target = "strain, isolate"
    description = "Null value for infraspecific identifier."

    _PKG = {"Microbe": ["strain", "isolate"]}

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            if not rec.package:
                continue
            for pfx, attrs in self._PKG.items():
                if rec.package.startswith(pfx) and _no_meaningful_identifier(rec, attrs):
                    out.append(self.result(
                        sample=(rec.sample_name or rec.accession),
                        message=f"Null value for infraspecific identifier. (package: {rec.package}, attributes: {'/'.join(attrs)})"))
        return out
