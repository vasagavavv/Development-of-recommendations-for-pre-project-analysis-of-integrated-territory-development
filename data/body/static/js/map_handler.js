// Глобальные переменные
let map;
let marker = null;
let selectedCoords = null;

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

    // Обновляем состояние кнопки отправки (если есть)
    try {
        const sendBtn = document.getElementById('sendBtn');
        if (sendBtn) sendBtn.disabled = false;
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
                // Оставляем кнопку заблокированной и показываем "Отправлено"
                btn.textContent = 'Отправлено';
            } else {
                // Восстанавливаем исходный текст и снова разрешаем кнопку
                if (originalBtnText !== null) btn.textContent = originalBtnText;
                btn.disabled = false;
            }
        }
        // очистить сообщение через 30 секунд
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

// Экспортируем функции для использования в других скриптах
window.mapAPI = {
    getSelectedCoords: () => selectedCoords,
    getSavedCoordinates: getSavedCoordinates,
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
        // если в localStorage уже есть координаты — активируем кнопку
        const saved = getSavedCoordinates();
        if (saved) sendBtnInit.disabled = false;
    }
} catch (e) {
    // ignore in non-browser contexts
}
