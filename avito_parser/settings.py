"""Реестр настроек: всё, что раньше жило только в .env, настраивается из админки.

Здесь описано всё настраиваемое: тип значения, подпись, группа формы и место в
`Config`, куда значение ложится поверх окружения.

Приоритет значений (см. AGENTS.md, п.1-2):
    таблица settings в БД  →  переменные окружения (.env)  →  дефолты кода

Пустое поле в админке означает «настройки этот параметр не касаются» — значение
берётся из окружения. Поэтому `.env` остаётся стартовым набором и страховкой при
первом запуске (в БД ещё нет ни одной строки), но менять параметры можно из UI.

Модуль не импортирует `database`, чтобы не создавать цикл: сюда передают либо
готовый словарь сырых значений, либо объект БД (duck-typing на `raw_settings`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import Config, split_urls, unescape

TRUE_WORDS = ("1", "true", "yes", "y", "on", "да")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


# --------------------------------------------------------------------- #
# реестр
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class SettingSpec:
    """Описание одной настройки: как хранить, как показывать, куда ложить."""

    key: str
    kind: str            # int | float | bool | text | secret | path | multiline | list
    label: str           # подпись поля
    group: str           # id раздела формы (см. GROUPS)
    hint: str = ""       # подсказка под полем
    section: str = ""    # browser | parser | vk | root | '' (пусто = параметр только для кода UI)
    attr: str = ""       # имя поля внутри секции Config
    env: str = ""        # переменная окружения, откуда берётся значение по умолчанию
    advanced: bool = False   # прятать до нажатия «Дополнительные параметры»
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    placeholder: str = ""
    choices: tuple[str, ...] = ()   # для text: допустимые значения (рисуются select'ом)


# id раздела -> (заголовок, описание для шапки строки формы)
GROUPS: list[tuple[str, str, str]] = [
    ("schedule", "Расписание",
     "Фоновый обход источников и постинг. Пауза останавливает крон, кнопки админки продолжают работать."),
    ("parse", "Парсинг",
     "Сколько карточек забирать с одной выдачи, что дочитывать и куда сохранять."),
    ("browser", "Браузер",
     "Параметры запуска Chrome и «очеловечивания» поведения: задержки, режим окна, User-Agent."),
    ("proxy", "Прокси",
     "Пул адресов для браузера: по одному прокси на строку. Пустое поле — работа напрямую."),
    ("block", "Блокировки",
     "Что делать, когда Авито показывает проверку безопасности: повторы и нарастающие паузы."),
    ("vk", "ВКонтакте",
     "Сообщество, ключ, шаблон поста и ограничения публикации."),
    ("publish", "Очередь публикации",
     "Сколько объявлений уходит за один запуск крона или кнопки «Постить очередь»."),
    ("system", "Система",
     "Пути к базе и логам, уровень подробности журналов."),
    ("access", "Доступ к админке",
     "Логин и пароль. Применяются после перезапуска сервиса; значения из .env остаются запасным входом."),
]

GROUP_TITLES: dict[str, str] = {gid: title for gid, title, _ in GROUPS}
GROUP_NOTES: dict[str, str] = {gid: note for gid, _, note in GROUPS}

SPECS: list[SettingSpec] = [
    # ---------------- расписание (только БД) ----------------
    SettingSpec("parse_interval_min", "int", "Парсинг, минут", "schedule",
                hint="как часто крон обходит включённые источники",
                minimum=1, maximum=1440),
    SettingSpec("publish_interval_min", "int", "Постинг, минут", "schedule",
                hint="как часто крон выгружает очередь в VK",
                minimum=1, maximum=1440),
    SettingSpec("cron_paused", "bool", "Поставить крон на паузу", "schedule",
                hint="останавливает фоновые задачи, но не кнопки админки"),

    # ---------------- парсинг ----------------
    SettingSpec("first_run_limit", "int", "Лимит объявлений за пуск", "parse",
                hint="для источника, который парсится впервые",
                minimum=1, maximum=500),
    SettingSpec("pages_per_source", "int", "Страниц выдачи на источник", "parse",
                section="parser", attr="pages", env="PAGES_COUNT",
                minimum=1, maximum=50),
    SettingSpec("details_on", "bool", "Открывать карточки", "parse",
                hint="полное описание и фотографии со страницы объявления",
                section="parser", attr="fetch_details", env="PARSE_DETAILS"),
    SettingSpec("photos_on", "bool", "Скачивать фото", "parse",
                hint="сохранять снимки в каталог ниже для вложений в пост",
                section="parser", attr="download_photos", env="DOWNLOAD_PHOTOS"),
    SettingSpec("max_photos_per_ad", "int", "Фото на объявление", "parse",
                section="parser", attr="max_photos", env="MAX_PHOTOS_PER_AD",
                minimum=1, maximum=20),
    SettingSpec("max_ads_per_run", "int", "Максимум объявлений за прогон", "parse",
                hint="0 — без лимита; суммарно по всем источникам",
                section="parser", attr="max_ads_per_run", env="MAX_ADS_PER_RUN",
                minimum=0, maximum=5000, advanced=True),
    SettingSpec("details_sample", "int", "Обрезать детали до N карточек", "parse",
                hint="0 — дочитывать все новые объявления",
                section="parser", attr="details_sample", env="DETAILS_SAMPLE",
                minimum=0, maximum=5000, advanced=True),

    # ---------------- браузер ----------------
    SettingSpec("headless", "bool", "Без окна (headless)", "browser",
                hint="в Docker и на сервере должно быть включено",
                section="browser", attr="headless", env="HEADLESS_MODE"),
    SettingSpec("rotate_user_agent", "bool", "Ротировать User-Agent", "browser",
                section="browser", attr="rotate_user_agent", env="ROTATE_USER_AGENT"),
    SettingSpec("delay_min", "float", "Задержка между действиями, от, сек", "browser",
                section="browser", attr="delay_min", env="DELAY_MIN",
                minimum=0, maximum=120, step=0.5),
    SettingSpec("delay_max", "float", "Задержка между действиями, до, сек", "browser",
                section="browser", attr="delay_max", env="DELAY_MAX",
                minimum=0, maximum=120, step=0.5),
    SettingSpec("browser_timeout", "int", "Таймаут загрузки страницы, сек", "browser",
                section="browser", attr="page_load_timeout", env="TIMEOUT",
                minimum=5, maximum=300, advanced=True),
    SettingSpec("render_timeout", "int", "Ждать отрисовку SPA, сек", "browser",
                hint="карточки Авито появляются после JS-рендера",
                section="browser", attr="render_timeout", env="RENDER_TIMEOUT",
                minimum=5, maximum=300, advanced=True),
    SettingSpec("inter_page_pause_min", "float", "Пауза между переходами, от, сек", "browser",
                section="parser", attr="inter_page_pause_min", env="INTER_PAGE_PAUSE_MIN",
                minimum=0, maximum=600, step=0.5, advanced=True),
    SettingSpec("inter_page_pause_max", "float", "Пауза между переходами, до, сек", "browser",
                section="parser", attr="inter_page_pause_max", env="INTER_PAGE_PAUSE_MAX",
                minimum=0, maximum=600, step=0.5, advanced=True),
    SettingSpec("chrome_profile_dir", "path", "Каталог профиля Chrome", "browser",
                hint="пусто — временный профиль, создаваемый на каждую сессию",
                section="browser", attr="profile_dir", env="CHROME_PROFILE_DIR",
                advanced=True, placeholder="data/profiles"),

    # ---------------- прокси ----------------
    SettingSpec("proxy_list", "list", "Прокси для браузера", "proxy",
                hint="по одному адресу на строку: login:pass@ip:port или socks5://ip:port",
                section="browser", attr="proxy_string", env="PROXY_STRING",
                placeholder="login:pass@185.10.20.30:8080\nsocks5://37.18.90.1:1080"),
    SettingSpec("proxy_allow_direct", "bool", "Разрешить прямой IP", "proxy",
                hint="если весь пул забанен — продолжать напрямую, а не останавливать прогон",
                section="browser", attr="allow_direct_fallback", env="PROXY_ALLOW_DIRECT"),
    SettingSpec("proxy_check_alive", "bool", "Проверять живость прокси", "proxy",
                hint="исключать недоступные адреса до запуска браузера",
                section="browser", attr="check_proxy_alive", env="PROXY_CHECK_ALIVE"),
    SettingSpec("proxy_ignore_tls", "bool", "Игнорировать ошибки TLS", "proxy",
                hint="нужно для резидентных прокси с перехватом сертификатов",
                section="browser", attr="ignore_insecure_tls", env="PROXY_IGNORE_TLS_ERRORS",
                advanced=True),
    SettingSpec("vk_proxy_list", "list", "Прокси для запросов VK", "proxy",
                hint="обычно пусто: VK не блокирует, а датацентровые адреса портят загрузку фото",
                section="vk", attr="proxy_string", env="VK_PROXY_STRING",
                advanced=True),

    # ---------------- блокировки ----------------
    SettingSpec("max_retries", "int", "Повторов страницы", "block",
                section="parser", attr="max_retries", env="MAX_RETRIES",
                minimum=0, maximum=10),
    SettingSpec("block_backoff_base", "float", "Пауза после блокировки, база, сек", "block",
                section="parser", attr="block_backoff_base", env="BLOCK_BACKOFF_BASE",
                minimum=1, maximum=3600, step=1),
    SettingSpec("block_backoff_max", "float", "Пауза после блокировки, потолок, сек", "block",
                section="parser", attr="block_backoff_max", env="BLOCK_BACKOFF_MAX",
                minimum=1, maximum=3600, step=1),
    SettingSpec("challenge_wait", "int", "Ждать JS-челлендж, сек", "block",
                hint="«Доступ ограничен: проверка безопасности» обычно отпускает за секунды",
                section="browser", attr="challenge_wait", env="CHALLENGE_WAIT",
                minimum=0, maximum=600),

    # ---------------- ВКонтакте ----------------
    SettingSpec("vk_access_token", "secret", "VK access token", "vk",
                hint="пустое поле не меняет сохранённый ключ",
                section="vk", attr="access_token", env="VK_ACCESS_TOKEN",
                advanced=True, placeholder="вставьте новый ключ"),
    SettingSpec("vk_group_id", "text", "Сообщество (id или screen_name)", "vk",
                section="vk", attr="group_id", env="VK_GROUP_ID",
                placeholder="vk.com/club12345678"),
    SettingSpec("vk_app_id", "text", "ID standalone-приложения", "vk",
                hint="нужен для ссылки OAuth, по которой получают ключ пользователя с правом photos",
                section="vk", attr="app_id", env="VK_APP_ID", advanced=True,
                placeholder="1234567"),
    SettingSpec("vk_post_template", "multiline", "Шаблон текста поста", "vk",
                hint="доступны {title} {price} {description} {url} {location} {id} {date}",
                section="vk", attr="template", env="VK_POST_TEMPLATE"),
    SettingSpec("vk_hashtags", "text", "Хэштеги в конец поста", "vk",
                placeholder="#авито #саранск",
                section="vk", attr="hashtags", env="VK_HASHTAGS"),
    SettingSpec("vk_min_interval_sec", "int", "Минимальная пауза между постами, сек", "vk",
                hint="защита от лимита 902; 0 — выключить",
                section="vk", attr="min_interval_sec", env="VK_POST_MIN_INTERVAL_SEC",
                minimum=0, maximum=3600),
    SettingSpec("vk_max_photos_per_post", "int", "Максимум фото в посте", "vk",
                section="vk", attr="max_photos_per_post", env="VK_MAX_PHOTOS_PER_POST",
                minimum=0, maximum=10),
    SettingSpec("vk_require_photos", "bool", "Постить только с фото", "vk",
                hint="объявление без снимков остаётся в очереди",
                section="vk", attr="require_photos", env="VK_REQUIRE_PHOTOS"),
    SettingSpec("vk_download_photos", "bool", "Докачивать недостающие фото", "vk",
                hint="если парсер не скачал снимки — скачать их перед публикацией",
                section="vk", attr="download_missing_photos", env="VK_DOWNLOAD_PHOTOS"),
    SettingSpec("vk_disable_comments", "bool", "Закрывать комментарии", "vk",
                section="vk", attr="disable_comments", env="VK_DISABLE_COMMENTS",
                advanced=True),
    SettingSpec("vk_max_description", "int", "Длина описания в посте, знаков", "vk",
                hint="0 — не обрезать",
                section="vk", attr="max_description", env="VK_MAX_DESCRIPTION_LENGTH",
                minimum=0, maximum=8000, advanced=True),
    SettingSpec("vk_max_message", "int", "Длина поста, знаков", "vk",
                hint="лимит стены VK — 8000",
                section="vk", attr="max_message_length", env="VK_MAX_MESSAGE_LENGTH",
                minimum=0, maximum=8000, advanced=True),
    SettingSpec("vk_api_version", "text", "Версия API VK", "vk",
                section="vk", attr="api_version", env="VK_API_VERSION", advanced=True),
    SettingSpec("vk_request_timeout", "int", "Таймаут запросов к API, сек", "vk",
                section="vk", attr="request_timeout", env="VK_REQUEST_TIMEOUT",
                minimum=5, maximum=300, advanced=True),
    SettingSpec("vk_upload_timeout", "int", "Таймаут загрузки фото, сек", "vk",
                section="vk", attr="upload_timeout", env="VK_UPLOAD_TIMEOUT",
                minimum=10, maximum=900, advanced=True),

    # ---------------- очередь публикации ----------------
    SettingSpec("publish_batch", "int", "Объявлений за запуск", "publish",
                hint="за один цикл крона или кнопку «Постить очередь»",
                minimum=1, maximum=100),

    # ---------------- система ----------------
    SettingSpec("photos_dir", "path", "Каталог фотографий", "system",
                section="parser", attr="photos_dir", env="PHOTOS_DIR",
                placeholder="data/photos"),
    SettingSpec("log_level", "text", "Уровень логов", "system",
                section="parser", attr="log_level", env="LOG_LEVEL",
                choices=LOG_LEVELS, advanced=True),
    SettingSpec("log_file", "path", "Файл лога", "system",
                section="parser", attr="log_file", env="LOG_FILE",
                placeholder="logs/avito_parser.log", advanced=True),
    SettingSpec("db_path", "path", "Файл базы SQLite", "system",
                hint="применяется при следующем перезапуске: база уже открыта",
                section="parser", attr="db_path", env="DB_PATH",
                placeholder="data/avito.db", advanced=True),

    # ---------------- доступ ----------------
    SettingSpec("admin_username", "text", "Логин администратора", "access",
                hint="после изменения — перезапустить сервис",
                section="root", attr="admin_username", env="ADMIN_USERNAME", advanced=True),
    SettingSpec("admin_password", "secret", "Пароль администратора", "access",
                hint="пустое поле не меняет сохранённый пароль; применяется после перезапуска",
                section="root", attr="admin_password", env="ADMIN_PASSWORD",
                advanced=True, placeholder="новый пароль"),
]

SPECS_BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SPECS}

# ключи, которые принимает POST /api/settings
SETTING_KEYS: frozenset[str] = frozenset(SPECS_BY_KEY)

# секреты: наружу (в HTML и логи) отдаём только маску
SECRET_KEYS: frozenset[str] = frozenset(
    spec.key for spec in SPECS if spec.kind == "secret")

# настройки, меняющие поведение уже запущенного браузера
BROWSER_KEYS: frozenset[str] = frozenset(
    spec.key for spec in SPECS if spec.section == "browser")


# --------------------------------------------------------------------- #
# разбор значений
# --------------------------------------------------------------------- #
def truthy(raw: str) -> bool:
    return str(raw).strip().lower() in TRUE_WORDS


def _target(config: Config, spec: SettingSpec) -> Any:
    """Объект, в который кладём значение: секция Config или сам Config."""
    if spec.section == "root":
        return config
    return getattr(config, spec.section)


def coerce(spec: SettingSpec, raw: str) -> Any:
    """Строка из БД/окружения → типизированное значение. None = значение не задано."""
    if raw is None:
        return None
    value = str(raw).strip()
    if spec.kind in ("multiline", "list"):
        value = str(raw).strip("\r")          # многострочные не теряем leading пробелы

    if not value:
        return None                       # пусто = параметр не перекрываем (остаётся .env)

    if spec.kind == "bool":
        return truthy(value)
    if spec.kind == "int":
        try:
            number = int(float(value))
        except ValueError:
            return None
        return _clamp(spec, number)
    if spec.kind == "float":
        try:
            number = float(value)
        except ValueError:
            return None
        return _clamp(spec, number)
    if spec.kind == "path":
        return Path(value)
    if spec.kind == "list":
        # список адресов: по одному на строку/через запятую — храним одной строкой пула
        return ", ".join(split_urls(value.replace("\r", "\n")))
    if spec.kind == "multiline":
        return unescape(value)
    if spec.choices:
        # выпадающий список: принимаем только свои значения (регистр не важен)
        for choice in spec.choices:
            if value.upper() == choice.upper():
                return choice
        return None
    return value


def _clamp(spec: SettingSpec, number: float) -> float:
    if spec.minimum is not None:
        number = max(spec.minimum, number)
    if spec.maximum is not None:
        number = min(spec.maximum, number)
    return int(number) if spec.kind == "int" else number


def raw_values(source: Any) -> dict[str, str]:
    """Сырые строки настроек из БД (без дефолтов): пусто — значит «не трогать .env»."""
    if source is None:
        return {}
    if isinstance(source, dict):
        return {str(k): ("" if v is None else str(v)) for k, v in source.items()}
    getter = getattr(source, "raw_settings", None)
    if callable(getter):
        return getter()
    all_getter = getattr(source, "all_settings", None)
    return all_getter() if callable(all_getter) else {}


# --------------------------------------------------------------------- #
# наложение на Config
# --------------------------------------------------------------------- #
def apply_db_settings(config: Config, source: Any = None) -> Config:
    """Положить значения из таблицы settings поверх Config (который собран из .env).

    Функция идемпотентна: перед наложением каждый параметр возвращается к значению
    окружения, поэтому очищенное в админке поле действительно возвращается к .env,
    а не сохраняет прежнюю запись из базы.

    Возвращает тот же объект config — секции мутируются на месте, поэтому держатели
    ссылок (VKPublisher, AvitoScraper) видят новые значения.
    """
    values = raw_values(source)
    pristine = Config()        # снимок «как из окружения»: дефолты dataclass считаются на импорте

    for spec in SPECS:
        if not spec.section or not spec.attr:
            continue                      # расписание, пачки и лимиты первого прогона живут только в БД
        parsed = coerce(spec, values.get(spec.key, "")) if values else None
        holder = _target(config, spec)
        setattr(holder, spec.attr, parsed if parsed is not None
                else getattr(_target(pristine, spec), spec.attr))
    return config


def overridden_keys(source: Any) -> set[str]:
    """Ключи, реально сохранённые в базе (нужны, чтобы пометить поля в форме)."""
    values = raw_values(source)
    return {key for key, value in values.items() if str(value).strip() and key in SPECS_BY_KEY}


def form_value(spec: SettingSpec, value: Any) -> str:
    """Значение из Config → строка для поля формы."""
    if value is None:
        return ""
    if spec.kind == "bool":
        return "1" if value else "0"
    if spec.kind == "list":
        return "\n".join(split_urls(str(value).replace("\r", "\n")))
    if spec.kind == "int":
        return str(int(value))
    if spec.kind == "float":
        return ("%g" % float(value))
    return str(value)


def current_value(config: Config, spec: SettingSpec) -> Any:
    """Значение параметра из Config (т.е. то, что дал .env или дефолт кода)."""
    if not spec.section:
        return None
    return getattr(_target(config, spec), spec.attr, None)


def effective_settings(config: Config, source: Any = None) -> dict[str, str]:
    """Все настройки для формы: строка из БД, иначе значение из окружения, иначе дефолт.

    Секреты наружу не отдаются никогда — ни сохранённые в базе, ни взятые из `.env`:
    вместо них пустая строка, а маску считает вызывающий код.
    """
    values = raw_values(source)
    defaults = dict(getattr(source, "DEFAULT_SETTINGS", {}) or {})
    result: dict[str, str] = {}
    for spec in SPECS:
        stored = values.get(spec.key)
        if stored is not None and str(stored).strip():
            if spec.kind == "secret":
                result[spec.key] = ""       # содержимое не показываем, поле остаётся «не менять»
            elif spec.kind == "list":
                result[spec.key] = "\n".join(split_urls(str(stored).replace("\r", "\n")))
            elif spec.kind == "multiline":
                result[spec.key] = str(stored).replace("\r\n", "\n")
            else:
                result[spec.key] = str(stored).strip()
            continue
        if spec.kind == "secret":
            result[spec.key] = ""
        elif spec.section:
            result[spec.key] = form_value(spec, current_value(config, spec))
        else:
            # параметр живёт только в базе (интервалы крона, пачки, лимиты)
            result[spec.key] = str(defaults.get(spec.key, ""))
    return result


def describe_spec(key: str) -> dict[str, Any]:
    """Спецификация ключа для UI (подписи, подсказки, границы полей)."""
    spec = SPECS_BY_KEY.get(key)
    if not spec:
        return {}
    return {
        "key": spec.key, "kind": spec.kind, "label": spec.label, "hint": spec.hint,
        "group": spec.group, "env": spec.env, "advanced": spec.advanced,
        "min": spec.minimum, "max": spec.maximum, "step": spec.step,
        "placeholder": spec.placeholder, "choices": list(spec.choices),
    }


def browser_signature(config: Config) -> tuple:
    """Подпись параметров, при которых браузер нужно пересоздать."""
    browser = config.browser
    return (
        browser.proxy_string,
        browser.headless,
        browser.rotate_user_agent,
        browser.ignore_insecure_tls,
        browser.check_proxy_alive,
        str(browser.profile_dir or ""),
        browser.page_load_timeout,
    )


def sanitize_for_storage(spec: SettingSpec, raw: Any) -> str:
    """Нормализация значения перед записью в таблицу settings (границы — из реестра)."""
    text = "" if raw is None else str(raw)
    if spec.kind == "bool":
        return "1" if truthy(text) else "0"
    if spec.kind == "list":
        return "\n".join(split_urls(text.replace("\r", "\n")))
    if spec.kind == "multiline":
        return text.replace("\r\n", "\n")
    text = text.strip()
    if spec.choices:
        # значение из выпадающего списка нормализуем к каноническому виду (debug → DEBUG)
        for choice in spec.choices:
            if text.upper() == choice.upper():
                return choice
        return text
    if spec.kind in ("int", "float") and text:
        try:
            number = float(text)
        except ValueError:
            return text                     # разберёт coerce: нечисло не пишем как значение
        return repr(_clamp(spec, number)) if spec.kind == "float" else str(int(_clamp(spec, number)))
    return text


def spec_for(key: str) -> SettingSpec | None:
    return SPECS_BY_KEY.get(key)


def keys_of_groups(groups: Iterable[str]) -> list[str]:
    """Ключи настроек, принадлежащих указанным разделам формы."""
    wanted = set(groups)
    return [spec.key for spec in SPECS if spec.group in wanted]
