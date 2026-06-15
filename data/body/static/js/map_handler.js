// Глобальные переменные
let map;
let marker = null;
let selectedCoords = null;
let isochronesLayer = null;

// Функция инициализации карты
function initMap(city, region, centerLat, centerLon, zoomLevel) {
    // Создаем карту
    map = L.map('map').setView([centerLat, centerLon], zoomLevel);

    // Добавляем слои карты
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19
    }).addTo(map);

    // Обработчик клика
    map.on('click', function(e) {
        const lat = e.latlng.lat;
        const lng = e.latlng.lng;

        onMapClick(lat, lng, city, region);
    });

    console.log('Карта инициализирована:', city, region);
}

// Обработчик клика по карте
function onMapClick(lat, lng, city, region) {
    selectedCoords = {lat: lat, lng: lng};

    // Обновляем информацию на странице
    document.getElementById('coords').innerHTML =
        `Выбрана точка: ${lat.toFixed(6)}, ${lng.toFixed(6)}`;

    // Обновляем маркер
    updateMarker(lat, lng, city, region);

    // Сохраняем координаты в локальное хранилище или отправляем на сервер
    saveCoordinates(lat, lng);
}

// Обновление маркера на карте
function updateMarker(lat, lng, city, region) {
    if (marker) {
        map.removeLayer(marker);
    }

    marker = L.marker([lat, lng]).addTo(map);

    marker.bindPopup(`
        <strong>${city}, ${region}</strong><br>
        Широта: ${lat.toFixed(6)}<br>
        Долгота: ${lng.toFixed(6)}
    `).openPopup();
}

// Сохранение координат
function saveCoordinates(lat, lng) {
    // Вариант 1: Сохраняем в localStorage
    localStorage.setItem('selected_coords', JSON.stringify({
        lat: lat,
        lng: lng,
        timestamp: new Date().toISOString()
    }));

    // Вариант 2: Отправляем на локальный сервер (если используется)
    if (window.pywebview && window.pywebview.api) {
        window.pywebview.api.save_coords(lat, lng);
    }

    // Вариант 3: Выводим в консоль
    console.log(`Координаты сохранены: ${lat.toFixed(6)}, ${lng.toFixed(6)}`);

    // Обновляем состояние кнопок (если они есть)
    try {
        const sendBtn = document.getElementById('sendBtn');
        if (sendBtn) sendBtn.disabled = false;

        const isoBtn = document.getElementById('isoBtn');
        if (isoBtn) isoBtn.disabled = false;
    } catch (e) {
        // ignore
    }
}

// Отправляет выбранные координаты на сервер по нажатию кнопки
function sendSelectedCoordsToServer() {
    const statusEl = document.getElementById('status');
    if (!statusEl) return;

    const payload = selectedCoords || getSavedCoordinates();
    if (!payload) {
        statusEl.textContent = 'Нет выбранной точки';
        statusEl.className = 'status-error';
        return;
    }

    // Блокируем кнопку на время отправки
    const btn = document.getElementById('sendBtn');
    let originalBtnText = null;
    if (btn) {
        originalBtnText = btn.textContent;
        btn.disabled = true;
        btn.setAttribute('aria-disabled', 'true');
        btn.classList.add('sending');
        btn.textContent = 'Обработка...';
    }
    statusEl.textContent = 'Отправка...';
    statusEl.className = '';

    let assignSuccess = false;

    fetch('/save_coords', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat: payload.lat, lng: payload.lng })
    }).then(resp => resp.json()).then(data => {
        console.log('Сервер ответил:', data);
        if (data && data.classification) {
            const cat = data.classification.category || null;
            if (cat) {
                statusEl.textContent = `Категория присвоена: ${cat}`;
                statusEl.className = 'status-success';
                assignSuccess = true;
            } else {
                statusEl.textContent = 'Типология не подтверждена для выбранной точки';
                statusEl.className = 'status-error';
            }
        } else if (data && data.status === 'error') {
            statusEl.textContent = `Ошибка классификации: ${data.message || 'неизвестная ошибка'}`;
            statusEl.className = 'status-error';
        } else {
            statusEl.textContent = 'Успешно отправлено';
            statusEl.className = 'status-success';
        }
    }).catch(err => {
        statusEl.textContent = 'Ошибка отправки';
        statusEl.className = 'status-error';
        console.error('Ошибка отправки координат:', err);
    }).finally(() => {
        if (btn) {
            btn.classList.remove('sending');
            btn.removeAttribute('aria-disabled');
            if (assignSuccess) {
                btn.textContent = 'Отправлено';
            } else {
                if (originalBtnText !== null) btn.textContent = originalBtnText;
                btn.disabled = false;
            }
        }
        setTimeout(() => { statusEl.textContent = ''; statusEl.className = ''; }, 30000);
    });
}

// Функция для получения сохраненных координат
function getSavedCoordinates() {
    const saved = localStorage.getItem('selected_coords');
    if (saved) {
        return JSON.parse(saved);
    }
    return null;
}

// Загрузка и отображение изохронов на карте
function loadIsochrones() {
    const statusEl = document.getElementById('status');
    if (!selectedCoords) {
        if (statusEl) statusEl.textContent = 'Сначала выберите точку на карте';
        return;
    }

    if (statusEl) statusEl.textContent = 'Загрузка изохронов...';

    fetch('/isochrones')
        .then(resp => resp.json())
        .then(data => {
            if (data.status === 'success') {
                displayIsochrones(data.geojson);
                if (statusEl) {
                    statusEl.textContent = `Изохроны загружены (${data.node_count} узлов)`;
                    statusEl.className = 'status-success';
                }
            } else {
                if (statusEl) {
                    statusEl.textContent = `Ошибка изохронов: ${data.message}`;
                    statusEl.className = 'status-error';
                }
                console.error('Ошибка изохронов:', data.message);
            }
        })
        .catch(err => {
            if (statusEl) {
                statusEl.textContent = 'Ошибка загрузки изохронов';
                statusEl.className = 'status-error';
            }
            console.error('Ошибка загрузки изохронов:', err);
        });
}


// Загрузка и отображение точек метрик (POI)
function loadMetricPoints() {
    const statusEl = document.getElementById('status');
    if (!selectedCoords) {
        if (statusEl) statusEl.textContent = 'Сначала выберите точку на карте';
        return;
    }
    if (statusEl) statusEl.textContent = 'Загрузка POI...';

    fetch('/metric_points')
        .then(resp => resp.json())
        .then(data => {
            if (data.status === 'success') {
                displayIsochrones(data.isochrones);
                displayMetricPoints(data.points, data.colors);
                if (statusEl) {
                    statusEl.textContent = 'POI загружены';
                    statusEl.className = 'status-success';
                }
            } else {
                if (statusEl) statusEl.textContent = 'Ошибка загрузки POI';
            }
        }).catch(err => {
            if (statusEl) statusEl.textContent = 'Ошибка загрузки POI';
            console.error('Ошибка metric_points:', err);
        });
}


let metricLayers = {};
let metricCluster = null;

function displayMetricPoints(pointsGeojson, colors) {
    if (metricCluster) {
        map.removeLayer(metricCluster);
        metricCluster = null;
    }

    metricCluster = L.markerClusterGroup();

    const geojsonLayer = L.geoJSON(pointsGeojson, {
        pointToLayer: function(feature, latlng) {
            const m = feature.properties.metric || feature.properties.metric;
            const col = feature.properties.color || (colors && (colors[m] || colors['default'])) || '#cccccc';
            const marker = L.circleMarker(latlng, {
                radius: 6,
                fillColor: col,
                color: '#000',
                weight: 1,
                opacity: 1,
                fillOpacity: 0.9
            });
            let popup = `<strong>${m}</strong>`;
            if (feature.properties && feature.properties.tags) {
                popup += '<br/>' + Object.entries(feature.properties.tags).map(([k,v]) => `${k}: ${v}`).join('<br/>');
            }
            if (feature.properties && feature.properties.zone) {
                popup += `<br/><em>Зона: ${feature.properties.zone}</em>`;
            }
            marker.bindPopup(popup);
            marker.on('click', function() { marker.openPopup(); });
            return marker;
        }
    });

    metricCluster.addLayer(geojsonLayer);
    metricCluster.addTo(map);

    // clear and rebuild legend
    const legend = document.getElementById('legend');
    if (legend) legend.innerHTML = '';
    // build legend from colors mapping
    if (colors) {
        Object.keys(colors).forEach(metric => {
            if (metric === 'default') return;
            addLegendEntry(metric, colors[metric]);
        });
    }
}

function addLegendEntry(metric, color) {
    // simple legend append
    const legend = document.getElementById('legend');
    if (!legend) return;
    const item = document.createElement('div');
    item.className = 'legend-item';
    item.innerHTML = `<span class="legend-color" style="background:${color}"></span> ${metric}`;
    legend.appendChild(item);
}

// Отображение изохронов на карте
function displayIsochrones(geojson) {
    // Удаляем старые изохроны если были
    if (isochronesLayer) {
        map.removeLayer(isochronesLayer);
    }

    isochronesLayer = L.geoJSON(geojson, {
        style: function(feature) {
            return {
                color: feature.properties['stroke'] || '#f9b528',
                weight: feature.properties['stroke-width'] || 2,
                opacity: feature.properties['stroke-opacity'] || 0.5,
                fillColor: feature.properties['fill'] || '#f9b528',
                fillOpacity: feature.properties['fill-opacity'] || 0.5
            };
        },
        onEachFeature: function(feature, layer) {
            if (feature.properties) {
                const props = feature.properties;
                const popupContent = `
                    <strong>Кольцо ${props.ring_index}</strong><br>
                    Время: ${props.time_range || 'N/A'} сек<br>
                    Прозрачность: ${(props['fill-opacity'] * 100).toFixed(0)}%
                `;
                layer.bindPopup(popupContent);
            }
        }
    }).addTo(map);
}

// Экспортируем функции для использования в других скриптах
window.mapAPI = {
    getSelectedCoords: () => selectedCoords,
    getSavedCoordinates: getSavedCoordinates,
    loadIsochrones: loadIsochrones,
    clearMarker: () => {
        if (marker) {
            map.removeLayer(marker);
            marker = null;
        }
    }
};

// Инициализация: повесим обработчик кнопки отправки и установим её состояние
try {
    const sendBtnInit = document.getElementById('sendBtn');
    if (sendBtnInit) {
        sendBtnInit.addEventListener('click', sendSelectedCoordsToServer);
        const saved = getSavedCoordinates();
        if (saved) sendBtnInit.disabled = false;
    }

    // Повешиваем обработчик для кнопки загрузки изохронов если она есть
    const isoBtnInit = document.getElementById('isoBtn');
    if (isoBtnInit) {
        isoBtnInit.addEventListener('click', loadIsochrones);
    }
    const metricBtnInit = document.getElementById('metricBtn');
    if (metricBtnInit) {
        metricBtnInit.addEventListener('click', loadMetricPoints);
        const saved = getSavedCoordinates();
        if (saved) metricBtnInit.disabled = false;
    }
} catch (e) {
    // ignore in non-browser contexts
}
