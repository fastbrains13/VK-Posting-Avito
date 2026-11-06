"""Конфигурация парсера.

Классы ниже собирают первоначальные значения из переменных окружения (файл
.env). Настраиваемые параметры админки лежат поверх них: см. `settings.py` —
приоритет БД → окружение → дефолты кода. Отслеживаемые ссылки в окружении больше
не задаются: они живут в таблице `sources` и добавляются в разделе «Источники».
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:  # python-dotenv опционален: без него работаем только с переменными окружения
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover
    pass


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env_str(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env_str(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on", "да")


def unescape(value: str) -> str:
    """Развернуть escape-последовательности в настоящие символы.

    Нужно и для значений из .env (dotenv отдаёт их как есть), и для шаблонов
    поста, сохранённых в настройках админки. chr() вместо слешей в исходнике —
    чтобы сам файл не зависел от правил экранирования.
    """
    if not value:
        return value
    backslash = chr(92)
    for letter, code in (("n", 10), ("r", 13), ("t", 9)):
        value = value.replace(backslash + letter, chr(code))
    return value


_unescape = unescape  # совместимость с прежними импортами внутри пакета


def _opt_path(name: str, default: str = "") -> Path | None:
    """Путь из окружения: пустая строка означает «не задан» (Path('') == '.')."""
    raw = _env_str(name, default)
    return Path(raw) if raw else None


def split_urls(raw: str) -> list[str]:
    """Разбить строку со ссылками по запятой/точке с запятой/переводам строки."""
    if not raw:
        return []
    parts = re.split(r"[,;\n\r]+", raw)
    out: list[str] = []
    for part in parts:
        value = part.strip()
        if value and value not in out:
            out.append(value)
    return out


def read_urls_file(path: Path | None) -> list[str]:
    """Ссылки из файла: по одной на строку, строки с # игнорируются."""
    if not path or not Path(path).is_file():
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


@dataclass
class BrowserConfig:
    """Параметры запуска и «очеловечивания» браузера."""

    headless: bool = _env_bool("HEADLESS_MODE", True)
    page_load_timeout: int = _env_int("TIMEOUT", 30)
    # сколько ждать отрисовки SPA-контента (карточки Авито появляются после JS-рендера)
    render_timeout: int = _env_int("RENDER_TIMEOUT", 45)
    # «Доступ ограничен: проверка безопасности» — JS-челлендж, обычно отпускает за секунды;
    # до этой величины ждём, а не перезапускаем браузер (перезапуск только злит защиту)
    challenge_wait: int = _env_int("CHALLENGE_WAIT", 40)
    # Случайные задержки между действиями, сек (ТЗ: 2-5 секунд)
    delay_min: float = _env_float("DELAY_MIN", 2.0)
    delay_max: float = _env_float("DELAY_MAX", 5.0)
    # Прокси в формате login:pass@ip:port (опционально)
    proxy_string: str = _env_str("PROXY_STRING", "")
    # резидентные/бесплатные SOCKS-прокси часто перехватывают TLS: игнорировать ошибки сертификатов
    ignore_insecure_tls: bool = _env_bool("PROXY_IGNORE_TLS_ERRORS", True)
    check_proxy_alive: bool = _env_bool("PROXY_CHECK_ALIVE", True)
    rotate_user_agent: bool = _env_bool("ROTATE_USER_AGENT", True)
    # все прокси забиты/не работают — продолжить напрямую, а не встать
    allow_direct_fallback: bool = _env_bool("PROXY_ALLOW_DIRECT", True)
    window_sizes: tuple = ((1366, 768), (1440, 900), (1280, 800), (1536, 864), (1680, 1050))
    # пусто -> временный профиль в системе, а не в рабочей директории
    profile_dir: Path | None = _opt_path("CHROME_PROFILE_DIR")


@dataclass
class ParserConfig:
    """Параметры самого парсера."""

    # Отслеживаемые ссылки в окружении не задаются: список источников ведётся
    # в таблице `sources` (раздел «Источники» админки или аргументы CLI).
    # Поле остаётся рабочим: UI/CLI кладут в него ссылки конкретного прогона.
    target_url: str = ""
    sources_file: Path | None = None
    pages: int = _env_int("PAGES_COUNT", 1)
    fetch_details: bool = _env_bool("PARSE_DETAILS", True)
    max_ads_per_run: int = _env_int("MAX_ADS_PER_RUN", 0)  # 0 = без лимита
    details_sample: int = _env_int("DETAILS_SAMPLE", 0)  # 0 = все новые

    # Фотографии
    download_photos: bool = _env_bool("DOWNLOAD_PHOTOS", True)
    max_photos: int = _env_int("MAX_PHOTOS_PER_AD", 5)  # ТЗ: от 1 до 5
    photos_dir: Path = Path(_env_str("PHOTOS_DIR", "data/photos"))

    # Хранилище
    db_path: Path = Path(_env_str("DB_PATH", "avito.db"))

    # Поведение при блокировке
    max_retries: int = _env_int("MAX_RETRIES", 2)
    block_backoff_base: float = _env_float("BLOCK_BACKOFF_BASE", 60.0)
    # потолок единичной паузы: в фоне лучше пропустить цикл и вернуться позже,
    # чем зависнуть на десятки минут внутри одной страницы
    block_backoff_max: float = _env_float("BLOCK_BACKOFF_MAX", 180.0)
    # Адаптивная пауза между переходами по страницам объявлений, сек
    inter_page_pause_min: float = _env_float("INTER_PAGE_PAUSE_MIN", 6.0)
    inter_page_pause_max: float = _env_float("INTER_PAGE_PAUSE_MAX", 14.0)

    log_level: str = _env_str("LOG_LEVEL", "INFO")
    log_file: Path = Path(_env_str("LOG_FILE", "logs/avito_parser.log"))

    # ------------------------------------------------------------------ #
    # список отслеживаемых ссылок
    # ------------------------------------------------------------------ #
    def sources(self) -> list[str]:
        """Все рабочие ссылки: из переменной окружения и из файла, без дублей."""
        urls: list[str] = []
        for candidate in split_urls(self.target_url) + read_urls_file(self.sources_file):
            if candidate.lower().startswith(("http://", "https://")) and candidate not in urls:
                urls.append(candidate)
            elif candidate and not candidate.lower().startswith("http"):
                # «avito.ru/...» без схемы — дополняем https
                fixed = "https://" + candidate.lstrip("/")
                if fixed not in urls:
                    urls.append(fixed)
        return urls

    def set_sources(self, urls: list[str]) -> None:
        """Задать список ссылок из кода (CLI/UI перекрывают .env)."""
        merged = split_urls(",".join(str(u) for u in urls if u))
        self.target_url = ", ".join(merged)


@dataclass
class VkConfig:
    """Публикация объявлений в сообщество ВКонтакте (ТЗ, п.3.3)."""

    access_token: str = _env_str("VK_ACCESS_TOKEN")
    # id standalone-приложения: из него строится ссылка на получение user-ключа
    # (user-ключ нужен для загрузки фото — ключи сообщества этого не умеют)
    app_id: str = _env_str("VK_APP_ID")
    # id сообщества (число, можно со знаком минус) или его короткий адрес — screen_name
    group_id: str = _env_str("VK_GROUP_ID")
    api_version: str = _env_str("VK_API_VERSION", "5.199")
    api_base: str = _env_str("VK_API_BASE", "https://api.vk.com/method")
    # ТЗ: постить не чаще одного объявления в 3-5 минут
    min_interval_sec: float = _env_float("VK_POST_MIN_INTERVAL_SEC", 240.0)
    # шаблон текста поста; \n в .env понимается как перенос строки
    template: str = unescape(_env_str(
        "VK_POST_TEMPLATE",
        "{title}\nЦена: {price}\n\n{description}\n\nСсылка: {url}",
    ))
    max_photos_per_post: int = _env_int("VK_MAX_PHOTOS_PER_POST", 10)
    # описание с Авито бывает до 8000 знаков — в пост берём только начало
    max_description: int = _env_int("VK_MAX_DESCRIPTION_LENGTH", 1200)
    max_message_length: int = _env_int("VK_MAX_MESSAGE_LENGTH", 7500)
    # не постить без фотографий (обычно так: посты без картинки тонут в ленте)
    require_photos: bool = _env_bool("VK_REQUIRE_PHOTOS", True)
    # если фото не скачаны парсером — докачать их перед публикацией
    download_missing_photos: bool = _env_bool("VK_DOWNLOAD_PHOTOS", True)
    disable_comments: bool = _env_bool("VK_DISABLE_COMMENTS", False)
    # хэштеги в конец поста, например "#авито #саранск"
    hashtags: str = _env_str("VK_HASHTAGS", "")
    request_timeout: int = _env_int("VK_REQUEST_TIMEOUT", 30)
    upload_timeout: int = _env_int("VK_UPLOAD_TIMEOUT", 120)
    # отдельный прокси для VK (по умолчанию не используется: VK не блокирует,
    # а датацентровые адреса от Авито только портят запросы)
    proxy_string: str = _env_str("VK_PROXY_STRING", "")

    @property
    def configured(self) -> bool:
        return bool(self.access_token and self.group_id)

    def group_number(self) -> int | None:
        """Числовой id сообщества из строки '-123' / '123' / 'myclub' (число пока неизвестно)."""
        raw = (self.group_id or "").strip().lstrip("@").lstrip("-")
        return int(raw) if raw.isdigit() else None


@dataclass
class Config:
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    parser: ParserConfig = field(default_factory=ParserConfig)
    vk: VkConfig = field(default_factory=VkConfig)
    # доступ к веб-админке (пароль печатается в лог при старте, если не задан)
    admin_username: str = _env_str("ADMIN_USERNAME", "admin")
    admin_password: str = _env_str("ADMIN_PASSWORD", "")
    admin_secret: str = _env_str("ADMIN_SECRET", "")

    @classmethod
    def load(cls) -> "Config":
        return cls()


# Общий экземпляр конфигурации по умолчанию
CONFIG = Config.load()
