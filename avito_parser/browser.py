"""Управление браузером Selenium (Chrome/Chromium).

Реализует требования ТЗ по обходу защиты:
  * скрытие признаков автоматизации (navigator.webdriver, флаги Chrome);
  * ротация User-Agent между сессиями;
  * поддержка прокси (в т.ч. с авторизацией login:pass@host:port);
  * headless-режим для работы в контейнере.
"""

from __future__ import annotations

import random
import re
import socket
import string
import tempfile
from dataclasses import dataclass
from pathlib import Path

import os

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException

from .config import BrowserConfig
from .logger import get_logger

logger = get_logger("avito.browser")

# Пул «свежих» UA: подменяется только minor/patch-версия, major остаётся реальным
# для браузера, иначе UA начнёт конфликтовать с navigator.userAgentData
_UA_TEMPLATE = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/{major}.0.{build}.{patch} Safari/537.36"
)

# Скрипт, убирающий самые заметные следы Selenium
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || { runtime: {}, loadTimes: function(){}, csi: function(){} };
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);
"""


@dataclass
class ProxySettings:
    """Разобранная строка прокси: [scheme://][login:password@]host:port."""

    host: str
    port: int
    login: str | None = None
    password: str | None = None
    scheme: str = "http"  # http | socks5

    @property
    def is_socks(self) -> bool:
        return self.scheme.startswith("socks")

    @property
    def chrome_url(self) -> str:
        # Chrome поддерживает только socks5:// (socks4/socks5h — ошибка ERR_NO_SUPPORTED_PROXIES),
        # а DNS при socks5 резолвится локально
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def requests_url(self) -> str:
        # для requests/PySocks резолвинг имени отдаём прокси: с MITM-цепочкой это надёжнее
        scheme = "socks5h" if self.is_socks else self.scheme
        auth = f"{self.login}:{self.password}@" if self.login else ""
        return f"{scheme}://{auth}{self.host}:{self.port}"

    def __str__(self) -> str:
        auth = f"{self.login}:***@" if self.login else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @classmethod
    def parse(cls, raw: str) -> "ProxySettings | None":
        if not raw:
            return None
        value = raw.strip()
        scheme = "http"
        if "://" in value:
            scheme, _, value = value.partition("://")
            scheme = scheme.lower()
            if scheme in ("socks5h", "socks4", "socks4a"):
                scheme = "socks5"  # Chrome умеет только socks5

        creds, _, hostport = value.rpartition("@")
        if not hostport:  # строка вида host:port без учётных данных
            host, _, port = value.partition(":")
            return cls(host=host, port=int(port or 80), scheme=scheme)
        host, _, port = hostport.partition(":")
        login, _, password = creds.partition(":")
        return cls(host=host, port=int(port or 80), login=login or None, password=password or None,
                   scheme=scheme)

    @classmethod
    def parse_pool(cls, raw: str) -> list["ProxySettings"]:
        """Пул прокси: PROXY_STRING может быть списком через запятую, точку с запятой или перевод строки."""
        if not raw:
            return []
        proxies: list[ProxySettings] = []
        for chunk in re.split(r"[;,\s]+", raw):
            proxy = cls.parse(chunk.strip())
            if proxy and proxy.host:
                proxies.append(proxy)
        return proxies

    def is_alive(self, timeout: float = 6.0) -> bool:
        """Жив ли прокси по-настоящему.

        Открытого порта мало: у «мёртвых» SOCKS из публичных списков TCP accept есть,
        а хендшейк обрывается. Для SOCKS5 проверяем greeting, для HTTP — CONNECT.
        """
        try:
            with socket.create_connection((self.host, self.port), timeout=timeout) as sock:
                sock.settimeout(timeout)
                if self.is_socks:
                    # SOCKS5 greeting: версия 5, один метод — «без авторизации»
                    sock.sendall(b"\x05\x01\x00")
                    reply = sock.recv(2)
                    if len(reply) != 2 or reply[0] != 0x05:
                        return False
                    if reply[1] == 0xFF:  # ни один метод не принят
                        return False
                    if self.login and reply[1] != 0x02:
                        logger.warning("Прокси %s не требует username/password, учётные данные не будут использованы", self)
                    return True
                # HTTP-прокси: проверяем, что он отвечает на запрос (не закрывает соединение)
                sock.sendall(b"OPTIONS * HTTP/1.0\r\n\r\n")
                return bool(sock.recv(16))
        except OSError:
            return False


def build_user_agent(major: int) -> str:
    """Сгенерировать правдоподобный UA с указанным major-версией Chrome."""
    return _UA_TEMPLATE.format(
        major=major,
        build=random.randint(6000, 7200),
        patch=random.choice([10, 32, 54, 81, 99, 120, 175]),
    )


def _detect_chrome_major() -> int:
    """Определить реальную major-версию Chrome (нужна для консистентного UA)."""
    import shutil
    import subprocess

    candidates = []
    for binary in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(binary)
        if path:
            candidates.append(path)
    candidates.append("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    candidates.append("/Applications/Chromium.app/Contents/MacOS/Chromium")

    for path in candidates:
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=8).stdout
            tail = out.strip().split()[-1]
            return int(tail.split(".")[0])
        except (ValueError, IndexError, OSError, subprocess.SubprocessError):
            continue
    return 0


class BrowserSession:
    """Обёртка над WebDriver: создание, перезапуск, корректное закрытие."""

    def __init__(self, config: BrowserConfig | None = None):
        self.config = config or BrowserConfig()
        self.driver: webdriver.Chrome | None = None
        self.user_agent: str = ""
        # пул прокси: при каждом рестарте берём следующий живой адрес (ротация)
        pool = ProxySettings.parse_pool(self.config.proxy_string)
        self.proxies: list[ProxySettings] = (
            self._filter_alive(pool) if self.config.check_proxy_alive else pool
        )
        self._proxy_index = -1
        self.proxy: ProxySettings | None = self.proxies[0] if self.proxies else None
        # адреса, которые Авито завернул по IP: они не «мертвы» для TCP, но бесполезны для
        # парсинга, поэтому карантин отдельный — иначе ротация зацикливается на одном бане
        self._quarantined: set[str] = set()
        self._profile_dir: Path | None = None
        self.chrome_major: int = 0

    @staticmethod
    def _proxy_key(proxy: ProxySettings) -> str:
        return f"{proxy.host}:{proxy.port}"

    def healthy_proxies(self) -> list[ProxySettings]:
        """Прокси, которые ещё не отправлены в карантин."""
        return [p for p in self.proxies if self._proxy_key(p) not in self._quarantined]

    def mark_proxy_bad(self, reason: str = "") -> str:
        """Исключить текущий прокси из пула.

        Возвращает режим дальнейшей работы: 'proxy' (есть чем заменить),
        'direct' (пул пуст, идём напрямую) или 'none' (менять не на что).
        """
        target = self.proxy
        if target is None:
            return "none"
        self._quarantined.add(self._proxy_key(target))
        logger.warning("Прокси %s непригоден (%s) — отправляю в карантин", target, reason)
        if self.healthy_proxies():
            return "proxy"
        if self.config.allow_direct_fallback:
            logger.warning("Живых прокси не осталось — продолжаю напрямую (PROXY_ALLOW_DIRECT)")
            self.proxy = None
            return "direct"
        logger.error("Все прокси в карантине, прямой доступ запрещён (PROXY_ALLOW_DIRECT=false)")
        return "none"

    @staticmethod
    def _filter_alive(proxies: list[ProxySettings]) -> list[ProxySettings]:
        """Отсеять недоступные прокси, чтобы висящий адрес не съедал цикл парсинга."""
        if not proxies:
            return []
        alive = [proxy for proxy in proxies if proxy.is_alive()]
        for dead in [p for p in proxies if p not in alive]:
            logger.warning("Прокси %s недоступен — исключаю из пула", dead)
        if not alive:
            logger.warning("Ни один прокси из пула не отвечает — работаю напрямую")
        return alive

    def _next_proxy(self) -> ProxySettings | None:
        healthy = self.healthy_proxies()
        if not healthy:
            return None
        self._proxy_index = (self._proxy_index + 1) % len(healthy)
        return healthy[self._proxy_index]

    # ------------------------------------------------------------------ #
    # creation / restart
    # ------------------------------------------------------------------ #
    def _make_options(self) -> Options:
        options = Options()
        width, height = random.choice(self.config.window_sizes)

        if self.config.headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--window-size={width},{height}")
        options.add_argument("--lang=ru-RU,ru")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--mute-audio")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        # performance-лог нужен, чтобы вытаскивать байты картинок, загруженных самим
        # браузером: через SOCKS-прокси с перехватом TLS прямой запрос к CDN не проходит
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        # eager: не ждать загрузки всех изображений — тяжёлые страницы Авито иначе уходят в таймаут
        options.set_capability("pageLoadStrategy", "eager")

        if self.user_agent:
            options.add_argument(f"--user-agent={self.user_agent}")

        if self.proxy:
            options.add_argument(f"--proxy-server={self.proxy.chrome_url}")
            if self.proxy.is_socks and self.proxy.login:
                # Chrome не передаёт учётные данные для SOCKS5 — только для HTTP-прокси
                logger.warning("SOCKS5 с авторизацией не поддерживается Chrome, логин будет проигнорирован")
            if self.config.ignore_insecure_tls:
                # резидентные/бесплатные SOCKS-прокси часто перехватывают TLS и отдают
                # самоподписанный сертификат — без этого флага страница не откроется вовсе
                options.add_argument("--ignore-certificate-errors")
                options.add_argument("--allow-insecure-localhost")
                options.set_capability("acceptInsecureCerts", True)

        # отдельный user-data-dir: куки и «прогресс» размонтируются между сессиями
        if self.config.profile_dir:
            self._profile_dir = self.config.profile_dir / f"profile-{''.join(random.choices(string.ascii_lowercase, k=8))}"
        else:
            self._profile_dir = Path(tempfile.mkdtemp(prefix="avito_profile_"))
        options.add_argument(f"--user-data-dir={self._profile_dir}")

        return options

    def _driver_kwargs(self, options: Options) -> dict:
        """Собрать аргументы webdriver.Chrome с учётом бинарников из окружения.

        В контейнере Chromium лежит по /usr/bin/chromium, а драйвер — по
        /usr/bin/chromedriver; Selenium Manager их не найдёт сам, поэтому
        пути передаются через CHROME_BIN и CHROMEDRIVER_PATH.
        """
        kwargs: dict = {}
        binary = os.environ.get("CHROME_BIN")
        if binary and Path(binary).exists():
            options.binary_location = binary
        driver_path = os.environ.get("CHROMEDRIVER_PATH")
        if driver_path and Path(driver_path).exists():
            kwargs["service"] = Service(executable_path=driver_path)
        return kwargs

    def start(self) -> webdriver.Chrome:
        """Запустить браузер. При ротации UA используется реальная major-версия Chrome."""
        # новый прокси на каждую сессию — рестарт после блокировки уходит в другой адрес
        if self.proxies:
            self.proxy = self._next_proxy()
            if self.proxy is None:
                # все адреса в карантине: молча «честить» реальный IP нельзя,
                # это ровно то, чего прокси-пул и avoids
                if not self.config.allow_direct_fallback:
                    raise RuntimeError(
                        "Все прокси заблокированы Авито, прямые запросы запрещены (PROXY_ALLOW_DIRECT=false)"
                    )
                logger.warning("Живых прокси не осталось — браузер работает напрямую")
            else:
                logger.info("Прокси %d/%d: %s", self._proxy_index + 1,
                            len(self.healthy_proxies()), self.proxy.chrome_url)

        if self.config.rotate_user_agent:
            if not self.chrome_major:
                self.chrome_major = _detect_chrome_major() or (self._probe_major() or 131)
            self.user_agent = build_user_agent(self.chrome_major)

        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                options = self._make_options()
                driver_kwargs = self._driver_kwargs(options)
                self.driver = webdriver.Chrome(options=options, **driver_kwargs)
                break
            except WebDriverException as exc:  # chromedriver не успел подняться
                last_error = exc
                logger.warning("Попытка %d запуска браузера не удалась: %s", attempt, str(exc).splitlines()[0])
                self.driver = None
        else:
            raise RuntimeError(f"Не удалось запустить Chrome: {last_error}")

        self.driver.set_page_load_timeout(self.config.page_load_timeout)
        self.driver.implicitly_wait(0)

        # прячем webdriver до загрузки любого документа
        try:
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": _STEALTH_JS})
        except WebDriverException:
            logger.debug("CDP недоступен, stealth-скрипт не применён")

        if self.proxy and self.proxy.login:
            self._apply_proxy_auth()

        logger.info("Браузер запущен (headless=%s, UA=Chrome/%s, прокси в пуле=%d)",
                    self.config.headless, self.chrome_major, len(self.healthy_proxies()))
        return self.driver

    def _probe_major(self) -> int:
        """Спросить версию Chrome у уже готового драйвера (запасной путь)."""
        try:
            options = self._bare_options()
            driver = webdriver.Chrome(options=options, **self._driver_kwargs(options))
            version = driver.capabilities.get("browserVersion", "")
            driver.quit()
            return int(version.split(".")[0]) if version else 0
        except Exception:
            return 0

    def _bare_options(self) -> Options:
        options = Options()
        options.add_argument("--headless=new")
        return options

    def _apply_proxy_auth(self) -> None:
        """Прокси с логином/паролем: Chrome не умеет их в --proxy-server, лечим CDP."""
        if not self.driver or not self.proxy:
            return
        try:
            self.driver.execute_cdp_cmd("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
            self.driver.execute_cdp_cmd(
                "Network.setExtraHTTPHeaders", {"headers": {"Proxy-Authorization": self._basic_auth_header()}}
            )
        except WebDriverException as exc:
            logger.warning("Не удалось задать авторизацию прокси через CDP: %s", exc)

    def _basic_auth_header(self) -> str:
        import base64

        token = f"{self.proxy.login}:{self.proxy.password or ''}"
        return "Basic " + base64.b64encode(token.encode()).decode()

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def restart(self) -> webdriver.Chrome:
        """Полный перезапуск браузера (после блокировки или «зависания» вкладки)."""
        logger.info("Перезапуск браузера...")
        self.quit()
        return self.start()

    def quit(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except WebDriverException:
                pass
            self.driver = None
        if self._profile_dir and self._profile_dir.exists() and not self.config.profile_dir:
            import shutil

            shutil.rmtree(self._profile_dir, ignore_errors=True)
            self._profile_dir = None

    def __enter__(self) -> "BrowserSession":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.quit()
