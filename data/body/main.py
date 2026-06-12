from flask import Flask, render_template, jsonify, request, send_from_directory
from category_process.category import classify_point, classify_and_export_csv
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

# Flask уже обслуживает файлы из static_folder, дополнительный маршрут не нужен

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

