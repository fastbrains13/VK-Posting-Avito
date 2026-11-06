"""Минимальный клиент Авито для MVP: одна страница выдачи и страница объявления.

Никакой пагинации: парсится ровно тот URL, который дал пользователь.
Детали и фото загружаются отдельно, когда пользователь выбрал объявление.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from PIL import Image, UnidentifiedImageError
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

from core.models import ProxyEndpoint

logger = logging.getLogger("avito.client")

AD_ID_RE = re.compile(r"[-_](\d{7,})(?:[?#/]|$)")
BLOCK_MARKERS = (
    "доступ ограничен",
    "проблема с ip",
    "проверка безопасности",
    "подтвердите, что запросы",
    "captcha",
)
LISTING_SELECTOR = '[data-marker="item"]'

LISTING_JS = r"""
const textOf = (root, selectors) => {
  for (const sel of selectors) {
    const el = root.querySelector(sel);
    if (el) {
      const v = el.getAttribute('content') || el.textContent || '';
      const s = v.replace(/\s+/g, ' ').trim();
      if (s) return s;
    }
  }
  return '';
};
const hrefOf = (card) => {
  const el = card.querySelector('a[itemprop="url"][href]')
    || card.querySelector('[data-marker="item-title"] a[href]')
    || card.querySelector('a[href*="/"]');
  if (!el) return '';
  try { return new URL(el.getAttribute('href'), location.href).href; } catch (e) { return ''; }
};
const imageOf = (card) => {
  const img = card.querySelector('img[src*="avito.st"], img[data-src*="avito.st"]')
    || card.querySelector('img');
  return img ? (img.currentSrc || img.src || img.getAttribute('data-src') || '') : '';
};
const out = [];
document.querySelectorAll('[data-marker="item"]').forEach((card, index) => {
  out.push({
    href: hrefOf(card),
    title: textOf(card, ['[itemprop="name"]', '[data-marker="item-title"]', 'h3', 'h2']),
    price: textOf(card, ['[itemprop="price"]', '[data-marker="item-price-value"]', '[data-marker="item-price"]']),
    location: textOf(card, ['[data-marker="item-location"]', '[itemprop="address"]']),
    image: imageOf(card),
    position: index + 1
  });
});
return {
  items: out,
  title: document.title,
  body: document.body ? document.body.innerText.slice(0, 500) : ''
};
"""

DETAIL_JS = r"""
const text = (selectors) => {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const v = el.getAttribute('content') || el.textContent || '';
      const s = v.replace(/\u00a0/g, ' ').trim();
      if (s) return s;
    }
  }
  return '';
};
// innerText сохраняет переносы строк, абзацы и эмодзи так, как их видит
// пользователь; textContent склеивает абзацы в одну строку.
const blockText = (selectors) => {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      const v = el.getAttribute('content') || el.innerText || el.textContent || '';
      const s = v.replace(/\u00a0/g, ' ').replace(/\r\n/g, '\n').trim();
      if (s) return s;
    }
  }
  return '';
};
const root = document.querySelector('[data-marker="item-view/main-gallery"]')
  || document.querySelector('[data-marker="card-gallery"]')
  || document;
const images = [];
root.querySelectorAll('img').forEach((img) => {
  const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
  if (!src) return;
  if (src.indexOf('avito.st') === -1 && src.indexOf('avito.ru') === -1) return;
  if ((img.naturalWidth || 0) < 300) return;
  images.push(src);
});
if (!images.length) {
  document.querySelectorAll('img').forEach((img) => {
    const src = img.currentSrc || img.src || '';
    if (src.indexOf('img.avito.st/image') !== -1) images.push(src);
  });
}
return {
  title: text(['h1', '[itemprop="name"]']),
  price: text(['[itemprop="price"]', '[data-marker="item-view/item-price"]', '[data-marker="price-tag"]']),
  description: blockText(['[data-marker="item-view/item-description"]', '[data-marker="text-block"]', '[itemprop="description"]']),
  location: text(['[data-marker="item-view/item-address"]', '[data-marker="item-location"]', '[itemprop="address"]']),
  images: Array.from(new Set(images)),
  title_tag: document.title,
  body: document.body ? document.body.innerText.slice(0, 500) : ''
};
"""


class AvitoError(RuntimeError):
    """Ошибка парсинга Авито с понятным текстом для UI."""


class AvitoBlocked(AvitoError):
    """Авито вернул заглушку/капчу."""


@dataclass
class PhotoPayload:
    position: int
    url: str
    content: bytes
    content_type: str
    filename: str
    sha256: str


def parse_price(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", str(value))
    return int(digits) if digits else None


def extract_ad_id(url: str) -> str | None:
    match = AD_ID_RE.search(url or "")
    return match.group(1) if match else None


def _is_blocked(title: str, body: str) -> bool:
    haystack = f"{title}\n{body}".lower()
    return any(marker in haystack for marker in BLOCK_MARKERS)


class AvitoClient:
    """Selenium-клиент с одним браузером на задачу."""

    def __init__(self, headless: bool | None = None, proxy: ProxyEndpoint | None = None) -> None:
        self.headless = settings.AVITO_HEADLESS if headless is None else headless
        self.page_timeout = settings.AVITO_PAGE_TIMEOUT
        self.render_timeout = settings.AVITO_RENDER_TIMEOUT
        self.user_agent = settings.AVITO_USER_AGENT
        self.proxy = proxy
        self.verify_tls = not settings.PROXY_INSECURE_TLS
        self._cookies: dict[str, str] = {}

    # ------------------------------------------------------------------
    # браузер
    # ------------------------------------------------------------------
    def _options(self) -> Options:
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1440,1000")
        options.add_argument("--lang=ru-RU,ru")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(f"--user-agent={self.user_agent}")
        # Avito держит long-poll соединения: обычный driver.get может ждать
        # загрузки минутами. Навигацию делаем через CDP, а готовность DOM
        # проверяем своим ожиданием селектора.
        options.page_load_strategy = "none"
        if settings.AVITO_PROFILE_DIR:
            profile = Path(settings.AVITO_PROFILE_DIR)
            if not profile.is_absolute():
                profile = Path(settings.BASE_DIR) / profile
            profile.mkdir(parents=True, exist_ok=True)
            options.add_argument(f"--user-data-dir={profile}")
        if settings.CHROME_BIN:
            options.binary_location = settings.CHROME_BIN
        if self.proxy:
            options.add_argument(f"--proxy-server={self.proxy.chrome_url}")
        return options

    def _driver(self) -> webdriver.Chrome:
        service = None
        if settings.CHROMEDRIVER_PATH:
            service = Service(executable_path=settings.CHROMEDRIVER_PATH)
        driver = webdriver.Chrome(options=self._options(), service=service) if service else webdriver.Chrome(options=self._options())
        driver.set_page_load_timeout(self.page_timeout)
        driver.set_script_timeout(self.page_timeout)
        if self.proxy and self.proxy.username and self.proxy.scheme == ProxyEndpoint.SCHEME_HTTP:
            self._apply_proxy_auth(driver)
        return driver

    def _apply_proxy_auth(self, driver: webdriver.Chrome) -> None:
        """HTTP-прокси с логином/паролем: Chrome не принимает их в --proxy-server.

        Это best-effort: часть прокси/версий Chrome может потребовать ввода
        пароля вручную. Для SOCKS5 с авторизацией браузер не поддерживается.
        """
        if not self.proxy or not self.proxy.username:
            return
        import base64

        token = f"{self.proxy.username}:{self.proxy.password}"
        header = "Basic " + base64.b64encode(token.encode()).decode()
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd(
                "Network.setExtraHTTPHeaders", {"headers": {"Proxy-Authorization": header}}
            )
        except WebDriverException as exc:
            logger.warning("Не удалось задать авторизацию прокси через CDP: %s", exc)

    def _open(self, driver: webdriver.Chrome, url: str, selector: str) -> bool:
        """Открыть URL, не дожидаясь полной загрузки, и дождаться селектора.

        Avito может отдавать JS-челлендж и держать long-poll соединения.
        Поэтому навигация идёт через CDP, а готовность страницы проверяем
        сами: ждём смену документа, снятие челленджа и появление селектора.
        """
        # Сбрасываем старый DOM, иначе WebDriverWait найдёт h1 предыдущей
        # страницы и вернёт управление до фактической навигации.
        try:
            driver.execute_cdp_cmd("Page.navigate", {"url": "about:blank"})
            time.sleep(0.3)
        except WebDriverException:
            pass
        try:
            driver.execute_cdp_cmd("Page.navigate", {"url": url})
        except WebDriverException:
            # Fallback для старых драйверов/CDP.
            try:
                driver.get(url)
            except TimeoutException:
                logger.info("Таймаут навигации, проверяю DOM: %s", url)

        deadline = time.time() + max(10.0, float(self.render_timeout))
        challenge_seen = False
        while time.time() < deadline:
            try:
                title = driver.title or ""
                ready = driver.execute_script("return document.readyState") or ""
                body = driver.execute_script(
                    "return document.body ? document.body.innerText.slice(0, 1200) : ''"
                ) or ""
            except WebDriverException:
                time.sleep(0.5)
                continue
            haystack = f"{title}\n{body}".lower()
            if "проверка безопасности" in haystack or "подтвердите, что запросы" in haystack:
                challenge_seen = True
                time.sleep(2.0)
                continue
            if any(marker in haystack for marker in BLOCK_MARKERS):
                logger.warning("Авито вернул блокировку: %s", title[:120])
                return False
            if ready in ("interactive", "complete") and body.strip():
                try:
                    if driver.find_elements(By.CSS_SELECTOR, selector):
                        time.sleep(0.5)
                        return True
                except WebDriverException:
                    pass
            time.sleep(0.5)

        logger.info("Страница %s не отдала селектор %s за %.0f сек%s",
                    url, selector, self.render_timeout,
                    " (был челлендж)" if challenge_seen else "")
        return False

    def _remember_cookies(self, driver: webdriver.Chrome) -> None:
        self._cookies = {c["name"]: c["value"] for c in driver.get_cookies()}

    # ------------------------------------------------------------------
    # выдача
    # ------------------------------------------------------------------
    def fetch_listing(self, url: str) -> list[dict[str, Any]]:
        driver = self._driver()
        try:
            self._open(driver, url, LISTING_SELECTOR)
            payload = driver.execute_script(LISTING_JS) or {}
            title = str(payload.get("title") or driver.title or "")
            body = str(payload.get("body") or "")
            if _is_blocked(title, body):
                raise AvitoBlocked("Авито вернул проверку безопасности или блокировку. "
                                   "Попробуйте позже или смените IP.")
            items = payload.get("items") or []
            result: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in items:
                href = str(item.get("href") or "").strip()
                avito_id = extract_ad_id(href)
                if not href or not avito_id or avito_id in seen:
                    continue
                seen.add(avito_id)
                result.append({
                    "avito_id": avito_id,
                    "url": href,
                    "title": str(item.get("title") or "").strip(),
                    "price_text": str(item.get("price") or "").strip(),
                    "price_rub": parse_price(item.get("price")),
                    "location": str(item.get("location") or "").strip(),
                    "card_image": str(item.get("image") or "").strip(),
                    "listing_position": int(item.get("position") or 0),
                })
            logger.info("Выдача %s: карточек %d, объявлений %d", url, len(items), len(result))
            return result
        except WebDriverException as exc:
            raise AvitoError(f"Браузер не смог открыть страницу: {str(exc).splitlines()[0]}") from exc
        finally:
            driver.quit()

    # ------------------------------------------------------------------
    # объявление
    # ------------------------------------------------------------------
    def fetch_detail(self, url: str) -> dict[str, Any]:
        driver = self._driver()
        try:
            loaded = self._open(driver, url, "h1")
            payload = driver.execute_script(DETAIL_JS) or {}
            title = str(payload.get("title") or driver.title or "")
            body = str(payload.get("body") or "")
            if _is_blocked(title, body):
                raise AvitoBlocked("Авито вернул проверку безопасности или блокировку. "
                                   "Попробуйте позже или смените IP.")
            if not loaded:
                raise AvitoError("Не удалось дождаться загрузки страницы объявления. "
                                 "Авито не отдал карточку за отведённое время.")
            self._remember_cookies(driver)
            images = [str(src).strip() for src in (payload.get("images") or []) if str(src).strip()]
            return {
                "title": str(payload.get("title") or "").strip(),
                "price_text": str(payload.get("price") or "").strip(),
                "price_rub": parse_price(payload.get("price")),
                "description": str(payload.get("description") or "").strip(),
                "location": str(payload.get("location") or "").strip(),
                "images": images,
                "title_tag": str(payload.get("title_tag") or ""),
            }
        except WebDriverException as exc:
            raise AvitoError(f"Браузер не смог открыть объявление: {str(exc).splitlines()[0]}") from exc
        finally:
            driver.quit()

    # ------------------------------------------------------------------
    # фото
    # ------------------------------------------------------------------
    def download_photos(self, urls: Iterable[str]) -> list[PhotoPayload]:
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "image/avif,image/webp,image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5",
            "Accept-Language": "ru-RU,ru;q=0.9",
            "Referer": "https://www.avito.ru/",
        })
        if self._cookies:
            session.cookies.update(self._cookies)
        if self.proxy:
            session.proxies.update({"http": self.proxy.requests_url, "https": self.proxy.requests_url})
            if not self.verify_tls:
                session.verify = False
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        result: list[PhotoPayload] = []
        seen: set[str] = set()
        position = 0
        for raw in urls:
            url = str(raw or "").strip()
            if not url:
                continue
            if url.startswith("//"):
                url = "https:" + url
            if not url.startswith("http") or url in seen:
                continue
            seen.add(url)
            try:
                response = session.get(url, timeout=settings.AVITO_PHOTO_TIMEOUT)
            except requests.RequestException as exc:
                logger.warning("Фото не скачано (%s): %s", url[:120], exc)
                continue
            if response.status_code != 200:
                logger.warning("Фото %s: HTTP %s", url[:120], response.status_code)
                continue
            if len(response.content) > settings.PHOTO_MAX_BYTES:
                logger.warning("Фото %s слишком большое: %d байт", url[:120], len(response.content))
                continue
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                logger.warning("Фото %s: не картинка (%s)", url[:120], content_type)
                continue
            body, content_type, filename = self._normalize_photo(response.content, content_type)
            if not body:
                continue
            position += 1
            result.append(PhotoPayload(
                position=position,
                url=url,
                content=body,
                content_type=content_type,
                filename=filename,
                sha256=hashlib.sha256(body).hexdigest(),
            ))
        logger.info("Скачано фото: %d", len(result))
        return result

    @staticmethod
    def _normalize_photo(body: bytes, content_type: str) -> tuple[bytes, str, str]:
        """VK надёжно принимает JPEG; webp/avif переводим в JPEG при необходимости."""
        if content_type in ("image/jpeg", "image/jpg", "image/png"):
            ext = ".png" if content_type == "image/png" else ".jpg"
            return body, content_type, f"photo{ext}"
        try:
            image = Image.open(io.BytesIO(body))
            image.load()
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=92)
            return out.getvalue(), "image/jpeg", "photo.jpg"
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            logger.warning("Не удалось распознать изображение: %s", exc)
            return b"", content_type, ""
