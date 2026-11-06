"""Модуль парсинга Авито через Selenium (ТЗ, п.3.1).

Стратегия извлечения данных строится на стабильных атрибутах сайта
(`data-marker`, микроразметка schema.org `itemprop`), а не на hash-классах,
которые Авито меняет при каждой сборке. Дополнительно используются:
  * имитация поведения человека (паузы, прокрутка, движения мыши);
  * детект страницы «Доступ ограничен: проблема с IP» с адаптивным бэкоффом;
  * перезапуск браузера при критических сбоях WebDriver.
"""

from __future__ import annotations

import base64
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from selenium.common.exceptions import (TimeoutException,
                                        WebDriverException)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from .browser import BrowserSession
from .config import Config, split_urls
from .database import Database
from .human import HumanBehavior
from .logger import get_logger
from .photos import PhotoDownloader

logger = get_logger("avito.scraper")

# Ссылка объявления Авито всегда оканчивается длинным числовым id:
#   /moskva/avtomobili/mercedes-benz_g-klass_2026_8239752533?context=...
AD_ID_RE = re.compile(r"[-_](\d{7,})(?:[?#/]|$)")

# Служебные страницы Авито: блокировка видна по заголовку вкладки, а не по словам в контенте.
# Авито отдаёт две разные «заглушки», и реагировать на них надо по-разному:
# 1) hard-бан по IP («Доступ ограничен: проблема с IP») — перезапуск бесполезен, нужен другой адрес;
# 2) JS-челлендж («Доступ ограничен: проверка безопасности») — проходит сам за несколько секунд,
#    а перезапуск браузера только начинает проверку заново.
IP_BLOCK_MARKERS = ("проблема с ip", "problem with ip", "доступ к сайту ограничен", "access denied")
CHALLENGE_MARKERS = ("проверка безопасности", "подтвердите, что запросы", "checking your browser",
                     "just a moment", "are you a robot", "доступ ограничен")
BLOCK_TITLE_MARKERS = IP_BLOCK_MARKERS  # обратная совместимость старых импортов
BLOCK_BODY_MARKERS = ("доступ ограничен: проблема с ip", "запрос не прошёл", "captcha-ifr",
                      "are you a robot")
NOT_FOUND_MARKERS = ("такой страницы не существует", "страница не найдена")

# карточка объявления в выдаче Авито
LISTING_SELECTOR = '[data-marker="item"]'

# JS: собрать карточки выдачи. Внутри карточки идём по schema.org/data-marker.
LISTING_JS = r"""
const cards = Array.from(document.querySelectorAll('[data-marker="item"]'));
const textOf = (root, selectors) => {
    for (const sel of selectors) {
        const el = root.querySelector(sel);
        if (el) {
            const t = (el.getAttribute('content') || el.textContent || '').trim();
            if (t) return t;
        }
    }
    return '';
};
const AD_LINK = /[-_]\d{7,}([?#/]|$)/;
const linkOf = (card) => {
    const direct = card.querySelector('[itemprop="url"][href], a[itemprop="url"][href], [data-marker="item-photo-sliderLink"][href]');
    if (direct) return direct.getAttribute('href') || '';
    const anchor = Array.from(card.querySelectorAll('a[href]')).find(a => AD_LINK.test(a.getAttribute('href') || ''));
    return anchor ? anchor.getAttribute('href') : '';
};
const imageOf = (card) => {
    const meta = card.querySelector('[itemprop="image"]');
    if (meta) {
        const v = meta.getAttribute('content') || meta.getAttribute('src') || '';
        if (v) return v;
    }
    const img = card.querySelector('img[src*="avito.st"], img[data-src*="avito.st"]');
    if (img) return img.getAttribute('src') || img.getAttribute('data-src') || '';
    return '';
};
const cleanHref = (href) => href ? href.split('?')[0] : '';
const out = [];
for (const card of cards) {
    out.push({
        href: cleanHref(linkOf(card)),
        title: textOf(card, ['[itemprop="name"]', '[data-marker="item-title"]', 'h3', 'h2']),
        price: textOf(card, ['[itemprop="price"]', '[data-marker="item-price-value"]', '[data-marker="item-price"]']),
        currency: textOf(card, ['[itemprop="priceCurrency"]']),
        image: imageOf(card),
        location: textOf(card, ['[data-marker="item-location"]']),
        params: textOf(card, ['[data-marker="item-specific-params"]']),
        is_org: !!card.querySelector('[data-marker="item-badge"], [data-marker="seller-type"]'),
    });
}
return { total: cards.length, items: out, title: document.title, body: document.body ? document.body.innerText.slice(0, 400) : '' };
"""

# JS: собрать данные страницы объявления
DETAIL_JS = r"""
const text = (sel) => {
    const el = document.querySelector(sel);
    return el ? (el.getAttribute('content') || el.textContent || '').trim() : '';
};
const html = document.documentElement.innerHTML;

const gallery = [];
// основной источник — галерея самого объявления; картинки со страницы (похожие
// объявления, аватары, промо-блоки) в выдачу фото попадать не должны
const root = document.querySelector('[data-marker="item-view/main-gallery"]') || document;
root.querySelectorAll('img').forEach(img => {
    const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
    if (src.indexOf('img.avito.st/image') !== -1 && (img.naturalWidth || 0) >= 300) gallery.push(src);
});
// резервный вариант: все картинки объявления на странице, если галерея не отрендерилась
if (gallery.length === 0) {
    document.querySelectorAll('img').forEach(img => {
        const src = img.currentSrc || img.src || '';
        if (src.indexOf('img.avito.st/image') !== -1 && (img.naturalWidth || 0) >= 600) gallery.push(src);
    });
}

const params = {};
document.querySelectorAll('[data-marker="item-view/item-advanced-params-group"]').forEach(group => {
    const titleEl = group.querySelector('[data-marker="item-view/item-advanced-params-group-title"]');
    group.querySelectorAll('li').forEach(li => {
        const parts = (li.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
        if (parts.length >= 2) params[parts[0]] = parts.slice(1).join(' ');
    });
});

let description = text('[data-marker="item-view/item-description"]') || text('[data-marker="text-block"]') ||
                  text('[itemprop="description"]') || text('.item-description') ||
                  text('meta[name="description"]');

return {
    title: text('h1') || text('[itemprop="name"]') || document.title,
    price: text('[itemprop="price"]') || text('[data-marker="item-view/item-price"]'),
    price_text: text('[data-marker="item-view/item-price"]') || text('[data-marker="price-tag"]'),
    availability: text('[itemprop="availability"]'),
    location: text('[data-marker="address"]') || text('[data-marker="item-view/item-location"]'),
    seller: text('[data-marker="item-seller"]') || text('[data-marker="seller-container"]'),
    description: description.replace(/\u00a0/g, ' ').trim(),
    images: Array.from(new Set(gallery)),
    params: params,
    title_tag: document.title,
    body_head: document.body ? document.body.innerText.slice(0, 300) : '',
};
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_ws(value: Any) -> str:
    """Схлопнуть пробелы (включая неразрывные) в одну строку."""
    if not value:
        return ""
    text = str(value).replace(chr(160), " ").replace(chr(8239), " ")
    return " ".join(text.split())


def clean_multiline(value: Any) -> str:
    """Нормализовать пробелы, сохранив структуру абзацев описания."""
    if not value:
        return ""
    text = str(value).replace(chr(160), " ").replace(chr(8239), " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(lines).strip()


def parse_price(value: Any) -> int | None:
    """'49 970 000 ₽' / '49970000' → 49970000"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def extract_ad_id(url: str) -> str | None:
    match = AD_ID_RE.search(url or "")
    return match.group(1) if match else None


def with_page(url: str, page: int) -> str:
    """Добавить/заменить параметр пагинации `p` в URL выдачи."""
    if page <= 1:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["p"] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def source_label(url: str) -> str:
    """Человеческая подпись источника для статусов: город/категория вместо всего URL."""
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)
    if query.get("q"):
        return f"поиск «{query['q'][0]}»"
    path = (parsed.path or "").strip("/").rstrip("-")
    if path:
        parts = [p for p in path.split("/") if p]
        # хвост вида mobile-ASgBAgICAUSwwQ2I_Dc — токен фильтра, в подписи не нужен
        if parts and "-" in parts[-1] and len(parts[-1]) > 24:
            parts = parts[:-1]
        return "/".join(parts[-2:]) if parts else parsed.netloc
    return parsed.netloc or (url or "")


class AvitoScraper:
    """Скрейпер: выдача → дедупликация по SQLite → детали → фотографии."""

    def __init__(self, config: Config | None = None, db: Database | None = None,
                 headless: bool | None = None, save_to_db: bool = True):
        self.config = config or Config.load()
        if headless is not None:
            self.config.browser.headless = headless
        self.save_to_db = save_to_db
        self.db = db or (Database(self.config.parser) if save_to_db else None)
        self.human = HumanBehavior(self.config.browser)
        self.session = BrowserSession(self.config.browser)
        self.driver: WebDriver | None = None
        self._photos: PhotoDownloader | None = None
        self.blocked_count = 0
        self._content_fails = 0  # повторы одной страницы без смены IP
        self._retry_ids: set[str] = set()  # «недолитые» объявления из прошлых прогонов
        self._image_bodies: dict[str, bytes] = {}  # байты фото, загруженные браузером
        # итог по каждому источнику за текущий прогон: {url: {found, new, status}}
        self.sources_stats: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def _enable_network_capture(self) -> None:
        """Включить CDP Network, чтобы потом достать тела загруженных браузером картинок."""
        if not self.driver:
            return
        try:
            self.driver.execute_cdp_cmd("Network.enable", {
                "maxTotalBufferSize": 100 * 1024 * 1024,
                "maxResourceBufferSize": 30 * 1024 * 1024,
            })
        except WebDriverException as exc:
            logger.debug("CDP Network недоступен: %s", str(exc).splitlines()[0])

    def _attach_driver(self) -> None:
        """Подключиться к (пере)запущенному драйверу: CDP-перехват + загрузчик фото."""
        self._enable_network_capture()
        self._image_bodies = {}
        if self._photos:
            self._photos.close()
        self._photos = self._make_photos()

    def _collect_image_bodies(self) -> dict[str, bytes]:
        """Вытащить байты картинок Авито из performance-лога браузера.

        Работает даже там, где прямой запрос к CDN невозможен (SOCKS-прокси с MITM,
        куки-зависимые ссылки): картинку уже загрузил браузер в нашей сессии.
        """
        if not self.driver:
            return {}
        try:
            entries = self.driver.get_log("performance")
        except (WebDriverException, ValueError):
            return {}

        found: dict[str, bytes] = {}
        for entry in entries:
            try:
                message = json.loads(entry["message"])["message"]
            except (KeyError, ValueError, TypeError):
                continue
            if message.get("method") != "Network.responseReceived":
                continue
            response = message.get("params", {}).get("response", {})
            url = response.get("url", "")
            mime = (response.get("mimeType") or "").lower()
            if "img.avito.st/image" not in url or not mime.startswith("image/"):
                continue
            request_id = response.get("requestId")
            if not request_id or url in found:
                continue
            try:
                payload = self.driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
            except WebDriverException:
                continue  # тело уже вытеснено из буфера
            body = payload.get("base64Encoded") and base64.b64decode(payload.get("body", "")) or \
                (payload.get("body") or "").encode("latin-1")
            if body:
                found[url] = body
        if found:
            logger.debug("Из кэша браузера получено %d картинок", len(found))
        return found

    def _make_photos(self) -> PhotoDownloader:
        """Загрузчик фото ходит через тот же прокси, что и браузер."""
        return PhotoDownloader(
            self.config.parser,
            cookies=self._cookies(),
            user_agent=self.session.user_agent,
            proxy=self.session.proxy,
            verify_tls=not self.config.browser.ignore_insecure_tls,
        )

    def start(self) -> WebDriver:
        self.driver = self.session.start()
        self._attach_driver()
        return self.driver

    def close(self) -> None:
        if self._photos:
            self._photos.close()
            self._photos = None
        self.session.quit()
        self.driver = None
        if self.db and self.save_to_db:
            self.db.close()

    def __enter__(self) -> "AvitoScraper":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _cookies(self) -> dict[str, str]:
        if not self.driver:
            return {}
        try:
            return {c["name"]: c["value"] for c in self.driver.get_cookies()}
        except WebDriverException:
            return {}

    # ------------------------------------------------------------------ #
    # navigation + anti-block
    # ------------------------------------------------------------------ #
    def _page_state(self, payload: dict | None = None) -> str:
        """Состояние страницы: 'ok' | 'challenge' | 'ip_block' | 'not_found' | 'dead_browser'."""
        if not self.driver:
            return "dead_browser"
        try:
            title = (self.driver.title or "").lower()
        except WebDriverException:
            return "dead_browser"
        if any(marker in title for marker in IP_BLOCK_MARKERS):
            return "ip_block"
        if payload:
            head = str(payload.get("title_tag") or "").lower()
            if any(marker in head for marker in IP_BLOCK_MARKERS):
                return "ip_block"
            body = str(payload.get("body_head") or "").lower()[:200]
            if any(marker in body for marker in BLOCK_BODY_MARKERS):
                return "ip_block"
        if any(marker in title for marker in CHALLENGE_MARKERS):
            return "challenge"
        if any(marker in title for marker in NOT_FOUND_MARKERS):
            return "not_found"
        return "ok"

    def _looks_blocked(self, payload: dict | None = None) -> bool:
        """Заглушка Авито вместо контента (бан по IP или незавершённый челлендж)."""
        return self._page_state(payload) in ("ip_block", "challenge", "dead_browser")

    def _wait_challenge(self) -> str:
        """Дать JS-челленджу отпуститься: ждать, но браузер не перезапускать.

        Возвращает состояние страницы по итогам ожидания.
        """
        state = self._page_state()
        if state != "challenge":
            return state
        limit = float(self.config.browser.challenge_wait)
        logger.info("Авито включил проверку безопасности — жду снятия до %.0f сек (без рестарта)", limit)
        deadline = time.time() + limit
        while time.time() < deadline:
            time.sleep(2)
            state = self._page_state()
            if state != "challenge":
                logger.info("Челлендж снят (состояние: %s)", state)
                return state
        logger.warning("Челлендж не снялся за %.0f сек", limit)
        return state

    def _switch_proxy(self, where: str) -> bool:
        """IP заблокирован: карантируем прокси и перезапускаемся с другим адресом.

        Дешевле долгого бэкоффа: пока пул живой, смена адреса решает проблему сразу.
        """
        self.blocked_count += 1
        action = self.session.mark_proxy_bad(f"страница не отдаёт контент на {where}")
        if action == "none":
            logger.error("Менять прокси не на что и прямой доступ запрещён — останавливаюсь")
            return False
        self.human.increase_tension()
        self.human.pause(3.0, 8.0)
        try:
            self.driver = self.session.restart()
            self._attach_driver()
        except (WebDriverException, RuntimeError) as exc:
            logger.error("Не удалось перезапустить браузер: %s", exc)
            return False
        logger.info("Продолжаю с %s", self.session.proxy or "прямого подключения")
        return True

    def _handle_block(self) -> None:
        """Адаптивная реакция на блокировку: пауза, рост задержек, рестарт браузера."""
        self.blocked_count += 1
        wait = min(self.config.parser.block_backoff_base * (2 ** (self.blocked_count - 1)),
                   self.config.parser.block_backoff_max)
        wait += random.uniform(0, 20)
        logger.warning("Похоже на блокировку (серия %d). Пауза %.0f сек и перезапуск браузера.",
                       self.blocked_count, wait)
        self.human.increase_tension()
        time.sleep(wait)
        try:
            self.driver = self.session.restart()
            self._attach_driver()
        except (WebDriverException, RuntimeError) as exc:
            logger.error("Не удалось перезапустить браузер: %s", exc)

    def _dom_ready(self, wait_selector: str | None = None) -> bool:
        """Готов ли DOM (readyState + наличие ожидаемого элемента)."""
        if not self.driver:
            return False
        try:
            state = self.driver.execute_script("return document.readyState")
        except WebDriverException:
            return False
        if state not in ("interactive", "complete"):
            return False
        if not wait_selector:
            return True
        try:
            return len(self.driver.find_elements(By.CSS_SELECTOR, wait_selector)) > 0
        except WebDriverException:
            return False

    def _stop_loading(self) -> None:
        """Обрезать хвосты запросов (сокеты/аналитику Авито), чтобы не копить таймауты."""
        if not self.driver:
            return
        try:
            self.driver.execute_script("window.stop();")
        except WebDriverException:
            pass

    def _recover(self, url: str, reason: str) -> bool:
        """Реакция на неудачу: сменить IP, повторить страницу или сдаться.

        Прокси, который не отдаёт контент или ловит «вечную проверку», — это не
        «неудачная попытка», а неудачный адрес: менять его надо сразу, без бэкоффа.
        """
        if self.session.proxy:
            logger.warning("Неудача (%s) на прокси %s — пробую другой адрес", reason, self.session.proxy)
            return self._switch_proxy(url)
        self._content_fails += 1
        limit = max(1, self.config.parser.max_retries)
        if self._content_fails >= limit:
            logger.error("Страница %s недоступна после %d попыток (%s)", url, self._content_fails, reason)
            return False
        logger.warning("Неудача (%s) — повторная попытка %d/%d напрямую", reason,
                       self._content_fails + 1, limit)
        if reason in ("ip_block", "challenge"):
            # прямой IP поймал бан: отступаем и перезапускаемся, как при классической блокировке
            self._handle_block()
        return True

    def open_url(self, url: str, wait_selector: str | None = None, timeout: float | None = None) -> bool:
        """Зайти на страницу с человеческими паузами и обработкой блокировок.

        Возвращает True, если страница пригодна к парсингу. Повторы страницы считаются
        отдельно от смены IP: ротация — это новый шанс, а не та же неудачная попытка.
        """
        if not self.driver:
            self.start()
        if timeout is None:
            # выдача рендерится дольше прочих страниц: ждём её по render_timeout
            timeout = float(
                self.config.browser.render_timeout
                if wait_selector == LISTING_SELECTOR
                else self.config.browser.page_load_timeout
            )
        self._content_fails = 0
        max_total = max(1, self.config.parser.max_retries) + len(self.session.proxies) + 2

        for attempt in range(1, max_total + 1):
            self._stop_loading()  # освобождаем сеть от «хвостов» предыдущей страницы
            self.human.pause()
            try:
                self.driver.get(url)
            except TimeoutException:
                # Авито держит long-poll сокеты: событие load может не наступить.
                # Если DOM уже готов и нужный элемент на месте — продолжаем работу.
                logger.warning("Таймаут загрузки %s (попытка %d) — проверяю готовность DOM", url, attempt)
                if not self._dom_ready(wait_selector):
                    self._stop_loading()
                    if self._recover(url, "таймаут загрузки"):
                        continue
                    return False
                logger.info("DOM готов несмотря на таймаут: %s", url)
            except WebDriverException as exc:
                logger.warning("Сбой браузера на %s: %s", url, str(exc).splitlines()[0])
                if self._recover(url, "сбой браузера"):
                    continue
                return False

            # заглушка «проверка безопасности» проходит сама — не трогаем браузер;
            # «проблема с IP» не проходит никогда — сразу меняем адрес
            state = self._wait_challenge()
            if state == "not_found":
                logger.error("Страница не найдена (проверьте URL): %s", url)
                return False
            if state != "ok":
                if self._recover(url, state):
                    continue
                return False

            self.human.scroll_page(self.driver)
            self.human.idle_like_user(self.driver)

            if wait_selector:
                ok = self.human.wait_for(
                    self.driver,
                    lambda sel=wait_selector: len(self.driver.find_elements(By.CSS_SELECTOR, sel)) > 0,
                    timeout=timeout,
                )
                if not ok:
                    state = self._page_state()
                    if state == "not_found":
                        logger.error("Страница не найдена (проверьте URL): %s", url)
                        return False
                    logger.warning("За %.0f сек не появилось ни одного элемента '%s'", timeout, wait_selector)
                    if self._recover(url, state if state != "ok" else "контент не отрисован"):
                        continue
                    return False

            self.blocked_count = 0
            self.human.relax()
            return True

        return False

    # ------------------------------------------------------------------ #
    # listing
    # ------------------------------------------------------------------ #
    def parse_listing(self, url: str, page: int = 1) -> list[dict[str, Any]]:
        """Спарсить страницу выдачи: id, заголовок, цена, ссылка (ТЗ, п.3.1)."""
        target = with_page(url, page)
        logger.info("Читаю выдачу: %s", target)
        if not self.open_url(target, wait_selector=LISTING_SELECTOR):
            return []

        try:
            payload = self.driver.execute_script(LISTING_JS)
        except WebDriverException as exc:
            logger.error("Не удалось извлечь выдачу: %s", exc)
            return []

        if not payload or not payload.get("items"):
            state = self._page_state(payload)
            # на заглушке Авито резервный разбор по ссылкам нашёл бы «мусор» (шапку, меню),
            # поэтому fallback только для реально живых страниц
            if state != "ok":
                logger.warning("Страница выдачи не отдаёт контент (состояние: %s) — объявлений 0", state)
                return []
            logger.warning("Карточки не найдены (str=%s, title=%r) — пробую резервный разбор ссылок",
                           payload.get("total") if payload else "?", payload.get("title") if payload else "?")
            return self._parse_listing_fallback(target)

        if self._looks_blocked(payload):
            logger.warning("Страница выдачи заблокирована на этапе извлечения")
            return []

        base = f"{urlparse(target).scheme}://{urlparse(target).netloc}"
        ads: list[dict[str, Any]] = []
        for item in payload["items"]:
            href = item.get("href") or ""
            ad_url = href if href.startswith("http") else urljoin(base, href)
            avito_id = extract_ad_id(ad_url)
            if not avito_id:
                continue
            ads.append({
                "avito_id": avito_id,
                "title": clean_ws(item.get("title")),
                "price": clean_ws(item.get("price")),
                "price_rub": parse_price(item.get("price")),
                "url": ad_url,
                "location": clean_ws(item.get("location")),
                "params": {"listing": clean_ws(item.get("params"))},
                "images": [item["image"]] if item.get("image") else [],
                "is_org": bool(item.get("is_org")),
                "parsed_at": _now_iso(),
            })

        logger.info("Найдено %d объявлений на странице %d", len(ads), page)
        return ads

    def _parse_listing_fallback(self, page_url: str) -> list[dict[str, Any]]:
        """Резервный способ: вынуть id и заголовки прямо из HTML страницы."""
        try:
            html = self.driver.page_source
        except WebDriverException:
            return []

        seen: set[str] = set()
        ads: list[dict[str, Any]] = []
        base = f"{urlparse(page_url).scheme}://{urlparse(page_url).netloc}"
        for match in re.finditer(r'href="(/[^"]*?[-_]\d{7,}(?:\?[^"]*)?)"[^>]*>(.{0,400}?)</a>', html, re.S):
            href, inner = match.group(1), match.group(2)
            avito_id = extract_ad_id(href)
            if not avito_id or avito_id in seen:
                continue
            seen.add(avito_id)
            title = re.sub(r"<[^>]+>", " ", inner)
            title = re.sub(r"\s+", " ", title).replace("&nbsp;", " ").strip()
            # служебные заголовки (шапка, «Авито — Объявления на сайте Авито») — не объявления
            if len(title) < 5 or any(marker in title.lower() for marker in NOT_FOUND_MARKERS):
                continue
            if title.lower().startswith("авито —"):
                continue
            price_match = re.search(r"(\d[\d\s\u00a0\u202f]*)(?:\s*(?:₽|руб))", title)
            ads.append({
                "avito_id": avito_id,
                "title": title[:200],
                "price": price_match.group(1).strip() if price_match else "",
                "price_rub": parse_price(price_match.group(1)) if price_match else None,
                "url": urljoin(base, href),
                "location": "",
                "params": {},
                "images": [],
                "parsed_at": _now_iso(),
            })
        logger.info("Резервный разбор выдал %d объявлений", len(ads))
        return ads

    # ------------------------------------------------------------------ #
    # details
    # ------------------------------------------------------------------ #
    def parse_details(self, ad: dict[str, Any]) -> dict[str, Any]:
        """Дочитать страницу объявления: полное описание и прямые ссылки на фото."""
        url = ad.get("url")
        if not url:
            return ad
        if not self.open_url(url, wait_selector="h1"):
            return ad

        # галерея подгружается лениво — пролистываем карусель и собираем кадры
        shots = self._reveal_gallery(max_shots=max(self.config.parser.max_photos + 2, 6))
        try:
            payload = self.driver.execute_script(DETAIL_JS)
        except WebDriverException as exc:
            logger.error("Ошибка извлечения деталей %s: %s", url, exc)
            return ad

        if not payload or self._looks_blocked(payload):
            logger.warning("Страница деталей %s заблокирована/пуста", url)
            return ad

        ad["description"] = clean_multiline(payload.get("description"))
        if payload.get("title"):
            ad["title"] = clean_ws(payload["title"])
        price = payload.get("price") or payload.get("price_text")
        if price:
            ad["price"] = clean_ws(price)
            ad["price_rub"] = parse_price(price)
        if payload.get("location"):
            ad["location"] = clean_ws(payload["location"])
        params = dict(ad.get("params") or {})
        params.update(payload.get("params") or {})
        ad["params"] = params

        # приоритет у полноформатных кадров из галереи, собранных прокликиванием
        merged = list(dict.fromkeys(shots + list(payload.get("images") or [])))
        images = PhotoDownloader.normalize(merged)
        ad["images"] = images or ad.get("images", [])

        # байты картинок забираем из кэша браузера: через SOCKS-прокси с MITM
        # прямой запрос к CDN не проходит, а браузер их уже скачал
        self._image_bodies.update(self._collect_image_bodies())
        logger.debug("Детали %s: описание %d симв., фото %d, в кэше %d", ad.get("avito_id"),
                     len(ad["description"]), len(ad["images"]), len(self._image_bodies))
        return ad

    # JS-сборщики для галереи: только внутри main-gallery, без regex (надёжнее с экранированием)
    _GALLERY_ROOT = ("const root = document.querySelector('[data-marker=\"item-view/main-gallery\"]')"
                     " || document.querySelector('[data-marker=\"card-gallery\"]')"
                     " || document.querySelector('[role=\"listbox\"]') || document;")

    _JS_FORCE_LAZY = (
        "document.querySelectorAll('img[data-src], img[data-lazy-src]').forEach(el => {"
        "  const v = el.getAttribute('data-src') || el.getAttribute('data-lazy-src');"
        "  if (v && !el.src) el.src = v;"
        "});"
    )

    _JS_THUMBS = (
        _GALLERY_ROOT +
        "return root.querySelectorAll('li').length;"
    )

    # Авито переключает активный кадр только по клику на button внутри миниатюры,
    # сам li на клик не реагирует
    _JS_CLICK_THUMB = (
        _GALLERY_ROOT +
        "const items = root.querySelectorAll('li');"
        "const li = items[arguments[0]];"
        "if (!li) return false;"
        "const btn = li.querySelector('button') || li;"
        "li.scrollIntoView({block: 'center'});"
        "btn.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));"
        "btn.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));"
        "btn.click();"
        "return true;"
    )

    _JS_LARGE_SHOTS = (
        _GALLERY_ROOT +
        "const out = [];"
        "root.querySelectorAll('img').forEach(img => {"
        "  const src = img.currentSrc || img.src || '';"
        "  if (src.indexOf('img.avito.st/image') !== -1 && (img.naturalWidth || 0) >= 500) out.push(src);"
        "});"
        "return out;"
    )

    def _reveal_gallery(self, max_shots: int = 8) -> list[str]:
        """Прокликать миниатюры галереи и собрать полноформатные кадры.

        Авито отдаёт большой файл только для активного кадра, поэтому листаем
        карусель как пользователь и забираем то, что реально загрузилось.
        """
        if not self.driver:
            return []

        try:
            self.driver.execute_script(self._JS_FORCE_LAZY)
        except WebDriverException:
            pass

        self.human.wait_for(
            self.driver,
            lambda: len(self.driver.execute_script(self._JS_LARGE_SHOTS)) > 0,
            timeout=8,
            poll=0.5,
            settle=0.3,
        )

        shots: list[str] = []

        def collect() -> None:
            try:
                found = self.driver.execute_script(self._JS_LARGE_SHOTS) or []
            except WebDriverException:
                return
            for src in found:
                if src not in shots:
                    shots.append(src)

        collect()

        try:
            thumbs = int(self.driver.execute_script(self._JS_THUMBS) or 0)
        except WebDriverException:
            thumbs = 0

        for index in range(min(thumbs, max_shots)):
            if len(shots) >= max_shots:
                break
            try:
                clicked = self.driver.execute_script(self._JS_CLICK_THUMB, index)
            except WebDriverException:
                break
            if not clicked:
                break
            time.sleep(random.uniform(0.5, 1.3))  # кадр должен успеть загрузиться
            collect()

        self.human.scroll_page(self.driver, steps=2)
        logger.debug("Галерея: собрано %d полноформатных кадров", len(shots))
        return shots

    # ------------------------------------------------------------------ #
    # photos
    # ------------------------------------------------------------------ #
    def download_photos(self, ad: dict[str, Any], dest: Path | str | None = None) -> list[Path]:
        """Скачать до MAX_PHOTOS_PER_AD фотографий объявления во временную папку."""
        if not self._photos:
            return []
        dest = Path(dest or (self.config.parser.photos_dir / str(ad["avito_id"])))
        return self._photos.download(ad.get("images") or [], dest,
                                     max_photos=self.config.parser.max_photos,
                                     ad_id=ad.get("avito_id"),
                                     bodies=self._image_bodies)

    # ------------------------------------------------------------------ #
    # orchestration helpers
    # ------------------------------------------------------------------ #
    def is_new(self, avito_id: str) -> bool:
        """Новое ли объявление: нет в базе ИЛИ лежит там «недолитым» (детали не пришли)."""
        if not self.db:
            return True
        if not self.db.is_parsed(avito_id):
            return True
        return avito_id in self._retry_ids

    def _as_urls(self, url: "str | list[str] | None") -> list[str]:
        """Нормализовать вход: одна ссылка, список или всё из конфигурации."""
        if url is None:
            return self.config.parser.sources()
        raw = url if isinstance(url, (list, tuple, set)) else [url]
        urls: list[str] = []
        for item in raw:
            for part in split_urls(str(item or "")):
                if part not in urls:
                    urls.append(part)
        return urls

    def scrape(self, url: "str | list[str] | None" = None, pages: int | None = None,
               with_details: bool | None = None,
               with_photos: bool | None = None, only_new: bool = True,
               limit: int | None = None,
               on_progress: Callable[[str], None] | None = None,
               on_ad: Callable[[dict], None] | None = None) -> list[dict[str, Any]]:
        """Полный цикл по одной ИЛИ нескольким отслеживаемым ссылкам.

        url — строка, список строк или None (тогда берутся ссылки конфигурации прогона:
        их кладёт в конфиг админка/CLI, из окружения они больше не читаются).
        Лимит объявления-за-прогон считается по всем источникам суммарно.
        """
        report = on_progress or (lambda message: None)
        urls = self._as_urls(url)
        if not urls:
            logger.error("Не задано ни одной ссылки — парсить нечего")
            return []

        pages = pages if pages is not None else self.config.parser.pages
        with_details = self.config.parser.fetch_details if with_details is None else with_details
        with_photos = self.config.parser.download_photos if with_photos is None else with_photos
        limit = limit if limit is not None else (self.config.parser.max_ads_per_run or None)

        # список «недолитых» обновляем один раз на прогон
        self._retry_ids = self.db.get_incomplete_ids() if self.db else set()
        if self._retry_ids:
            logger.info("В базе %d объявлений без деталей — повторяем попытку", len(self._retry_ids))

        processed: list[dict[str, Any]] = []
        for index, source in enumerate(urls, 1):
            remaining = None if not limit else max(0, limit - len(processed))
            if remaining == 0:
                logger.info("Лимит %d объявлений за прогон выбран — остальные источники пропускаю", limit)
                for skipped in urls[index - 1:]:
                    self.sources_stats.setdefault(skipped, {"found": 0, "new": 0, "status": "skipped"})
                break
            if len(urls) > 1:
                report(f"Источник {index}/{len(urls)}: {source_label(source)}")
            processed.extend(self._scrape_source(
                source, pages=pages, with_details=with_details, with_photos=with_photos,
                only_new=only_new, limit=remaining, report=report, on_ad=on_ad,
            ))
            if index < len(urls):
                self.human.pause(self.config.parser.inter_page_pause_min,
                                 self.config.parser.inter_page_pause_max)

        logger.info("Прогон завершён: %d источников, %d объявлений обработано", len(urls), len(processed))
        return processed

    def _scrape_source(self, url: str, pages: int, with_details: bool, with_photos: bool,
                       only_new: bool, limit: int | None,
                       report: Callable[[str], None],
                       on_ad: Callable[[dict], None] | None) -> list[dict[str, Any]]:
        """Обработать одну ссылку выдачи: список → новые → детали → фото → база."""
        logger.info("Разбираю источник: %s", url)
        self.sources_stats[url] = {"found": 0, "new": 0, "status": "error"}
        if self.db:
            self.db.register_source(url)

        collected: list[dict[str, Any]] = []
        new_ads: list[dict[str, Any]] = []

        for page in range(1, pages + 1):
            report(f"{source_label(url)}: страница {page} из {pages}")
            ads = self.parse_listing(url, page=page)
            if not ads:
                logger.info("Страница %d пуста — останавливаю пагинацию", page)
                report(f"{source_label(url)}: страница {page} — карточек не найдено")
                break
            collected.extend(ads)

            for ad in ads:
                ad["source_url"] = url
                if only_new and not self.is_new(ad["avito_id"]):
                    continue
                new_ads.append(ad)

            if limit and len(new_ads) >= limit:
                new_ads = new_ads[:limit]
                break
            if page < pages:
                self.human.pause(self.config.parser.inter_page_pause_min,
                                 self.config.parser.inter_page_pause_max)

        logger.info("В выдаче %d объявлений, новых: %d", len(collected), len(new_ads))
        report(f"{source_label(url)}: в выдаче {len(collected)}, новых для обработки {len(new_ads)}")

        sample = self.config.parser.details_sample
        if sample and len(new_ads) > sample:
            logger.info("Ограничиваю парсинг деталей: %d из %d", sample, len(new_ads))
            new_ads = new_ads[:sample]

        for index, ad in enumerate(new_ads, 1):
            logger.info("Новое объявление %d/%d: [%s] %s", index, len(new_ads), ad["avito_id"], ad["title"][:60])
            report(f"{source_label(url)}: дочитываю {index}/{len(new_ads)} — {ad['title'][:60]}")
            if with_details:
                self.parse_details(ad)
                self.human.pause(self.config.parser.inter_page_pause_min,
                                 self.config.parser.inter_page_pause_max)
            if with_photos:
                ad["photo_files"] = [str(p) for p in self.download_photos(ad)]

            ad["status"] = "complete" if (ad.get("description") or ad.get("photo_files")
                                          or not with_details) else "partial"
            if self.db and self.save_to_db:
                self.db.save_ad(ad)
                if ad["status"] == "partial":
                    # считаем попытку: после MAX_DETAIL_ATTEMPTS объявление перестанет повторяться
                    attempts = self.db.bump_attempts(ad["avito_id"])
                    logger.warning("Объявление %s дочитано частично (попытка %d)", ad["avito_id"], attempts)
                self.db.commit()
            if on_ad:
                on_ad(ad)

        complete = sum(1 for ad in new_ads if ad.get("status") == "complete")
        logger.info("Готово к публикации: %d из %d", complete, len(new_ads))
        state = "ok" if collected else ("blocked" if self._looks_blocked() else "empty")
        self.sources_stats[url] = {"found": len(collected), "new": len(new_ads), "status": state}
        if self.db:
            self.db.touch_source(url, status=state, found=len(collected), new=len(new_ads))
        return new_ads
