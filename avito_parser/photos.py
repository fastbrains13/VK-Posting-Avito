"""Скачивание фотографий объявления во временную директорию (ТЗ, п.3.1).

Запросы идут той же сессией и с теми же куки, что и браузер, чтобы не «светить»
отдельный HTTP-клиент перед антиботом Авито.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable

import requests

from .config import ParserConfig
from .logger import get_logger

logger = get_logger("avito.photos")

_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}

# Ссылки вида .../image/1/xxx?cqp=... → приводим к одному виду для дедупликации
_TRACKING_QUERY = re.compile(r"\?(cqp|width|height|resize|static)\b.*$", re.I)
# «Обрезка» URL, вынутых регуляркой из HTML: всё после первой кавычки/скобки — мусор
_URL_DELIMITERS = ('"', "'", "<", ">", "(", ")", chr(92), chr(9), chr(10), chr(13), " ")


class PhotoDownloader:
    """Скачивает от N первых фотографий объявления (ТЗ: 1..5, настраиваемо)."""

    def __init__(self, config: ParserConfig | None = None, cookies: dict[str, str] | None = None,
                 user_agent: str = "", proxy=None, verify_tls: bool = True):
        self.config = config or ParserConfig()
        self.proxy = proxy
        self.verify_tls = verify_tls
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
            "Referer": "https://www.avito.ru/",
        })
        if cookies:
            self.session.cookies.update(cookies)
        if proxy is not None:
            url = proxy.requests_url
            self.session.proxies.update({"http": url, "https": url})
            if not verify_tls:
                # MITM на прокси: цепочка доверия ломается, но картинка всё равно наша
                self.session.verify = False
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ------------------------------------------------------------------ #
    @staticmethod
    def normalize(urls: Iterable[str]) -> list[str]:
        """Очистить и отфильтровать ссылки картинок, убрать дубликаты."""
        result: list[str] = []
        seen: set[str] = set()
        for raw in urls or []:
            if not raw:
                continue
            url = raw.strip()
            if url.startswith("//"):
                url = "https:" + url
            # режем хвосты, приклеившиеся при вытаскивании из HTML/JSON
            for delimiter in _URL_DELIMITERS:
                url = url.split(delimiter)[0]
            url = url.rstrip('.,;:)')
            if not url.startswith("http"):
                continue
            if any(token in url for token in ("logo", "sprite", ".svg", "favicon", "avatar", "placeholder")):
                continue
            # Авито раздаёт один и тот же файл с разных CDN-хостов (b00/c90/60...) — дедуплицим по пути
            key = _TRACKING_QUERY.sub("", url)
            key = "/".join(key.split("/")[3:]) if key.count("/") >= 3 else key
            if key in seen:
                continue
            seen.add(key)
            result.append(url)
        return result

    @staticmethod
    def upscale(url: str) -> str:
        """Попытка получить вариант фотографии побольше (Авито режет размер суффиксом)."""
        # .../image/1/hash → оставляем как есть: хеш подписан, суффиксы вида _c125x125 срезаем
        return re.sub(r"_(?:x1|c\d+x\d+|s\d+|small|medium|large|120x120|160x160|255x0|668x668|1000x1000)$", "", url)

    @staticmethod
    def to_jpeg(path: Path) -> Path:
        """Привести webp/avif к JPEG: стена VK стабильно принимает именно jpg/png."""
        if path.suffix.lower() not in (".webp", ".avif"):
            return path
        try:
            from PIL import Image
        except ImportError:
            logger.debug("Pillow не установлен — оставляю %s как есть", path.name)
            return path

        jpeg_path = path.with_suffix(".jpg")
        try:
            with Image.open(path) as image:
                image.convert("RGB").save(jpeg_path, "JPEG", quality=90)
            path.unlink(missing_ok=True)
            return jpeg_path
        except Exception as exc:  # битые данные картинки не должны ронять парсинг
            logger.debug("Не сконвертировал %s: %s", path.name, exc)
            return path

    @staticmethod
    def image_size(path: Path) -> tuple[int, int]:
        try:
            from PIL import Image

            with Image.open(path) as image:
                return image.size
        except Exception:
            return (0, 0)

    def save_bytes(self, body: bytes, dest: Path, content_type: str = "") -> Path | None:
        """Сохранить байты картинки с проверками и конвертом в JPEG."""
        if not body or len(body) < 3_000:  # заглушки/прозрачные пиксели
            return None
        if len(body) > 12_000_000:
            logger.debug("Слишком большой файл (%d КБ), пропускаем", len(body) // 1024)
            return None

        content_type = (content_type or "").split(";")[0].strip().lower()
        ext = _EXT_BY_MIME.get(content_type, ".jpg")
        path = dest.with_suffix(ext)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        except OSError as exc:
            logger.debug("Не удалось записать %s: %s", path, exc)
            return None

        path = self.to_jpeg(path)
        width, height = self.image_size(path)
        if (width < 320 or height < 240) and ext != ".jpg":
            # jpg без Pillow может не дать размеров — в этом случае доверяем файлу
            logger.debug("Слишком маленькое фото %dx%d — удаляю", width, height)
            path.unlink(missing_ok=True)
            return None
        logger.debug("Сохранено фото: %s (%d КБ, %dx%d)", path.name, path.stat().st_size // 1024, width, height)
        return path

    # ------------------------------------------------------------------ #
    def download(self, urls: list[str], dest_dir: Path | str, max_photos: int | None = None,
                 ad_id: str | int = "", bodies: dict[str, bytes] | None = None) -> list[Path]:
        """Скачать до `max_photos` файлов. Возвращает список сохранённых путей.

        `bodies` — байты, уже загруженные браузером (через CDP): при работе через
        SOCKS-прокси с перехватом TLS прямой requests-запрос к CDN не проходит,
        поэтому в приоритете они.
        """
        limit = max(1, max_photos if max_photos is not None else self.config.max_photos)
        candidates = self.normalize(urls)[: limit * 2]  # запас на «битые» ссылки
        if not candidates:
            logger.debug("Нет валидных ссылок на фото для %s", ad_id)
            return []

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        stamp = str(ad_id) or hashlib.md5(candidates[0].encode()).hexdigest()[:12]

        saved: list[Path] = []
        for url in candidates:
            if len(saved) >= limit:
                break
            path: Path | None = None

            body = self._match_body(bodies, url)
            if body:
                path = self.save_bytes(body, dest / f"{stamp}_{len(saved) + 1}", "image/jpeg")

            if path is None:
                path = self._fetch_via_http(url, dest, stamp, len(saved) + 1)

            if path:
                saved.append(path)

        logger.info("Скачано %d/%d фото для объявления %s", len(saved), limit, ad_id)
        return saved

    @staticmethod
    def _match_body(bodies: dict[str, bytes] | None, url: str) -> bytes | None:
        """Найти байты по URL с учётом того, что CDN-хост и query могут отличаться."""
        if not bodies:
            return None
        if url in bodies:
            return bodies[url]
        tail = "/".join(url.split("/")[3:]).split("?")[0]
        for candidate, body in bodies.items():
            if "/".join(candidate.split("/")[3:]).split("?")[0] == tail:
                return body
        return None

    def _fetch_via_http(self, url: str, dest: Path, stamp: str, index: int) -> Path | None:
        """Прямая загрузка через requests (работает без прокси/на прозрачных прокси)."""
        try:
            resp = self.session.get(self.upscale(url), timeout=20)
        except requests.RequestException as exc:
            logger.debug("Ошибка загрузки %s: %s", url, exc)
            return None

        if resp.status_code != 200:
            logger.debug("HTTP %s на %s", resp.status_code, url)
            return None
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            logger.debug("Не картинка (%s): %s", content_type, url)
            return None
        return self.save_bytes(resp.content, dest / f"{stamp}_{index}", content_type)

    def close(self) -> None:
        self.session.close()
