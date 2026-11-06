# Avito Parser + VK Publisher

Парсер объявлений Авито (Selenium) с автоматической публикацией в сообщество ВКонтакте.
Работает из CLI, через веб-админку или в Docker. Все параметры правятся в разделе
**Настройки** админки; `.env` — стартовые значения, править код для смены настроек не нужно.

## Что внутри

| Файл / пакет | Назначение |
|---|---|
| `main.py` | CLI: парсинг выдачи/карточек, сохранение в БД, постинг в VK |
| `publisher.py` | CLI: публикация из `avito.db` в VK (один пост, очередь, watch, тест) |
| `webui.py` | Веб-админка (stdlib `http.server`), фоновый крон (парсинг → постинг) |
| `webui_page.py` | HTML/CSS/JS интерфейса админки |
| `avito_parser/` | Пакет ядра |
| `avito_parser/config.py` | Конфиг из `.env` (парсер, браузер, VK, админка) |
| `avito_parser/settings.py` | Реестр настроек админки: типы, подписи, группы формы, наложение на `.env` |
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

Минимально необходимые значения в `.env`:

- **VK** — `VK_ACCESS_TOKEN` (ключ сообщества с правами `photos, wall, groups`) и `VK_GROUP_ID=public123456789`
- **Админка** — `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_SECRET` (длинный случайный hex)

Ссылки для парсинга в `.env` не задаются: после входа в админку добавьте их в разделе
**Источники** (таблица `sources`). Остальные параметры — задержки, прокси, шаблоны поста,
интервалы крона — при желании правятся там же в **.env** или прямо в разделе **Настройки**.

Оставшиеся после первого запуска изменения из админки хранятся в SQLite и перекрывают
`.env` — переменные окружения остаются запасным входом и стартовыми значениями.

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
python main.py                                       # из включённых источников БД
python main.py --urls-file urls.txt                  # список ссылок из файла
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
7. **Настройки** — все параметры парсера, браузера, прокси, VK и системы; перекрывают `.env`

### Постинг с фото

VK запрещает загрузку фото ключами сообщества (код ошибки 27). Для постов с картинками нужен **user-ключ standalone-приложения**.

1. В разделе **VK-канал** нажмите «Получить user-ключ (для фото)» — откроется OAuth-диалог VK
2. Разрешите права: `photos, wall, groups, offline`
3. Скопируйте `access_token=...` из адресной строки
4. Вставьте в поле «VK: ключ доступа» → «Сохранить»
5. Включите «Только посты с фото» → «Сохранить»

### Настройки

Раздел **Настройки** — форма, собранная из реестра `avito_parser/settings.py`: 50 параметров
в 9 группах (расписание, парсинг, браузер, прокси, блокировки, ВКонтакте, очередь публикации,
система, доступ). Приоритет значений:

```
сохранённое в таблице settings (SQLite)  →  переменная окружения (.env)  →  дефолт из кода
```

- Пустое поле параметр не перекрывает — значение остаётся из `.env`.
- Сохранённые в базе поля помечены в форме, подзаголовком считается «N из 50 сохранено в базе».
- «Сбросить настройки» очищает таблицу — все поля возвращаются к значениям из `.env`.
- Секреты (`vk_access_token`, `admin_password`) наружу не отдаются: вместо значения маска,
  пустое поле означает «не менять».
- Прокси для браузера — списком, по одному адресу на строку (`login:pass@ip:port`,
  `socks5://ip:port`): это пул, из которого `browser.py` берёт живой адрес.
- Параметры меняются на лету: крон перечитывает интервалы, VK-канал пересобирает ключ и шаблон,
  браузер пересоздаётся при смене прокси/headless/таймаута. Логин, пароль и файл базы
  применяются после перезапуска сервиса.

В окружении не задаются только параметры админки: `parse_interval_min`, `publish_interval_min`,
`cron_paused`, `first_run_limit`, `publish_batch` (дефолты — `database.py:DEFAULT_SETTINGS`).

## Архитектура

```
.env ─────────────→ Config.load() ──→ ParserConfig / VkConfig / BrowserConfig
settings (SQLite) ─→ settings.apply_db_settings() ─┘   (приоритет БД → .env → код)
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
.venv/bin/python tests/settings_test.py
.venv/bin/python tests/vk_flow_test.py
```

`tests/settings_test.py` — проверяет реестр настроек на временной базе: без строк в БД
параметры не трогают `.env`, сохранённые значения ложатся в `Config` (включая прокси-пул
списком), очищенное поле возвращается к окружению, форма отдаёт все 50 ключей, маска секрета
не содержит самого ключа, а разметка `SETTINGS_PAGE` рисует поле для каждой настройки.

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
