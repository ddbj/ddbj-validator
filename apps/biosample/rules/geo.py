"""地理情報ルール（country CV 依存・DB 非依存。フェーズ A 続き）。

- BS_R0008: geo_loc_name の国名部分が controlled country list に無い
  country CV は common/resources/definitions.json の cv_terms.countries / historical_countries を使用。
- BS_R0041: lat_lon と geo_loc_name（国名部分）の矛盾。common/geo.py（ddbj ANN1275 と共通ロジック）を利用。
  geopandas/shapely 未導入時は検証スキップ。
"""
from apps.biosample.rules.base import BsRule
from apps.biosample.rules._util import is_missing_value, is_empty
from common.geo import GeoChecker

# 頻出の非正規国名 → INSDC 正表記のハードコード補正（大文字小文字無視）。
# "Vietnam" は多いため特例で "Viet Nam" へ autofix する。
_COUNTRY_HARDCODE = {"vietnam": "Viet Nam"}


class BS_R0008(BsRule):
    rule_id = "BS_R0008"
    level = "error"
    target = "geo_loc_name"
    description = "Entered country is not in controlled terms."

    def validate(self, submission, context):
        countries = context.country_terms()
        if not countries:
            return []  # CV が無ければ検証スキップ
        lower = {c.lower() for c in countries}
        out = []
        for rec in submission.records:
            v = rec.attr("geo_loc_name")
            if not v or is_missing_value(v):
                continue
            country = v.split(":", 1)[0].strip()
            # 完全一致／大文字小文字差／ハードコード補正対象（Vietnam 等）は許容（R0094 が autofix）
            if (country and country not in countries and country.lower() not in lower
                    and country.lower() not in _COUNTRY_HARDCODE):
                out.append(self.result(sample=rec.sample_id,
                                       message=f"Entered country is not in controlled terms. (Found: '{country}')"))
        return out


class BS_R0094(BsRule):
    rule_id = "BS_R0094"
    level = "warning"
    target = "geo_loc_name"
    description = "Format of geo_loc_name is invalid."

    def validate(self, submission, context):
        # 国名部分の大文字小文字補正 ＋ INSDC 正形「Country: Region」（コロン後 半角空白1つ）への正規化。
        # 例 "japan:Tokyo" / "Japan:Tokyo" → "Japan: Tokyo"（CV に全く無い国名は R0008=error が担当）。
        # コロン後空白の付与は決定的・安全な補正のみ（地域名の中身は変更しない）。
        countries = context.country_terms()
        if not countries:
            return []
        canon = {c.lower(): c for c in countries}
        out = []
        for rec in submission.records:
            v = rec.attr("geo_loc_name")
            if not v or is_missing_value(v):
                continue
            parts = v.split(":", 1)
            country = parts[0].strip()
            cl = country.lower()
            new_country = _COUNTRY_HARDCODE.get(cl) or canon.get(cl)
            if not new_country:
                continue  # CV 外かつハードコード対象外は R0008

            if len(parts) == 1:
                new_val = new_country
            else:
                # コロンの後は半角空白 1 つ（INSDC 正形）。地域名前後の余分な空白のみ整える。
                new_val = f"{new_country}: {parts[1].strip()}"
            if new_val != v:
                out.append(self.autofix_result(
                    sample=rec.sample_id,
                    message=f"Format of geo_loc_name is invalid. (Found: '{v}', Suggested: '{new_val}')",
                    attribute="geo_loc_name", old_value=v, new_value=new_val))
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
                    sample=rec.sample_id,
                    message=(f"Values provided for 'lat_lon' ({lat_lon}) and 'geo_loc_name' "
                             f"({country}) contradict each other. Coordinates point to: {actual}")))
        return out
