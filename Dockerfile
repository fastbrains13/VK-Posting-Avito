# =========================================================
# Dockerfile для Avito Parser + VK Publisher
# Базовый образ: Debian + Python 3.12 + Chromium
# =========================================================

FROM python:3.12-slim

# --- 1. Переменные окружения ---
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Moscow \
    CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

# --- 2. Системные зависимости + Chromium ---
# chromium сам тянет все библиотеки (nss/gbm/pango и т.д.); шрифты нужны
# для кириллицы, иначе Selenium падает на русских названиях объявлений
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
        fonts-liberation \
        fonts-dejavu-core \
        fonts-noto-core \
        curl \
        && rm -rf /var/lib/apt/lists/*

# --- 3. Зависимости Python ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- 4. Код проекта ---
COPY . .

# --- 5. Директории для данных (volume) ---
RUN mkdir -p /app/data/photos /app/data/logs

# --- 6. Права на запуск (парсер работает как root в контейнере) ---
# --no-sandbox добавляется в browser.py автоматически при is_container
RUN useradd -m -u 1000 parser && \
    chown -R parser:parser /app || true

# --- 7. Entrypoint ---
# Запуск по умолчанию: CLI-скрипт. Для UI вызываем python webui.py.
CMD ["python", "main.py", "--help"]
