import osmnx as ox
import geopandas as gpd
from shapely.geometry import Point
from typing import Optional, Dict, Any


def only_polygons(gdf: Optional[gpd.GeoDataFrame]) -> Optional[gpd.GeoDataFrame]:
    """Return GeoDataFrame with only Polygon/MultiPolygon geometries or None/empty as-is."""
    if gdf is None or gdf.empty or "geometry" not in gdf.columns:
        return gdf
    g = gdf[~gdf.geometry.isna()].copy()
    if g.empty:
        return g
    return g[g.geometry.geom_type.isin(["Polygon", "MultiPolygon"]) ]


def point_in_polygons(gdf: Optional[gpd.GeoDataFrame], point: Point) -> bool:
    """Check whether point is covered by any polygon in gdf.

    Uses unary_union for faster single-point checks when possible.
    """
    g = only_polygons(gdf)
    if g is None or g.empty:
        return False
    try:
        union = g.geometry.unary_union
        return bool(union.covers(point))
    except Exception:
        # fallback to elementwise check
        return bool(g.geometry.apply(lambda geom: geom.covers(point)).any())


def get_features(lat: float, lon: float, tags: Dict[str, str], dist: int):
    """Safe wrapper around osmnx.features_from_point; returns GeoDataFrame or None."""
    try:
        gdf = ox.features_from_point((lat, lon), tags, dist=dist)
        return gdf
    except Exception as e:
        # don't crash the caller; return None and let caller decide
        print(f"Ошибка получения данных OSM для тегов {tags}: {e}")
        return None


def classify_point(proj_lat: float, proj_lon: float, R_CAT: int = 1500, raise_on_fail: bool = True) -> Dict[str, Any]:
    """Classify point by OSM polygons.

    Returns a dict with keys: in_park_poly, in_wood_poly, category (or None), details.
    If raise_on_fail is True and no category matched, raises ValueError.
    """
    pt = Point(proj_lon, proj_lat)

    tags_park = {"leisure": "park"}
    tags_wood = {"natural": "wood"}

    gdf_park = get_features(proj_lat, proj_lon, tags_park, R_CAT)
    gdf_wood = get_features(proj_lat, proj_lon, tags_wood, R_CAT)

    # Ensure CRS is WGS84 (EPSG:4326) for reliable geometric tests
    for gdf in (gdf_park, gdf_wood):
        if gdf is None or gdf.empty:
            continue
        try:
            if gdf.crs is None:
                gdf.set_crs(epsg=4326, inplace=True)
            else:
                gdf.to_crs(epsg=4326, inplace=True)
        except Exception:
            # If CRS operations fail, continue — point checks may still work if geometries are lat/lon
            pass

    in_park_poly = point_in_polygons(gdf_park, pt)
    in_wood_poly = point_in_polygons(gdf_wood, pt)

    details = {
        "in_park_poly": in_park_poly,
        "in_wood_poly": in_wood_poly,
        "R_CAT": R_CAT,
    }

    if in_park_poly or in_wood_poly:
        category = "park"
        details["category"] = category
        return details

    # no match
    details["category"] = None
    if raise_on_fail:
        raise ValueError(
            "Типология 'park' НЕ подтверждена: точка не входит ни в один полигон "
            "leisure=park или natural=wood (по данным OSM). Выберите другую точку."
        )
    return details


# Модуль предоставляет функцию `classify_point(proj_lat, proj_lon, ...)`.
# Примеры использования и тесты удалены — вызывайте функцию из `main.py`.



TEMPLATE_PATH = "/content/drive/MyDrive/НИР/04-Template_new_object.xlsx"
OUT_PATH = "/content/evaluation/05-New_object_filled.xlsx"
INPUT_ROW = 4  # строка нового объекта

if not os.path.exists(TEMPLATE_PATH):
    raise FileNotFoundError(f"Шаблон не найден: {TEMPLATE_PATH}")

def find_header_columns(ws, required_headers, search_rows=15):
    required_lower = {h.lower(): h for h in required_headers}

    for r in range(1, search_rows + 1):
        mapping = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str):
                key = v.strip().lower()
                if key in required_lower:
                    mapping[required_lower[key]] = c

        if all(h in mapping for h in required_headers):
            return r, mapping

    raise ValueError(f"Не найдена строка заголовков с полями {required_headers} в первых {search_rows} строках.")

required = ["№", "Город", "Регион", "name", "coordinate", "category"]

wb = load_workbook(TEMPLATE_PATH)
ws = wb.active  # при необходимости: wb["ИмяЛиста"]

header_row, col = find_header_columns(ws, required_headers=required, search_rows=15)

ws.cell(row=INPUT_ROW, column=col["№"]).value = 0
ws.cell(row=INPUT_ROW, column=col["Город"]).value = city
ws.cell(row=INPUT_ROW, column=col["Регион"]).value = region
ws.cell(row=INPUT_ROW, column=col["name"]).value = "object"
ws.cell(row=INPUT_ROW, column=col["coordinate"]).value = coordinate_str
ws.cell(row=INPUT_ROW, column=col["category"]).value = category

wb.save(OUT_PATH)
print("Готово:", OUT_PATH)
