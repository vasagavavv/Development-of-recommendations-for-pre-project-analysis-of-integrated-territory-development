from flask import Flask, render_template, jsonify, request, send_from_directory
from typologization.category import classify_point, classify_and_export_csv
from typologization.isochrone import get_isochrones
import json
import importlib.util
import hashlib
import geopandas as gpd
from shapely.geometry import shape
from shapely.ops import unary_union
import osmnx as ox
import webbrowser
import threading
import tempfile
import os

app = Flask(__name__, template_folder='template', static_folder='static')

# Глобальная переменная для хранения координат
selected_coordinates = None

# Значения по умолчанию для шаблона (будут перезаписаны в __main__ при вводе)
default_city = "Москва"
default_region = "Московская область"

@app.route('/')
def index():
    """Главная страница с картой"""
    # Берем значения из глобальных defaults (их можно изменить при старте)
    return render_template('map_template.html',
                         city=default_city,
                         region=default_region,
                         center_lat=61.0,
                         center_lon=105.0,
                         zoom_level=3)

@app.route('/save_coords', methods=['POST'])
def save_coords():
    """API для сохранения координат"""
    global selected_coordinates
    data = request.json
    selected_coordinates = (data['lat'], data['lng'])
    # После подтверждения точки выполняем классификацию, экспортируем в CSV и возвращаем результат
    try:
        result = classify_and_export_csv(
            lat=selected_coordinates[0],
            lon=selected_coordinates[1],
            city=default_city,
            region=default_region,
            output_dir="data/content/evaluation"
        )
        return jsonify({'status': 'success', 'coords': selected_coordinates, 'classification': result})
    except Exception as e:
        # В редких случаях может быть ошибка — вернём ошибку
        return jsonify({'status': 'error', 'coords': selected_coordinates, 'message': str(e)}), 500


@app.route('/__static_check')
def static_check():
    """Диагностический маршрут: проверяет существование ключевых статических файлов"""
    static_root = os.path.join(os.path.dirname(__file__), 'static')
    css_path = os.path.join(static_root, 'css', 'map_style.css')
    js_path = os.path.join(static_root, 'js', 'map_handler.js')
    result = {
        'static_root': static_root,
        'css_exists': os.path.exists(css_path),
        'css_path': css_path,
        'js_exists': os.path.exists(js_path),
        'js_path': js_path
    }
    return jsonify(result)


@app.route('/classify', methods=['GET'])
def classify():
    """Классификация текущих выбранных координат через category.classify_and_export_csv"""
    global selected_coordinates
    if selected_coordinates is None:
        return jsonify({'status': 'error', 'message': 'Координаты ещё не заданы'}), 400

    proj_lat, proj_lon = selected_coordinates
    try:
        result = classify_and_export_csv(
            lat=proj_lat,
            lon=proj_lon,
            city=default_city,
            region=default_region,
            output_dir="data/content/evaluation"
        )
        return jsonify({'status': 'success', 'result': result})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/isochrones', methods=['GET'])
def isochrones():
    """Получить изохроны (кольца времени ходьбы) для выбранных координат"""
    global selected_coordinates
    if selected_coordinates is None:
        return jsonify({'status': 'error', 'message': 'Координаты ещё не заданы'}), 400

    proj_lat, proj_lon = selected_coordinates
    result = get_isochrones(lat=proj_lat, lon=proj_lon)
    return jsonify(result)


@app.route('/metric_points', methods=['GET'])
def metric_points():
    """Return isochrones and nearby POI points grouped by metric with color mapping.

    Query params: none (uses last selected_coordinates).
    """
    global selected_coordinates
    if selected_coordinates is None:
        return jsonify({'status': 'error', 'message': 'Координаты ещё не заданы'}), 400

    proj_lat, proj_lon = selected_coordinates

    # generate isochrones
    iso = get_isochrones(lat=proj_lat, lon=proj_lon)
    if iso.get('status') != 'success':
        return jsonify({'status': 'error', 'message': 'Ошибка расчёта изохрон', 'detail': iso.get('message')}), 500

    # dynamically import helper module (located in 'analysis process/geoanalysis')
    metrics_path = os.path.join(os.path.dirname(__file__), 'analysis process', 'geoanalysis', 'metrics.py')
    if not os.path.exists(metrics_path):
        return jsonify({'status': 'error', 'message': f'Metrics helper not found: {metrics_path}'}), 500

    spec = importlib.util.spec_from_file_location('metrics_mod', metrics_path)
    metrics_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(metrics_mod)

    # load colors and tags
    try:
        colors = metrics_mod.load_colors(os.path.join(os.path.dirname(__file__), '..', 'initial data', 'metrics_colors.json'))
    except Exception:
        colors = {'default': '#cccccc'}

    try:
        tags_map = metrics_mod.load_tags_from_csv(os.path.join(os.path.dirname(__file__), '..', 'initial data', 'content', 'analyzis_object.csv'))
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Ошибка чтения CSV тегов', 'detail': str(e)}), 500

    # Convert isochrone geojson to GeoDataFrame
    try:
        features = iso.get('geojson', {}).get('features', [])
        ring_records = []
        for feat in features:
            geom = feat.get('geometry')
            if geom is None:
                continue
            ring_records.append({**feat.get('properties', {}), 'geometry': shape(geom)})

        if not ring_records:
            return jsonify({'status': 'error', 'message': 'Пустые изохроны'}), 500

        rings_gdf = gpd.GeoDataFrame(ring_records, geometry='geometry', crs='EPSG:4326')
        # derive zone label from t_from/t_to if available
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

        outer_poly = unary_union(rings_gdf.geometry.values)
    except Exception as e:
        return jsonify({'status': 'error', 'message': 'Ошибка обработки изохрон', 'detail': str(e)}), 500

    # prepare cache
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    cache_dir = os.path.join(repo_root, 'cache', 'osm')
    os.makedirs(cache_dir, exist_ok=True)

    all_point_features = []

    # For each metric, query OSM (or read from cache)
    import hashlib
    for metric, kvs in tags_map.items():
        # build tags dict for osmnx
        tags_query = {}
        for k, v in kvs:
            tags_query.setdefault(k, set()).add(v)
        for k in list(tags_query.keys()):
            vals = list(tags_query[k])
            tags_query[k] = vals[0] if len(vals) == 1 else vals

        # cache key by metric + bbox
        try:
            minx, miny, maxx, maxy = outer_poly.bounds
            bbox_str = f"{minx:.6f}_{miny:.6f}_{maxx:.6f}_{maxy:.6f}"
        except Exception:
            bbox_str = f"{proj_lat:.6f}_{proj_lon:.6f}"

        h = hashlib.md5(bbox_str.encode('utf-8')).hexdigest()[:12]
        cache_file = os.path.join(cache_dir, f"{metric}_{h}.geojson")

        gdf_points = None
        if os.path.exists(cache_file):
            try:
                gdf_points = gpd.read_file(cache_file)
            except Exception:
                gdf_points = None

        if gdf_points is None:
            try:
                gdf_all = ox.geometries_from_polygon(outer_poly, tags_query)
            except Exception as e:
                # skip metric on error but continue others
                print(f"OSM query failed for {metric}: {e}")
                continue

            if gdf_all is None or gdf_all.empty:
                continue

            # ensure geometries exist and convert to points
            gdf_all = gdf_all[~gdf_all.geometry.isna()].copy()
            points = []
            for idx, row in gdf_all.iterrows():
                geom = row.geometry
                if geom is None:
                    continue
                # prefer representative_point for polygons/lines
                try:
                    if geom.geom_type == 'Point':
                        pt = geom
                    else:
                        pt = geom.representative_point() if hasattr(geom, 'representative_point') else geom.centroid
                except Exception:
                    pt = geom.centroid

                props = {}
                # collect relevant tag values
                for key in tags_query.keys():
                    try:
                        props[key] = row.get(key)
                    except Exception:
                        props[key] = None

                props['metric'] = metric
                props['color'] = colors.get(metric, colors.get('default', '#cccccc'))

                points.append({'geometry': pt, 'properties': props})

            if not points:
                continue

            gdf_points = gpd.GeoDataFrame([p['properties'] for p in points], geometry=[p['geometry'] for p in points], crs='EPSG:4326')

            # write cache
            try:
                gdf_points.to_file(cache_file, driver='GeoJSON')
            except Exception:
                pass

        # collect features
        if gdf_points is not None and not gdf_points.empty:
            # spatial join to find zone
            try:
                pts = gdf_points.copy()
                pts = pts.set_geometry('geometry')
                pts = pts.set_crs('EPSG:4326')
                # sjoin with rings
                try:
                    joined = gpd.sjoin(pts, rings_gdf[['geometry', 'zone']], how='left', predicate='within')
                except TypeError:
                    joined = gpd.sjoin(pts, rings_gdf[['geometry', 'zone']], how='left', op='within')

                for _, prow in joined.iterrows():
                    geom = prow.geometry
                    props = {k: prow.get(k) for k in prow.index if k != 'geometry'}
                    # ensure tags property grouping
                    props_dict = {k: props.get(k) for k in tags_query.keys()}
                    feat_props = {'metric': metric, 'color': colors.get(metric, colors.get('default', '#cccccc')), 'tags': props_dict, 'zone': props.get('zone')}
                    all_point_features.append({'type': 'Feature', 'geometry': json.loads(gpd.GeoSeries([geom], crs='EPSG:4326').to_json())['features'][0]['geometry'], 'properties': feat_props})
            except Exception as e:
                print(f"Ошибка пространственного объединения для {metric}: {e}")
                # fallback: export points without zone
                for _, prow in gdf_points.iterrows():
                    geom = prow.geometry
                    props_dict = {k: prow.get(k) for k in tags_query.keys()}
                    feat_props = {'metric': metric, 'color': colors.get(metric, colors.get('default', '#cccccc')), 'tags': props_dict, 'zone': None}
                    all_point_features.append({'type': 'Feature', 'geometry': json.loads(gpd.GeoSeries([geom], crs='EPSG:4326').to_json())['features'][0]['geometry'], 'properties': feat_props})

    # build GeoJSON
    points_geojson = {'type': 'FeatureCollection', 'features': all_point_features}

    return jsonify({'status': 'success', 'isochrones': iso.get('geojson'), 'colors': colors, 'points': points_geojson})

def open_browser():
    """Открывает браузер после запуска сервера"""
    webbrowser.open('http://localhost:5000')

if __name__ == '__main__':
    # При запуске с включённым debug Flask использует reloader,
    # из-за чего модуль выполняется дважды. Переменная окружения
    # WERKZEUG_RUN_MAIN установлена в 'true' в рабочем (child) процессе.
    # Выполняем интерактивный ввод и открытие браузера только в этом процессе,
    # чтобы избежать двойного запроса ввода.
    is_reloader_child = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    # Если debug=True и WERKZEUG_RUN_MAIN отсутствует, это родительский процесс reloader'а — пропускаем ввод.
    should_prompt = not (app.debug and 'WERKZEUG_RUN_MAIN' not in os.environ) or is_reloader_child

    if should_prompt:
        # Запрос данных у пользователя и установка значений по умолчанию
        try:
            city_input = input("Введите название города (Enter для Москвы): ").strip()
            region_input = input("Введите регион (Enter для Московская область): ").strip()
            if city_input:
                default_city = city_input
            if region_input:
                default_region = region_input
        except Exception:
            # В окружениях без stdin просто используем defaults
            pass

        # Открываем браузер только в рабочем процессе
        threading.Timer(1, open_browser).start()

    # Запускаем сервер. Отключаем встроенный reloader, чтобы
    # не выполнять модуль дважды и не дублировать ввод в консоли.
    app.run(debug=True, port=5000, use_reloader=False)

    # Этот принт выполнится в процессе, где app.run завершится
    # print(f"Выбраны координаты: {selected_coordinates}")

#proj_lat = data.get('proj_lat')
#proj_lon = data.get('proj_lon')
#if proj_lat is None or proj_lon is None:
#    raise ValueError("Точка проекта не выбрана. Кликните по карте и выполните ячейку снова")

if selected_coordinates is None:
    raise ValueError("Точка проекта не выбрана. Кликните по карте и выполните ячейку снова")

proj_lat, proj_lon = selected_coordinates

coordinate_str = f"{proj_lat:.6f}, {proj_lon:.6f}"
print("Точка проекта:", coordinate_str)

