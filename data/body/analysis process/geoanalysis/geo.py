"""
Utility functions for spatial analysis: collect POI (points) within isochrone rings.

This module exposes `collect_poi_points(iso_geojson, tags_map, colors, cache_dir)` which:
- converts isochrone GeoJSON into a GeoDataFrame of rings
- queries OSM for given tags (tries osmnx.geometries_from_polygon, falls back to bbox or Overpass HTTP)
- converts returned geometries to representative points
- assigns each point to an isochrone zone via spatial join
- returns GeoJSON FeatureCollection of points with properties: metric, color, tags, zone

The implementation is robust to osmnx API differences and includes a simple disk cache.
"""

from typing import Dict, Any, List, Tuple, Optional
import os
import json
import hashlib
import requests

import geopandas as gpd
import pandas as pd
import shapely.geometry as geom
from shapely.geometry import shape, mapping, Point
from shapely.ops import unary_union

try:
    import osmnx as ox
except Exception:
    ox = None


def _query_overpass_bbox(tags: Dict[str, Any], bbox: Tuple[float, float, float, float], overpass_url: str = 'https://overpass-api.de/api/interpreter') -> gpd.GeoDataFrame:
    """Query Overpass API using bbox and return GeoDataFrame of point geometries (center for ways/relations)."""
    south, west, north, east = bbox[1], bbox[0], bbox[3], bbox[2]
    queries = []
    for k, v in tags.items():
        values = v if isinstance(v, (list, tuple)) else [v]
        for val in values:
            # request nodes, ways, relations
            queries.append(f'node["{k}"="{val}"]({south},{west},{north},{east});')
            queries.append(f'way["{k}"="{val}"]({south},{west},{north},{east});')
            queries.append(f'relation["{k}"="{val}"]({south},{west},{north},{east});')

    q = "[out:json][timeout:25];(" + "".join(queries) + ");out center;"

    resp = requests.post(overpass_url, data={'data': q}, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = []
    for el in data.get('elements', []):
        props = el.get('tags', {}) or {}
        props['osm_type'] = el.get('type')
        props['osm_id'] = el.get('id')
        lat = None
        lon = None
        if el.get('type') == 'node':
            lat = el.get('lat')
            lon = el.get('lon')
        else:
            c = el.get('center') or el.get('bounds')
            if c and isinstance(c, dict):
                lat = c.get('lat')
                lon = c.get('lon')
        if lat is None or lon is None:
            continue
        features.append({'geometry': Point(lon, lat), 'properties': props})

    if not features:
        return gpd.GeoDataFrame([], geometry='geometry', crs='EPSG:4326')

    gdf = gpd.GeoDataFrame([f['properties'] for f in features], geometry=[f['geometry'] for f in features], crs='EPSG:4326')
    return gdf


def collect_poi_points(iso_geojson: Dict[str, Any], tags_map: Dict[str, List[Tuple[str, str]]], colors: Dict[str, str], cache_dir: Optional[str] = None, overpass_url: Optional[str] = None) -> Dict[str, Any]:
    """Collect POI points for given isochrone GeoJSON and tags mapping.

    Returns a dict suitable for JSONifying: {'status': 'success', 'isochrones': iso_geojson, 'colors': colors, 'points': points_geojson}
    """
    if iso_geojson is None:
        return {'status': 'error', 'message': 'iso_geojson is None'}

    features = iso_geojson.get('features', [])
    ring_records = []
    for feat in features:
        geom_json = feat.get('geometry')
        if geom_json is None:
            continue
        try:
            shapely_geom = shape(geom_json)
        except Exception:
            continue
        props = dict(feat.get('properties', {}) or {})
        props['geometry'] = shapely_geom
        ring_records.append(props)

    if not ring_records:
        return {'status': 'error', 'message': 'no isochrone features'}

    rings_gdf = gpd.GeoDataFrame(ring_records, geometry='geometry', crs='EPSG:4326')

    # create zone labels from t_from/t_to if present
    ZONE_LABELS = {
        (0, 300): "5<",
        (300, 600): "5<10",
        (600, 900): "10<15",
        (900, 1200): "15<20",
        (1200, 1500): "20<25",
    }

    def zone_label_from_props(row):
        try:
            t_from = int(row.get('t_from'))
            t_to = int(row.get('t_to'))
            return ZONE_LABELS.get((t_from, t_to))
        except Exception:
            return None

    rings_gdf['zone'] = rings_gdf.apply(zone_label_from_props, axis=1)

    outer_poly = unary_union(list(rings_gdf.geometry.values))

    # prepare cache dir
    if cache_dir is None:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        cache_dir = os.path.join(repo_root, 'cache', 'osm')
    os.makedirs(cache_dir, exist_ok=True)

    all_point_features: List[Dict[str, Any]] = []

    minx, miny, maxx, maxy = outer_poly.bounds
    bbox = (minx, miny, maxx, maxy)

    for metric, kvs in tags_map.items():
        # build tags dict for query
        tags_query: Dict[str, List[str]] = {}
        for k, v in kvs:
            if not k:
                continue
            tags_query.setdefault(k, []).append(v)
        # simplify values: keep unique
        tags_query = {k: list(sorted(set([str(x) for x in vals if x and not pd.isna(x)]))) for k, vals in tags_query.items()}

        # cache key
        key_str = json.dumps({'metric': metric, 'bbox': bbox, 'tags': tags_query}, sort_keys=True)
        h = hashlib.md5(key_str.encode('utf-8')).hexdigest()[:12]
        cache_file = os.path.join(cache_dir, f"{metric}_{h}.geojson")

        gdf_points = None
        if os.path.exists(cache_file):
            try:
                gdf_points = gpd.read_file(cache_file)
            except Exception:
                gdf_points = None

        if gdf_points is None:
            # try osmnx polygon query, else bbox, else Overpass fallback
            gdf_all = None
            if ox is not None and hasattr(ox, 'geometries_from_polygon'):
                try:
                    gdf_all = ox.geometries_from_polygon(outer_poly, tags_query)
                except Exception:
                    gdf_all = None

            if gdf_all is None and ox is not None and hasattr(ox, 'geometries_from_bbox'):
                try:
                    north, south, east, west = maxy, miny, maxx, minx
                    gdf_all = ox.geometries_from_bbox(north, south, east, west, tags_query)
                except Exception:
                    gdf_all = None

            if gdf_all is None:
                # fallback to Overpass HTTP
                try:
                    gdf_all = _query_overpass_bbox(tags_query, bbox, overpass_url=overpass_url or 'https://overpass-api.de/api/interpreter')
                except Exception:
                    gdf_all = None

            if gdf_all is None or gdf_all.empty:
                continue

            # convert to points
            gdf_all = gdf_all[~gdf_all.geometry.isna()].copy()
            pts = []
            prop_rows = []
            for _, row in gdf_all.iterrows():
                geom_obj = row.geometry
                if geom_obj is None:
                    continue
                try:
                    if geom_obj.geom_type == 'Point':
                        pt = geom_obj
                    else:
                        pt = geom_obj.representative_point() if hasattr(geom_obj, 'representative_point') else geom_obj.centroid
                except Exception:
                    pt = geom_obj.centroid

                # collect tag fields
                props = {k: row.get(k) if k in row.index else None for k in tags_query.keys()}
                props['metric'] = metric
                props['color'] = colors.get(metric, colors.get('default', '#cccccc'))
                prop_rows.append(props)
                pts.append(pt)

            if not pts:
                continue

            gdf_points = gpd.GeoDataFrame(prop_rows, geometry=pts, crs='EPSG:4326')

            # cache
            try:
                gdf_points.to_file(cache_file, driver='GeoJSON')
            except Exception:
                pass

        if gdf_points is None or gdf_points.empty:
            continue

        # spatial join to rings to get zone
        try:
            pts = gdf_points.set_geometry('geometry').set_crs('EPSG:4326')
            try:
                joined = gpd.sjoin(pts, rings_gdf[['geometry', 'zone']], how='left', predicate='within')
            except TypeError:
                joined = gpd.sjoin(pts, rings_gdf[['geometry', 'zone']], how='left', op='within')

            for _, prow in joined.iterrows():
                pt_geom = prow.geometry
                props = {k: prow.get(k) for k in prow.index if k != 'geometry'}
                props_dict = {k: props.get(k) for k in tags_query.keys()}
                feat_props = {'metric': metric, 'color': colors.get(metric, colors.get('default', '#cccccc')), 'tags': props_dict, 'zone': props.get('zone')}
                all_point_features.append({'type': 'Feature', 'geometry': mapping(pt_geom), 'properties': feat_props})
        except Exception:
            for _, prow in gdf_points.iterrows():
                pt_geom = prow.geometry
                props_dict = {k: prow.get(k) for k in tags_query.keys()}
                feat_props = {'metric': metric, 'color': colors.get(metric, colors.get('default', '#cccccc')), 'tags': props_dict, 'zone': None}
                all_point_features.append({'type': 'Feature', 'geometry': mapping(pt_geom), 'properties': feat_props})

    points_geojson = {'type': 'FeatureCollection', 'features': all_point_features}
    return {'status': 'success', 'isochrones': iso_geojson, 'colors': colors, 'points': points_geojson}
