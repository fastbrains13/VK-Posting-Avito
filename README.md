# Avito Parser + VK Publisher

Парсер объявлений Авито (Selenium) с автоматической публикацией в сообщество ВКонтакте.
Работает из CLI, через веб-админку или в Docker. Настройка — только `.env`, без правки кода.

## Что внутри

| Файл / пакет | Назначение |
|---|---|
| `main.py` | CLI: парсинг выдачи/карточек, сохранение в БД, постинг в VK |
| `publisher.py` | CLI: публикация из `avito.db` в VK (один пост, очередь, watch, тест) |
| `webui.py` | Веб-админка (stdlib `http.server`), фоновый крон (парсинг → постинг) |
| `webui_page.py` | HTML/CSS/JS интерфейса админки |
| `avito_parser/` | Пакет ядра |
| `avito_parser/config.py` | Конфиг из `.env` (парсер, браузер, VK, админка) |
| `avito_parser/browser.py` | Запуск Chrome (anti-detect, UA-ротация, прокси-пул, fallback на прямой IP) |
| `avito_parser/human.py` | Имитация поведения человека (случайные задержки, скролл) |
| `avito_parser/scraper.py` | Парсинг выдачи и карточек (Selenium) |
| `avito_parser/photos.py` | Скачивание фотографий объявления |
| `avito_parser/database.py` | SQLite `avito.db`, дедупликация, источники, настройки админки |
| `avito_parser/export.py` | Выгрузка в CSV / JSON |
| `avito_parser/vk_publisher.py` | Публикация объявлений в VK (фото + текст + ссылка) |
| `tests/vk_flow_test.py` | Тест VK-флоу (dry-run + group-check на заглушках) |

## Быстрый старт

### 1. Виртуальное окружение

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

### 2. Конфигурация

```bash
cp .env.example .env
```

Заполните в `.env` как минимум:

```
# Авито
AVITO_TARGET_URL=https://www.avito.ru/.../mobile-ASgBAgICAUSwwQ2I_Dc

# VK — ключ сообщества (права photos, wall, groups)
VK_ACCESS_TOKEN=vk1.a.…
VK_GROUP_ID=public123456789

# Админка
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-strong-password
ADMIN_SECRET=long-random-hex
```

### 3. Запуск

#### CLI — разовый прогон

```bash
python main.py --details --photos --publish
```

#### CLI — режим мониторинга (парсинг + постинг каждые N минут)

```bash
python main.py --watch 900 --details --photos --publish
```

#### Веб-админка

```bash
python webui.py --host 0.0.0.0 --port 8000
```

Откройте `http://localhost:8000`. Флаги для отладки:
- `--no-auth` — без входа (локально!)
- `--no-cron` — без фоновых задач (парсинг/постинг по кнопкам)

#### Docker

```bash
docker compose up --build
```

Контейнер `avito_webui`: порт 8000, healthcheck каждые 30 с, данные на хосте через `./data` и `./logs`.

**Подробное развёртывание на боевом сервере** (подготовка, `.env`, доступ через SSH-туннель,
обновление, бэкапы, типовые проблемы) — [DEPLOY.md](DEPLOY.md).

## CLI-справка

### main.py — парсер

```
python main.py "https://..." "https://..."          # парсить указанные
python main.py                                       # из AVITO_TARGET_URL / SOURCES_FILE
python main.py --details --photos                    # с описанием и фото
python main.py --publish                             # сразу постить в VK
python main.py --publish-dry-run                     # собрать посты, не отправляя
python main.py --watch 900 --details --photos --publish  # дежурный режим, 15 мин
python main.py --csv out.csv --json out.json         # выгрузить результат
python main.py --stats                               # статистика базы
```

### publisher.py — постинг в VK

```
python publisher.py --check                 # проверить токен и права сообщества
python publisher.py --preview               # тексты постов без отправки
python publisher.py --publish               # выложить всю очередь
python publisher.py --publish --limit 5     # только 5 постов
python publisher.py --publish --dry-run     # собрать, не отправляя
python publisher.py --ad 8309226157         # одно объявление
python publisher.py --watch                 # дежурить: постить новые
python publisher.py --test "Тестовый пост"  # произвольный тестовый пост
python publisher.py --delete POST_ID        # удалить пост со стены
python publisher.py --stats                 # статистика очереди
```

## Веб-админка

7 разделов:

1. **Дашборд** — KPI (всего / в очереди / опубликовано / недолитые), конвейер (источники → очередь → VK), последние объявления, последние посты, расписание крона
2. **Объявления** — счётчики-фильтры (все / в очереди / опубликованные / недолитые), поиск, пагинация, действия (Опубликовать / В очередь / Удалить), экспорт CSV
3. **Источники** — список отслеживаемых ссылок, статистика прогона, вкл/выкл, удалить, разовый парсинг произвольной ссылки
4. **VK-канал** — состояние (сообщество, токен, фото), предпросмотр следующего поста, история опубликованных, настройки (интервал, пачка, только фото, OAuth-ключ)
5. **Задачи** — журнал всех фоновых задач с раскрываемыми логами
6. **Логи** — хвост `avito_parser.log`, авто-обновление, скачивание файла
7. **Настройки** — расписание крона, пауза крона, лимиты парсинга, статус прокси

### Постинг с фото

VK запрещает загрузку фото ключами сообщества (код ошибки 27). Для постов с картинками нужен **user-ключ standalone-приложения**.

1. В разделе **VK-канал** нажмите «Получить user-ключ (для фото)» — откроется OAuth-диалог VK
2. Разрешите права: `photos, wall, groups, offline`
3. Скопируйте `access_token=...` из адресной строки
4. Вставьте в поле «VK: ключ доступа» → «Сохранить»
5. Включите «Только посты с фото» → «Сохранить»

### Настройки

Параметры из админки сохраняются в БД и перекрывают `.env`. Полный список полей в `database.py:DEFAULT_SETTINGS`:

| Поле | По умолчанию | Описание |
|---|---|---|
| `parse_interval_min` | 15 | интервал парсинга, мин |
| `publish_interval_min` | 30 | интервал постинга, мин |
| `first_run_limit` | 10 | лимит объявлений при первом прогоне новой ссылки |
| `pages_per_source` | 1 | страниц выдачи на источник |
| `details_on` | 1 | качать описания |
| `photos_on` | 1 | качать фото |
| `vk_min_interval_sec` | 240 | пауза между постами, сек |
| `vk_require_photos` | 0 | постить без фото (community-токен не умеет photos) |
| `vk_max_photos_per_post` | 10 | макс фото в посте |
| `publish_batch` | 5 | объявлений за один цикл |
| `cron_paused` | 0 | пауза крона (1 = стоит) |
| `vk_access_token` | (пусто) | ключ VK (приоритет над .env) |
| `vk_group_id` | (пусто) | сообщество VK (приоритет над .env) |

## Архитектура

```
.env ──→ Config.load() ──→ ParserConfig / VkConfig / BrowserConfig
                          ──→ Database   (SQLite avito.db, WAL)
                          ──→ AvitoScraper (Selenium, browser.py, human.py, photos.py)
                          ──→ VKPublisher  (photos.getWallUploadServer, wall.post)

webui.py (stdlib http.server)
  ├─ Handler: GET/POST → /api/*, /export.csv, /login, /logout
  ├─ ParseService  (submit → Job → _run в фоне)
  ├─ PublishService (submit/submit_one → Job → _publish в фоне)
  └─ SchedulerService (cycle: parse → publish → sleep)

main.py / publisher.py — standalone CLI, не зависят от webui
```

## Известные ограничения

- **Фото через community-токен невозможны.** `photos.getWallUploadServer` возвращает код 27 для любых ключей сообщества (подтверждено VKCOM/vk-api-schema#242). Только user-ключ standalone-приложения.
- **wall.delete не работает с group-токеном.** Тестовые посты удаляются только вручную через интерфейс VK.
- **Прокси-пул.** Если все SOCKS5-прокси забанены, парсер падает на прямой IP (конфиг `PROXY_ALLOW_DIRECT=True`). Прямой IP Авито тоже банит (`ip_block`). Нужны свежие, не-датацентровые прокси.
- **1 CPU / 1 ГБ.** На сервере крон живёт внутри `webui.py` — отдельный worker не запускается, чтобы не спорить за память.

## Тесты

```bash
.venv/bin/python tests/vk_flow_test.py
```

`tests/vk_flow_test.py` — smoke-тест VK-флоу. Подменяет `requests.Session` фиктивным
клиентом, который отвечает ровно теми формами, что отдаёт VK, и проверяет 7 сценариев:

| # | Сценарий | Что проверяется |
|---|---|---|
| 1 | `ok` | загрузка фото → `wall.post` → отметка в БД; в загрузку файла не попадает `access_token` |
| 2 | `dup_photo` | дубликат снимка (код 107) не роняет пост — пост уходит без вложений |
| 2b | `dup_photo` + `require_photos` | пост осознанно пропускается, `wall.post` не вызывается |
| 3 | `captcha` | `VkCaptchaRequired` с `captcha_sid`/`captcha_img` |
| 4 | `spam` | `publish_pending` останавливает пачку, неудачный пост **не** отмечается опубликованным |
| 5 | `flood` | код 6 → повтор внутри `_call` (2 вызова `wall.post`) |
| 6 | `dry-run` | сеть не дёргается вообще (`CALLS == []`) |
| 7 | без токена | понятная `VkError` вместо Traceback |

Тест читает реальные jpg из `data/photos/*/*.jpg` (нужны хотя бы 3 файла) и пишет БД
в `/tmp/vk_test.db`. Финальный вывод — `ВСЕ ПРОВЕРКИ ПРОШЛИ`.

UI-смоук админки (headless Chrome, только read-only действия):

```bash
python webui.py --no-auth --no-cron --port 8012 &
node tests/ui_smoke.mjs http://127.0.0.1:8012/
# на сервере — через SSH-туннель (см. DEPLOY.md):
# ssh -p <порт> -N -L 8000:127.0.0.1:8000 root@<сервер>
node tests/ui_smoke.mjs http://127.0.0.1:8000/ admin '<ADMIN_PASSWORD>'
```

## Связи с ТЗ

| Раздел ТЗ | Реализация |
|---|---|
| 2.1 Парсер выдачи и карточек | `avito_parser/scraper.py` (Selenium, JS-рендер) |
| 2.2 Хранение в SQLite | `avito_parser/database.py` (WAL, дедупликация) |
| 2.3 CLI с флагами | `main.py` (argparse, --watch, --details, --photos, --publish) |
| 2.4 Публикация в VK | `avito_parser/vk_publisher.py` (wall.post, фото, тайминг) |
| 2.5 Конфиг из окружения | `avito_parser/config.py` (`.env`, 20+ параметров) |
