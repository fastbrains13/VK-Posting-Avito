# AGENTS.md

Инструкции для AI-агентов, работающих с репозиторием **Avito → VK MVP**.

## Что это

Django-приложение: парсит страницу выдачи Авито, даёт вручную опубликовать выбранное объявление в сообщество VK с фотографиями.

Текущий режим — **ручной MVP**:

- один пользовательский токен VK;
- одно активное сообщество;
- один источник Авито;
- только указанная страница выдачи, без пагинации;
- детали и фото объявления загружаются по кнопке;
- только ручная публикация;
- один пост на пару «объявление + сообщество»;
- до 10 фото в посте.

Не добавляйте автопостинг, планировщик, мультисообщество или конструктор шаблонов без отдельного запроса.

## Стек

- Python 3.12, Django 5.1
- PostgreSQL 16 в Docker; SQLite для локальной разработки
- Selenium + Chromium/ChromeDriver
- requests, PySocks
- Gunicorn, WhiteNoise
- Docker Compose, Caddy (опционально)

## Структура

```text
manage.py
config/                  # settings, urls, wsgi/asgi
core/                    # VKAccount, VKCommunity, ProxyEndpoint, JobRun
  crypto.py              # Fernet-шифрование токенов
  proxies.py             # парсинг, проверка, ротация прокси
  management/commands/import_proxies.py
avito/                   # AvitoSource, Ad, AdPhoto
  client.py              # Selenium: выдача, объявление, фото
  services.py            # parse_listing / parse_detail
publishing/              # Publication, VKClient, renderer, services
jobs/                    # handlers + management/commands/worker.py
web/                     # views, urls, templates, static
data/                    # media/, chrome-profile/ — volume, не в git
Dockerfile
docker-compose.yml
Caddyfile.example
.env.example
README.md
```

## Золотые правила

1. **Секреты только в `.env`.** Токены VK, пароль БД, `DJANGO_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` не коммитить. Токены VK и пароли прокси в БД шифруются.
2. **Настройки пользователя — в БД/UI.** Интервал, максимум фото, обязательность фото — в `VKCommunity`; прокси — в `ProxyEndpoint`. Инфраструктурные параметры (БД, порт, таймауты) — в `.env`.
3. **Один общий пул прокси.** Прокси проверяется и для Авито, и для VK; рабочий статус общий. Новые нерабочие прокси не сохраняются. Не создавайте отдельные пулы без запроса.
4. **Ротация прокси.** `core.proxies.pick_proxy()` выбирает давно не использованный рабочий прокси. Авито использует `require_browser=True`; VK — обычный вызов.
5. **Фото VK — только пользовательский токен.** Ключ сообщества не умеет `photos.getWallUploadServer` (код 27). `wall.post` может требовать ключ сообщества (код 15).
6. **Без повторов.** Уникальность `Publication(ad, community)`. Повторная попытка — та же запись, не новая. Уже загруженные вложения переиспользуются; не загружайте одни и те же фото повторно без необходимости.
7. **Selenium — только в воркере.** Веб-процесс не запускает браузер. Парсинг/публикация — задачи `JobRun`, их выполняет `python manage.py worker`.
8. **Никаких фреймворков сверху.** Django + серверные шаблоны + ванильный JS. Не добавлять React/DRF/FastAPI без запроса.
9. **Миграции обязательны.** После изменения моделей: `makemigrations` + `migrate`; миграции коммитить.
10. **Проверки перед сдачей.** `python manage.py test`, `ruff check .`, `python manage.py check`, при необходимости `makemigrations --check`.

## Ключевые компоненты

### `core/models.py`

- `VKAccount` — пользовательский токен, владелец, статус.
- `VKCommunity` — группа, права, ключ сообщества, интервал, лимит фото.
- `ProxyEndpoint` — единый пул: scheme `http|socks4|socks5`, host, port, логин, зашифрованный пароль, статус, счётчики.
- `JobRun` — ручная задача: `parse_listing`, `parse_detail`, `publish`; статусы и лог.

### `core/proxies.py`

- `parse_proxy_line` — форматы `http://`, `socks4://`, `socks5://`, `host:port`; без схемы — автоопределение.
- `check_proxy` — проверка через Авито и VK API; рабочий только если прошли обе.
- `add_proxy_lines` — добавить/проверить пачку, сохранить только рабочие, добавить к текущим.
- `recheck_proxy` / `recheck_all` — повторная проверка.
- `pick_proxy(require_browser=False)` — ротация.
- `import_proxies` — CLI для больших файлов.

### `avito/client.py`

- Selenium Chrome, постоянный профиль `data/chrome-profile`.
- CDP-навигация без ожидания long-poll, ожидание снятия челленджа.
- Прокси: `--proxy-server`; HTTP-авторизация best-effort через CDP.
- `fetch_listing`, `fetch_detail`, `download_photos` (через requests; SOCKS с авторизацией поддерживается).

### `publishing/vk.py`

- `VKClient(token, proxy=None)`.
- `validate`, `list_admin_communities`, `community_info`, `upload_photo`, `post`, `recent_posts`.
- Ошибки: 6/9/29 — retry, 14 — captcha, 15/27 — понятные подсказки, 902 — стоп.
- `VKTemporaryPhotoLimit` — временный лимит фото VK; не ретраить сразу.

### `publishing/services.py`

- подключение аккаунта/сообщества;
- `set_community_token` — сохранение ключа сообщества без `wall.get` (ключ сообщества не умеет этот метод);
- `create_publish_job` — проверки и постановка задачи;
- `publish_publication` — фото пользовательским токеном, `wall.post` ключом сообщества (если есть), защита от дублей.

### `web/`

- `views.py` — страницы и действия;
- `templates/web/` — отдельные страницы;
- `static/css/app.css`, `static/js/app.js`;
- настройки: `/settings/` — сообщество и единый пул прокси.

## Частые операции

### Запуск локально

```bash
source .venv/bin/activate
python manage.py migrate
python manage.py runserver 127.0.0.1:8000
# второй терминал:
python manage.py worker
```

Или `./run_local.sh` / `./stop_local.sh`.

### Полный прогон проверок

```bash
python manage.py check
python manage.py test
ruff check .
python manage.py makemigrations --check --dry-run
```

### Добавить страницу

1. `web/templates/web/<name>.html`.
2. `web/views.py` — view с `@login_required`.
3. `web/urls.py` — route.
4. `web/templates/web/base.html` — пункт навигации.
5. Тест на GET страницы.

### Добавить поле в модель

1. `models.py` — поле.
2. `makemigrations` + `migrate`.
3. Форма/шаблон.
4. Тест.

### Добавить прокси-схему

1. `ProxyEndpoint.SCHEME_*` + choices.
2. `requests_url`/`browser_supported`/`chrome_url`.
3. `parse_proxy_line`.
4. Проверка и тесты.

### Массовый импорт прокси

```bash
python manage.py import_proxies ~/Downloads/data.txt --workers 100 --timeout 4
python manage.py import_proxies ~/Downloads/data.txt --dry-run
```

На сервере в Docker:

```bash
docker compose cp ~/data.txt web:/tmp/data.txt
docker compose exec web python manage.py import_proxies /tmp/data.txt --workers 100 --timeout 4
```

### Перезапуск после изменений

```bash
./stop_local.sh
./run_local.sh
```

В Docker:

```bash
docker compose up -d --build
docker compose logs --tail=50 web worker
```

### Деплой на сервер

Полная пошаговая инструкция — в [README.md](README.md), раздел «Развёртывание на сервере». Минимальные требования: 1 vCPU, 2 ГБ RAM, 20 ГБ SSD, swap. Рекомендуется 2 vCPU / 4 ГБ.

## Правила кода

- Русские комментарии и сообщения об ошибках.
- Типизация функций и методов.
- Бизнес-логика — в сервисах, не во view и не в моделях.
- Внешние интеграции — за клиентами (`AvitoClient`, `VKClient`).
- Не логировать токены, пароли и содержимое прокси-URL с авторизацией.
- Не использовать `print` в библиотечном коде; только logger/CLI.
- Не оставлять мёртвый код и неиспользуемые зависимости.
- Держать файлы небольшими; `web/views.py` уже крупный — новые разделы выносить в отдельные модули.

## Безопасность

- `.env`, `data/`, `Caddyfile` — не коммитить.
- Токены VK и пароли прокси — только в зашифрованном виде.
- `TOKEN_ENCRYPTION_KEY` менять нельзя без перевыпуска токенов.
- Не публиковать порт 8000 наружу; использовать SSH-туннель или Caddy.
- При утечке токена: отозвать в VK, заменить, проверить посты.
- Прокси-пароли не выводить в UI и логи.

## Известные ограничения

- Код 15 VK: `wall.post` только для standalone-приложений или с ключом сообщества.
- Код 27 VK: ключ сообщества не загружает фото.
- Пустой `photo` / 405: временный лимит VK; ждать, не повторять часто.
- SOCKS5 с паролем не работает в Chrome; только `requests`.
- Avito может отдавать челлендж; сохранять профиль, не спамить.
- Один источник/сообщество/аккаунт и ручная публикация — это текущий scope, не баг.

## Definition of Done

- Модели/миграции согласованы.
- `python manage.py test` — зелёный.
- `ruff check .` — чисто.
- `python manage.py check` — без ошибок.
- Новые внешние интеграции имеют тест на заглушке.
- README/AGENTS обновлены, если изменились запуск, настройки или деплой.
