"""地理情報ルール（country CV 依存・DB 非依存。フェーズ A 続き）。

- BS_R0008: geo_loc_name の国名部分が controlled country list に無い
country CV は common/resources/definitions.json の cv_terms.countries / historical_countries を使用。
lat_lon ↔ country 矛盾（R0041）は geopandas 依存のため別バッチ。
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value


class BS_R0008(BsRule):
    rule_id = "BS_R0008"
    level = "error"
    target = "geo_loc_name"
    description = "Entered country is not in controlled terms."

    def validate(self, submission, context):
        countries = set(context.cv_terms.get("countries", []))
        countries |= set(context.cv_terms.get("historical_countries", []))
        if not countries:
            return []  # CV が無ければ検証スキップ
        lower = {c.lower() for c in countries}
        out = []
        for rec in submission.records:
            v = rec.attr("geo_loc_name")
            if not v or is_missing_value(v):
                continue
            country = v.split(":", 1)[0].strip()
            # 完全一致／大文字小文字差は許容（case 補正は autofix の領分）
            if country and country not in countries and country.lower() not in lower:
                out.append(self.result(sample=(rec.sample_name or rec.accession),
                                       message=f"Entered country is not in controlled terms. (Found: '{country}')"))
        return out
