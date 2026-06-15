import osmnx as ox
import networkx as nx
import geopandas as gpd
import json
from typing import Dict, List, Optional, Tuple
from alphashape import alphashape
from shapely.geometry import Point as ShapelyPoint, MultiPolygon

TIME_BINS = [300, 600, 900, 1200, 1500]
WALK_SPEED_MPS = 1.4
GRAPH_DIST_M = int(TIME_BINS[-1] * WALK_SPEED_MPS * 1.3)

# Color and opacity settings for isochrone rings
RING_COLOR = "#f9b528"
RING_OPACITIES = [0.75, 0.625, 0.5, 0.375, 0.25]  # 50% to 10% for rings 1-5


def _create_concave_hull(points_geom, alpha=0.0015):
    """Create concave hull from point geometries.

    Args:
        points_geom: GeoSeries of point geometries
        alpha: Alpha parameter for alphashape (lower = more concave).
               0.0015 works well for typical urban networks

    Returns:
        Polygon or MultiPolygon, or None if insufficient points
    """
    if len(points_geom) < 3:
        return points_geom.unary_union.buffer(150)

    try:
        coords = [(p.x, p.y) for p in points_geom.geometry]
        concave = alphashape(coords, alpha=alpha)

        if concave.is_empty:
            return points_geom.unary_union.convex_hull.buffer(150)

        if concave.geom_type in ('Polygon', 'MultiPolygon'):
            return concave.buffer(50)
        else:
            return points_geom.unary_union.convex_hull.buffer(150)
    except Exception:
        return points_geom.unary_union.convex_hull.buffer(150)


def get_isochrones(lat: float, lon: float) -> Dict:
    """Calculate isochrone rings and return as GeoJSON with styling.

    Args:
        lat: Latitude coordinate
        lon: Longitude coordinate

    Returns:
        GeoJSON dict with styled isochrone rings, or error dict if calculation fails
    """
    try:
        from shapely.geometry import Point as ShapelyPoint

        G = ox.graph_from_point(
            (lat, lon),
            dist=GRAPH_DIST_M,
            network_type="walk",
            simplify=True
        )

        # Add travel_time to edges
        for u, v, k, data in G.edges(keys=True, data=True):
            length_m = data.get("length")
            if length_m is None:
                data["travel_time"] = None
            else:
                data["travel_time"] = float(length_m) / WALK_SPEED_MPS

        # Convert to GeoDataFrame
        nodes_gdf, edges_gdf = ox.graph_to_gdfs(G, nodes=True, edges=True)
        utm_crs = nodes_gdf.estimate_utm_crs()
        nodes_m = nodes_gdf.to_crs(utm_crs)

        # Find nearest node using optimized OSM method
        orig_node = ox.nearest_nodes(G, lon, lat, return_dist=False)

        # Calculate travel times from origin with early stopping (cutoff)
        travel_times = nx.single_source_dijkstra_path_length(
            G, orig_node, weight="travel_time", cutoff=max(TIME_BINS)
        )

        # Add travel_time to nodes_m GeoDataFrame
        nodes_m["travel_time"] = nodes_m.index.map(travel_times)

        iso_polys = []
        prev = 0

        for t in TIME_BINS:
            sub = nodes_m[nodes_m["travel_time"] <= t]
            geom = None if sub.empty else _create_concave_hull(sub.geometry)
            iso_polys.append({"t_from": prev, "t_to": t, "geometry": geom})
            prev = t

        iso_gdf = gpd.GeoDataFrame(iso_polys, crs=nodes_m.crs)

        rings = iso_gdf.copy()
        ring_geoms = []
        for i in range(len(iso_gdf)):
            geom = iso_gdf.loc[i, "geometry"]
            if geom is None:
                ring = None
            elif i == 0:
                ring = geom
            else:
                prev_geom = iso_gdf.loc[i-1, "geometry"]
                ring = geom.difference(prev_geom) if prev_geom is not None else geom
            ring_geoms.append(ring)

        rings["geometry"] = ring_geoms
        rings_wgs = rings.to_crs(epsg=4326)

        geojson_data = json.loads(rings_wgs.to_json())

        for i, feature in enumerate(geojson_data["features"]):
            if feature["geometry"] is not None:
                opacity = RING_OPACITIES[i] if i < len(RING_OPACITIES) else 0.1
                feature["properties"]["fill"] = RING_COLOR
                feature["properties"]["fill-opacity"] = opacity
                feature["properties"]["stroke"] = RING_COLOR
                feature["properties"]["stroke-opacity"] = opacity
                feature["properties"]["stroke-width"] = 2
                feature["properties"]["ring_index"] = i + 1
                feature["properties"]["time_range"] = f"{feature['properties']['t_from']}-{feature['properties']['t_to']}s"

        return {"status": "success", "geojson": geojson_data, "node_count": len(travel_times)}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": f"Ошибка расчета изохрон: {str(e)}"}
