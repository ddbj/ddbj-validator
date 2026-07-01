"""地理情報ルール（country CV 依存・DB 非依存。フェーズ A 続き）。

- BS_R0008: geo_loc_name の国名部分が controlled country list に無い
  country CV は common/resources/definitions.json の cv_terms.countries / historical_countries を使用。
- BS_R0041: lat_lon と geo_loc_name（国名部分）の矛盾。common/geo.py（ddbj ANN1275 と共通ロジック）を利用。
  geopandas/shapely 未導入時は検証スキップ。
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value, is_empty
from common.geo import GeoChecker


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


# geo データは重いのでルール間で 1 インスタンスを共有（プロセス内キャッシュ）
_GEO = GeoChecker()


class BS_R0041(BsRule):
    rule_id = "BS_R0041"
    level = "warning"
    target = "lat_lon, geo_loc_name"
    description = "Values provided for 'latitude and longitude' and 'geographic location' contradict each other."

    def validate(self, submission, context):
        out = []
        for rec in submission.records:
            lat_lon = rec.attr("lat_lon")
            geo = rec.attr("geo_loc_name")
            if is_empty(lat_lon) or is_empty(geo) or is_missing_value(geo):
                continue
            country = geo.split(":", 1)[0].strip()
            verdict = _GEO.check(lat_lon, country)
            if verdict is None:
                continue  # 判定不能（geo 未導入 / 形式不正 / 未知国名）→ スキップ
            if not verdict["is_valid"]:
                hits = sorted(set(verdict["hit_names"]))
                actual = ", ".join(hits) if hits else "Ocean/Unmapped area"
                out.append(self.result(
                    sample=(rec.sample_name or rec.accession),
                    message=(f"Values provided for 'lat_lon' ({lat_lon}) and 'geo_loc_name' "
                             f"({country}) contradict each other. Coordinates point to: {actual}")))
        return out
