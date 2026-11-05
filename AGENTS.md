# AGENTS.md

Инструкции для AI-агентов, работающих с репозиторием **Avito Parser + VK Publisher**.

## Кратко

Парсер объявлений Авито (Selenium) + автопостинг в сообщество VK.
Без фреймворков: `stdlib http.server` (админка), `argparse` (CLI), `sqlite3` (БД), `requests` (VK API), `selenium` (браузер).
Всё настраивается через `.env` — **не правьте код для изменения параметров**.

## Структура

```
.
├── main.py                # CLI: парсинг + постинг (argparse, --watch)
├── publisher.py           # CLI: публикация из БД в VK (standalone)
├── webui.py               # Веб-админка (stdlib http.server + cron)
├── webui_page.py          # HTML/CSS/JS интерфейса админки
├── requirements.txt       # selenium, requests, python-dotenv, schedule, Pillow
├── Dockerfile             # Debian + Python 3.12 + Chromium
├── docker-compose.yml     # сервис webui (порт 8000, volumes data/, logs/)
├── .env.example           # шаблон конфигурации
├── avito_parser/
│   ├── __init__.py        # экспорты пакета
│   ├── config.py          # Config, ParserConfig, VkConfig, BrowserConfig (.env)
│   ├── browser.py         # запуск Chrome (anti-detect, UA-ротация, прокси)
│   ├── human.py           # имитация поведения человека
│   ├── scraper.py         # парсинг выдачи и карточек (Selenium)
│   ├── photos.py          # скачивание фотографий
│   ├── database.py        # SQLite avito.db, схемы, DEFAULT_SETTINGS
│   ├── export.py          # CSV / JSON выгрузка
│   └── vk_publisher.py    # VK API: wall.post, фото, ошибки (27, 14, 6/9/29, 902)
├── tests/
│   └── vk_flow_test.py    # smoke-тест VK-флоу (dry-run, group-check, mock)
├── data/                  # авито.db, photos/ — на хосте (volume)
└── logs/                  # avito_parser.log — на хосте (volume)
```

## Золотые правила

1. **`.env` — источник правды.** Параметры парсера, VK, браузера читаются из окружения. Если нужно добавить настройку — добавьте в `config.py` + `.env.example` + `webui_page.py` (Настройки).
2. **БД — `avito_parser/database.py`.** Миграции в `_migrate()`. `DEFAULT_SETTINGS` (строка 368) — дефолты настроек админки. Приоритет: БД > `.env` > код.
3. **Webui — stdlib `http.server`.** Никаких Django/FastAPI. GET/POST в `Handler.do_GET` / `do_POST`. Роуты — `if path == ...` / `if route == ...`.
4. **Фоновые задачи — `Job` в памяти.** `PublishService` и `ParseService` хранят `jobs: dict[str, Job]`. `SchedulerService` — цикл парсинг → постинг → сон.
5. **`webui_page.py` — одна большая строка `PAGE` в Python.** Это HTML-шаблон. CSS inline в `<style>`, JS inline в `<script>`. Правки — через `edit_file` на подстроку.
6. **VK-фото через community-токен невозможен (код 27).** `vk_publisher.py:288-296` — генерирует понятную ошибку. Для фото нужен user-ключ standalone-приложения (OAuth).
7. **Не удаляйте `.env` при деплое.** Скрипты деплоя должны делать бэкап перед перезаписью.
8. **Docker не копирует `.env` (`.dockerignore`).** Передаётся через `env_file: .env`.

## Ключевые компоненты

### `config.py`

```python
Config.load() → Config(
    browser=BrowserConfig(...),   # HEADLESS_MODE, прокси, задержки, UA
    parser=ParserConfig(...),     # AVITO_TARGET_URL, PARSE_DETAILS, MAX_RETRIES
    vk=VkConfig(...),             # VK_ACCESS_TOKEN, VK_GROUP_ID, VK_APP_ID, шаблон
    admin_username, admin_password, admin_secret  # админка
)
```

Все поля — из переменных окружения с дефолтами. `_unescape()` разбирает `\n` в шаблонах поста.

### `database.py`

Схемы: `parsed_ads` (основная таблица), `sources` (отслеживаемые ссылки), `settings` (настройки админки).

Ключевые методы:
- `save_ad(ad, update=True)` — дедупликация по `avito_id`
- `get_unposted(limit)` → очередь для постинга
- `mark_posted(avito_id, posted=True, posted_at, vk_post_id, vk_post_url)`
- `list_ads(flt, q, limit, offset)` — фильтрация + поиск
- `counts_by_filter()` → `{'all', 'pending', 'posted', 'partial'}`
- `setting_get/set/bulk` — настройки админки
- `register_source / touch_source / set_source_enabled` — источники

### `webui.py`

**Классы:**
- `AuthService` — HMAC cookie-сессии (`issue` / `verify` / `check_login`)
- `Job` — задача (id, params, status, progress, log, posts, error, elapsed)
- `PublishService` — постинг (`submit` / `submit_one` / `_publish`)
- `ParseService` — парсинг (`submit` / `_run` / `_config_for` / `_ensure_scraper`)
- `SchedulerService` — крон (`_loop`: parse → publish → sleep)
- `Handler(BaseHTTPRequestHandler)` — HTTP-обработчик

**GET роуты:**
| Путь | Описание |
|---|---|
| `/` | страница админки (PAGE) |
| `/login` | форма входа |
| `/logout` | сброс cookie |
| `/api/state` | полное состояние (vk, scheduler, db, sources, settings, recent) |
| `/api/listings` | объявления (flt, q, page, per) + counts |
| `/api/jobs` | журнал задач |
| `/api/logs` | хост лога + хвост строк |
| `/api/proxy` | статус прокси |
| `/api/preview` | предпросмотр следующего поста |
| `/api/sources` | CRUD источников |
| `/api/ads` | POST: delete, requeue |
| `/api/scheduler` | POST: пауза крона |
| `/api/settings` | POST: bulk-обновление настроек |
| `/export.csv` | выгрузка CSV с BOM |
| `/photo` | отдача скачанного фото |
| `/job/<id>` | статус задачи, прогресс, лог (40 последних строк), ads, posts |
| `/job/<id>/raw` | то же + params, sources, proxy_used |
| `/vk` | описание VK-канала (JSON: токен, сообщество, очередь) |

**POST роуты:**
| Путь | Описание |
|---|---|
| `/login` | вход (JSON: username, password) → cookie |
| `/parse` | разовый парсинг (URL или sources) → Job |
| `/vk/publish` | пакетный постинг → Job |
| `/vk/publish-one` | одно объявление → Job |

**CLI-флаги `webui.py`:**
- `--host`, `--port` — адрес
- `--no-headless` — показывать окно браузера
- `--no-auth` — без входа (отладка)
- `--no-cron` — без фоновых задач

### `vk_publisher.py`

**Классы ошибок:**
- `VkError(message, code, response)` — базовая
- `VkCaptchaRequired(message, captcha_sid, captcha_img, code=14)`
- `VkPublishLimit(message, code=902)` — фатальная ошибка (spam/ограничения, коды `FATAL_CODES` = 102–104, 205, 236, 510, 901–902)

**`VKPublisher` методы:**
- `_call(method, **params)` — обёртка над `requests` с retry: код 14 → `VkCaptchaRequired`, `FATAL_CODES` → `VkPublishLimit`, коды 6/9/29 → пауза и повтор
- `resolve_group()` → name, id, wall, is_admin (группа 27 → fallback на `wall.get`)
- `_get_upload_server()` → `photos.getWallUploadServer` (код 27 → подсказка про user-ключ)
- `upload_photo(path)` → upload → photos.saveWallPhoto → возвращает `photo,-gid_aid`
- `collect_photos(ad, allow_download)` → список `Path` (локально + докачка)
- `build_message(ad)` → шаблон `{title} {price} {description} {url}`
- `build_attachments(ad)` → `photo-<gid>_<id>` × N
- `post_ad(ad, dry_run, skip_publish=False)` → wall.post
- `publish_pending(limit, dry_run)` → цикл с таймингом

**Паттерн post_ad:**
1. `build_message` — текст
2. `collect_photos` → `build_attachments` — фото (локальные + докачка)
3. `wait_interval` — пауза между постами
4. `wall.post(group_id, message, attachments, from_group)`

### `scraper.py`

**`AvitoScraper` методы:**
- `scrape(url, pages, with_details, with_photos, only_new, limit)` → список `dict`
- `_check_blocked()` → ip_block, proxy-пул, fallback
- `_load_page(url)` → Selenium с anti-detect
- `_parse_list_page(html)` → карточки выдачи
- `_parse_detail(ad, driver)` → описание + фото со страницы

**`source_label(url)`** → человекочитаемая метка (`avito.ru/moskva/avtomobili` → `Москва / Авто`).

## Зависимости

| Пакет | Версия | Зачем |
|---|---|---|
| `selenium` | 4.52.0 | Браузер для парсинга |
| `requests` | 2.32.5 | VK API, прокси-чеки |
| `python-dotenv` | 1.2.1 | `.env` |
| `schedule` | 1.2.2 | Cron (не используется в webui, но в requirements) |
| `Pillow` | 13.0.0 | Обработка фото |

## Деплой

### Локально

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполнить .env
python webui.py --host 127.0.0.1 --port 8000
```

### Docker

```bash
docker compose up --build
```

### Сервер (Ubuntu, paramiko)

Скрипты деплоя в `/tmp/deploy_stage*.py` — заливают файлы, правят `.env`, `docker compose up -d --build`.
**Всегда сохраняйте бэкап `.env` перед перезаписью.**

## Стиль кода

- **Русские комментарии и docstrings.** Сообщения об ошибках — на русском.
- **Типизация.** `def foo(x: int) -> str:` — везде.
- **Файлы не длинные.** `webui.py` ~1040 строк, `webui_page.py` ~1170 строк, `scraper.py` ~946 строк, `vk_publisher.py` ~679 строк.
- **Нет фреймворков.** Только stdlib + selenium + requests.
- **Без внешних секретов.** `.env` в `.gitignore`. `ADMIN_SECRET` — HMAC-подпись сессий.
- **Без `print` в продакшене.** Логирование через `get_logger("avito.<модуль>")` — неймспейсы: `avito.db`, `avito.scraper`, `avito.browser`, `avito.human`, `avito.photos`, `avito.vk`, `avito.webui`, `avito.main`, `avito.export`.

## Частые операции

### Добавить настройку
1. `config.py` — добавить поле в нужный `@dataclass`
2. `.env.example` — описание + дефолт
3. `database.py DEFAULT_SETTINGS` — если перекрывается из админки
4. `webui_page.py` — добавить поле в форму Настроек
5. `webui.py` — добавить в `_handle_settings` `allowed` set

### Добавить API-эндпоинт в админку
1. `webui.py` — `do_GET`: `if path == "/api/new": self._json(...)`
2. `webui.py` — `do_POST`: `if route == "/api/new": ...`
3. `webui_page.py` — добавить вызов `api('/api/new')` в JS

### Отладка webui
```bash
python webui.py --no-auth --no-cron --port 8012
```
- `--no-auth` — без входа
- `--no-cron` — без фонового крона (парсинг/постинг по кнопкам)

### Проверить VK-ключ

```bash
python publisher.py --check
python publisher.py --preview --limit 3
```

### Восстановить .env на сервере

Если `.env` на сервере перетёрт — восстановить из бэкапа:
```bash
cp /opt/avito/.env.bak /opt/avito/.env
cd /opt/avito && docker compose up -d --force-recreate
```
