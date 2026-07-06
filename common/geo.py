"""lat_lon ↔ 国名（geo_loc_name の国部分）の整合チェック（ddbj/biosample 共通）。

ddbj の ANN1275 と同じロジックを共通化したもの。geopandas/shapely と
common/resources/geo/ の parquet を遅延ロードし、座標が国ポリゴンに含まれるか判定する。
未インストール／リソース欠落時は「検証スキップ（空結果）」で安全側に倒す。

使い方:
    checker = GeoChecker()
    verdict = checker.check(lat_lon_str, country_name)
    # verdict is None → 判定不能（スキップ）。dict → {is_valid, hit_names, dist_km}
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

DEGREES_TO_KM = 111.0
# INSDC lat_lon 形式（例: "35.6 N 139.7 E"）
_LATLON_RE = re.compile(r"^\d+(?:\.\d+)?\s+[NS]\s+\d+(?:\.\d+)?\s+[EW]$")


class GeoChecker:
    """遅延ロード式の geo チェッカー。ロード失敗時は常に None を返す。"""

    def __init__(self):
        self._loaded = False
        self._available = False
        self._cache = {}
        self.geo_df = None
        self.geo_mapping = None
        self.valid_land_names = None
        self.Point = None

    def _load(self):
        if self._loaded:
            return self._available
        self._loaded = True
        try:
            import geopandas as gpd
            from shapely.geometry import Point
            self.Point = Point
        except ImportError:
            logger.warning("geopandas/shapely 未インストール。geo チェックはスキップします。")
            return False
        try:
            from importlib.resources import files, as_file
            geo_resources = files("common.resources.geo")
            parquet_path = geo_resources / "countries_50m.parquet"
            mapping_path = geo_resources / "insdc_geo_mapping.json"
            self.geo_mapping = {}
            if mapping_path.is_file():
                with mapping_path.open("r", encoding="utf-8") as f:
                    self.geo_mapping = json.load(f)
            if not parquet_path.is_file():
                logger.warning("GeoParquet が見つかりません。geo チェックはスキップします。")
                return False
            with as_file(parquet_path) as p_path:
                self.geo_df = gpd.read_parquet(p_path)
                _ = self.geo_df.sindex
        except Exception as e:
            logger.warning(f"geo データのロードに失敗: {e}")
            return False

        names = set()
        for ne_name in self.geo_df["name"].values:
            if ne_name in self.geo_mapping:
                for mapped in self.geo_mapping[ne_name]:
                    names.add(mapped.lower())
            else:
                names.add(ne_name.lower())
        self.valid_land_names = names
        self._available = True
        return True

    @staticmethod
    def parse_lat_lon(lat_lon_str):
        """INSDC 形式の lat_lon を (lat, lon) に。不正なら None。"""
        s = (lat_lon_str or "").strip()
        if not _LATLON_RE.match(s):
            return None
        parts = s.split()
        if len(parts) != 4:
            return None
        lat = float(parts[0]) * (-1 if parts[1] == "S" else 1)
        lon = float(parts[2]) * (-1 if parts[3] == "W" else 1)
        return lat, lon

    def check(self, lat_lon_str, country_name):
        """座標と国名の整合を判定。

        戻り値:
          None … 判定不能（geo 未ロード / 形式不正 / 国名が既知の陸地名に無い）→ スキップ扱い
          dict … {"is_valid": bool, "hit_names": [str], "dist_km": float}
        """
        if not self._load():
            return None
        country_lower = (country_name or "").strip().lower()
        if country_lower not in self.valid_land_names:
            return None
        coords = self.parse_lat_lon(lat_lon_str)
        if not coords:
            return None
        cache_key = (lat_lon_str, country_lower)
        if cache_key in self._cache:
            return self._cache[cache_key]

        lat, lon = coords
        pt = self.Point(lon, lat)
        matches_df = self.geo_df[self.geo_df.intersects(pt.buffer(1.0))]

        hit_names = []
        matched_geoms = []
        for _idx, row in matches_df.iterrows():
            ne_name = row["name"]
            if ne_name in self.geo_mapping:
                allowed = [m.lower() for m in self.geo_mapping[ne_name]]
                hit_names.extend(self.geo_mapping[ne_name])
            else:
                allowed = [ne_name.lower()]
                hit_names.append(ne_name)
            if country_lower in allowed:
                matched_geoms.append(row["geometry"])

        is_valid = len(matched_geoms) > 0
        dist_km = 0.0
        if is_valid:
            min_dist_deg = min(g.distance(pt) for g in matched_geoms)
            if min_dist_deg > 0:
                dist_km = round(min_dist_deg * DEGREES_TO_KM, 1)

        verdict = {"is_valid": is_valid, "hit_names": hit_names, "dist_km": dist_km}
        self._cache[cache_key] = verdict
        return verdict
