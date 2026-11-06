"""Публикация объявлений в сообщество ВКонтакте по API (ТЗ, п.3.3).

Пост с фотографией собирается в четыре шага (официальный флоу VK):
  1. photos.getWallUploadServer(group_id) — получить адрес временного сервера;
  2. POST файлов на upload_url (multipart, поле file1) — получить photo/server/hash;
  3. photos.saveWallPhoto(...) — зафиксировать фото и получить attachment `photo<owner>_<id>`;
  4. wall.post(owner_id=-group_id, from_group=1, message, attachments) — сама запись на стене.

Отдельно проработаны «взрослые» ситуации: флуд-контроль VK (коды 6/9/29), капча (14),
дубликаты изображений (107), спам-ограничения стены (104/510/901/902) и троттлинг
по времени между постами (ТЗ: не чаще одного объявления в 3-5 минут).
"""

from __future__ import annotations

import mimetypes
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from .browser import ProxySettings
from .config import Config, VkConfig
from .database import Database
from .logger import get_logger
from .photos import PhotoDownloader

logger = get_logger("avito.vk")

# тексты подсказок по кодам ошибок VK: без них «error_code: 7» ничего не говорит
ERROR_HINTS = {
    5: "ключ сообщества недействителен или истёк — создайте новый в Настройки → Работа с API",
    6: "слишком частые запросы — увеличьте VK_POST_MIN_INTERVAL_SEC",
    7: "недостаточно прав: у ключа должны быть включены «Стена» и «Фотографии», "
       "а участник — быть администратором/редактором сообщества",
    9: "задержка флуд-контроля на секунду — повторяем автоматически",
    14: "ВКонтакте запросил капчу — нужно дождаться или решить её вручную",
    15: "доступ к объекту закрыт настройками приватности",
    29: "превышен лимит запросов — пауза и повтор",
    100: "некорректные параметры запроса",
    102: "текст поста отклонён модерацией ВК (запрещённые слова)",
    103: "ссылка в посте запрещена",
    104: "превышен суточный лимит постов в сообществе",
    107: "такое фото уже загружено — пропускаем снимок",
    123: "слишком много изображений в запросе",
    204: "нельзя редактировать запись, опубликованную другим приложением",
    205: "у пользователя нет прав на это действие",
    236: "слишком много постов за день",
    300: "одно или несколько переданных значений некорректны",
    310: "отсутствует обязательный параметр",
    312: "изображение недопустимого формата",
    313: "недостаточно прав для загрузки фото в этот альбом",
    340: "слишком длинный текст поста",
    510: "превышен лимит записей на стене",
    720: "запись нельзя изменить (она закреплена или опубликована давно)",
    901: "пост заблокирован анти-спам системой сообщества",
    902: "пользователь ограничен спам-фильтром — постинг временно заблокирован",
}

# ошибки, после которых бессмысленно продолжать пачку: стена закрыта/лимиты
FATAL_CODES = {102, 103, 104, 205, 236, 510, 901, 902}


class VkError(Exception):
    """Ошибка VK API с кодом и человеческой подсказкой."""

    def __init__(self, message: str, code: int = 0, response: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.response = response or {}

    @property
    def hint(self) -> str:
        return ERROR_HINTS.get(self.code, "")

    def __str__(self) -> str:
        base = self.message if not self.code else f"[{self.code}] {self.message}"
        return f"{base} — {self.hint}" if self.hint else base


class VkCaptchaRequired(VkError):
    """VK потребовал капчу: нужно решение, автоматически его не принять."""

    def __init__(self, message: str, captcha_sid: str, captcha_img: str, code: int = 14):
        super().__init__(message, code)
        self.captcha_sid = captcha_sid
        self.captcha_img = captcha_img


class VkPublishLimit(VkError):
    """Стена закрыта спам-фильтром или исчерпаны лимиты постов."""


@dataclass
class PostResult:
    """Итог публикации одного объявления."""

    avito_id: str
    ok: bool
    post_id: str = ""
    post_url: str = ""
    message: str = ""
    attachments: list[str] = field(default_factory=list)
    error: str = ""
    skipped: str = ""
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "avito_id": self.avito_id,
            "ok": self.ok,
            "dry_run": self.dry_run,
            "post_id": self.post_id,
            "post_url": self.post_url,
            "attachments": self.attachments,
            "error": self.error,
            "skipped": self.skipped,
        }


class VKPublisher:
    """Клиент публикаций: дедупликация через БД, троттлинг, обработка ошибок API."""

    def __init__(self, config: Config | None = None, db: Database | None = None):
        self.config = config or Config.load()
        self.vk = self.config.vk
        self.db = db
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
            "Accept": "application/json",
            "Accept-Language": "ru-RU,ru;q=0.9",
        })
        self._proxy = ProxySettings.parse(self.vk.proxy_string) if self.vk.proxy_string else None
        if self._proxy:
            url = self._proxy.requests_url
            self.session.proxies.update({"http": url, "https": url})
            logger.info("Запросы к VK идут через прокси %s", self._proxy)
        self._group_id: int | None = self.vk.group_number()
        self._group_info: dict[str, Any] = {}
        self._upload_server: dict[str, Any] = {}
        self._last_post_at: float = 0.0

    # ------------------------------------------------------------------ #
    # низкоуровневый вызов API
    # ------------------------------------------------------------------ #
    def _call(self, method: str, *, timeout: float | None = None,
              retries: int = 3, **params) -> Any:
        """POST к api.vk.com с разбором ошибок и повтором при флуд-контроле.

        Загрузку фото на временный сервер VK этот метод не обслуживает: там другой
        ответ и не нужны access_token/v в теле запроса (см. upload_photo).
        """
        if not self.vk.access_token:
            raise VkError("VK_ACCESS_TOKEN не задан — добавьте ключ сообщества в .env", code=0)

        payload = {k: v for k, v in params.items() if v is not None and v != ""}
        payload["access_token"] = self.vk.access_token
        payload["v"] = self.vk.api_version
        url = f"{self.vk.api_base}/{method}"

        last_error: VkError | None = None
        for attempt in range(1, retries + 1):
            try:
                response = self.session.post(url, data=payload,
                                             timeout=timeout or self.vk.request_timeout)
            except requests.RequestException as exc:
                wait = 2.0 * attempt
                logger.warning("Сеть при вызове %s (попытка %d): %s — пауза %.0f сек",
                               method, attempt, str(exc)[:120], wait)
                time.sleep(wait)
                continue

            try:
                data = response.json()
            except ValueError:
                raise VkError(f"VK вернул не JSON (HTTP {response.status_code}): "
                              f"{response.text[:200]}", code=0) from None

            if not isinstance(data, dict):
                # api.vk.com отвечает объектом; если пришёл массив/строка — не падаем на .get
                return data

            if "error" not in data:
                return data.get("response", data)

            error = data["error"]
            if not isinstance(error, dict):
                raise VkError(str(error)[:200], code=0, response=data)
            code = int(error.get("error_code") or 0)
            message = str(error.get("error_msg") or "unknown error")
            details = error.get("error_data")
            details = details if isinstance(details, dict) else {}
            last_error = VkError(message, code=code, response=data)

            if code == 14:
                raise VkCaptchaRequired(message, str(details.get("captcha_sid", "")),
                                       str(details.get("captcha_img", "")))
            if code in FATAL_CODES:
                raise VkPublishLimit(message, code=code, response=data)
            if code in (6, 9, 29) and attempt < retries:
                delay = float(details.get("delay") or 0) or (2.0 * attempt + random.uniform(0, 2))
                logger.warning("Флуд-контроль VK (%s, код %d) — жду %.0f сек", message, code, delay)
                time.sleep(delay)
                continue
            raise last_error

        raise last_error or VkError(f"VK API: {method} не отвечен за {retries} попыток")

    # ------------------------------------------------------------------ #
    # сообщество
    # ------------------------------------------------------------------ #
    def resolve_group(self, refresh: bool = False) -> dict[str, Any]:
        """Проверить ключ и получить данные сообщества (id, название, адрес).

        groups.get недоступен ключам сообщества (ошибка 27), поэтому данные
        берём через groups.getById — он принимает и числовой id, и короткий адрес.
        """
        if self._group_info and not refresh:
            return self._group_info
        if not self.vk.group_id:
            raise VkError("VK_GROUP_ID не задан — укажите id или короткий адрес сообщества")

        try:
            info = self._call("groups.getById", group_id=self.vk.group_id.lstrip("-"), fields="screen_name")
            # ключ сообщества отдаёт {"groups": [...]}, ключ пользователя — {"count", "items"}
            if isinstance(info, list):
                info = next((g for g in info if isinstance(g, dict)), {})
            if not isinstance(info, dict):
                info = {}
            data = info.get("groups") or info.get("items") or []
            if data and isinstance(data, list):
                info = next((g for g in data if isinstance(g, dict)), info)
        except VkError as exc:
            # токен сообщества не может читать группы напрямую — парсим локально
            if "27" in str(exc) or "Group authorization" in str(exc):
                raw = self.vk.group_id.lstrip("-").replace("public", "").replace("club", "")
                if not raw.isdigit():
                    raise VkError(
                        f"Не удалось определить id сообщества из «{self.vk.group_id}». "
                        "Укажите числовой id (например, -129804058) в VK_GROUP_ID"
                    ) from exc
                logger.info("Групповая авторизация: id сообщества распознан как %s", raw)
                self._group_id = int(raw)
                self._group_info = {
                    "group_id": self._group_id,
                    "name": f"сообщество {raw}",
                    "screen_name": self.vk.group_id.lstrip("-"),
                    "is_admin": None,
                    "member": None,
                }
                return self._group_info
            raise

        group_id = int(info.get("id") or self._group_id or 0)
        if not group_id:
            raise VkError(f"Сообщество {self.vk.group_id} не найдено по этому ключу")
        # публикация возможна только от имени сообщества: id на стене всегда отрицательный
        self._group_id = group_id
        self._group_info = {
            "group_id": group_id,
            "name": info.get("name", ""),
            "screen_name": info.get("screen_name", ""),
            "is_admin": bool(info.get("is_admin")),
            "member": bool(info.get("member")),
        }
        logger.info("Сообщество: «%s» (id %d, %s), прав админа: %s",
                    self._group_info["name"], group_id,
                    "vk.com/" + self._group_info["screen_name"], self._group_info["is_admin"])
        # поле is_admin есть не у всех типов ключей — ругаемся только когда оно явно ложное
        if "is_admin" in info and not self._group_info["is_admin"]:
            logger.warning("Ключ выдан участнику без прав администратора — wall.post может быть закрыт (код 7/205)")
        return self._group_info

    @property
    def owner_id(self) -> int:
        if not self._group_id:
            self.resolve_group()
        return -(self._group_id or 0)

    def wall_url(self, post_id: str | int) -> str:
        """Постоянная ссылка на запись: wall-<id группы>_<id поста>."""
        # user-ключ может вернуть post_id уже в форме «-<gid>_<pid>» — берём номер поста
        text = str(post_id)
        if "_" in text:
            text = text.split("_", 1)[-1]
        return f"https://vk.com/wall-{self._group_id}_{text}"

    # ------------------------------------------------------------------ #
    # фотографии
    # ------------------------------------------------------------------ #
    def _get_upload_server(self, force: bool = False) -> dict[str, Any]:
        """Получить (и переиспользовать) адрес сервера загрузки фото на стену."""
        if self._upload_server and not force:
            return self._upload_server
        self.resolve_group()
        try:
            server = self._call("photos.getWallUploadServer", group_id=self._group_id)
        except VkError as exc:
            if "27" in str(exc) or "Group authorization" in str(exc):
                raise VkError(
                    "VK запрещает загрузку фото ключам сообщества (код 27) — даже со "
                    "включённым скоупом «Фотографии». Загрузите фото можно только "
                    "user-ключом: создайте standalone-приложение (id.app в VK ID) и "
                    "выдайте user-ключ с правами photos, wall, groups, offline, затем "
                    "укажите его в админке (Настройки → VK: ключ доступа)."
                ) from exc
            raise
        if not isinstance(server, dict) or not server.get("upload_url"):
            raise VkError(f"VK не вернул upload_url: {server}")
        self._upload_server = server
        return server

    @staticmethod
    def _parse_upload_items(data: Any) -> list[dict[str, Any]]:
        """Сервер загрузки отвечает то плоским объектом, то списком — приводим к одному виду."""
        if isinstance(data, list):
            return [i for i in data if isinstance(i, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("images", "photos"):
            items = data.get(key)
            if isinstance(items, list):
                return [i for i in items if isinstance(i, dict)]
        if data.get("photo") or data.get("pid"):
            return [data]
        return []

    @staticmethod
    def _upload_error(data: Any) -> tuple[int, str]:
        """Достать код ошибки из ответа временного сервера.

        api.vk.com оборачивает ошибку в поле `error`, а upload.php отдаёт её
        плоским словарём (`{"error_code":107,"error_msg":...}`) — учитываем оба.
        """
        if not isinstance(data, dict):
            return 0, ""
        error = data.get("error")
        if isinstance(error, dict):
            return int(error.get("error_code") or 0), str(error.get("error_msg") or "")
        if error:
            return 0, str(error)
        if "error_code" in data or "error_msg" in data:
            return int(data.get("error_code") or 0), str(data.get("error_msg") or "")
        return 0, ""

    @staticmethod
    def _saved_photos(saved: Any) -> list[dict[str, Any]]:
        """Привести ответ photos.saveWallPhoto к списку снимков.

        Варианты ответа VK: массив фото (user-ключ), объект с `items`/`photos`
        (ключ сообщества / новый формат), плоский снимок со старыми `pid`/`photo`/
        `hash`, а также завёрнутый `{"photo": {...}}`.
        """
        if isinstance(saved, list):
            raw: list[Any] = saved
        elif isinstance(saved, dict):
            items = saved.get("items") or saved.get("photos")
            raw = list(items) if isinstance(items, list) else [saved]
        else:
            raw = []
        photos: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            inner = item.get("photo")
            # старый формат: `photo` — строка-ссылка, новый: вложенный объект снимка
            photo = inner if isinstance(inner, dict) else item
            if photo.get("id") or photo.get("pid"):
                photos.append(photo)
        return photos

    def upload_photo(self, path: Path | str) -> str:
        """Загрузить один файл и вернуть attachment вида `photo<owner_id>_<id>`."""
        path = Path(path)
        if not path.is_file():
            raise VkError(f"Файл не найден: {path}")
        size = path.stat().st_size
        if size == 0:
            raise VkError(f"Файл пустой: {path}")
        if size > 50 * 1024 * 1024:
            raise VkError(f"Файл больше 50 МБ: {path}")

        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        last_error: Exception | None = None
        for attempt in (1, 2):
            server = self._get_upload_server(force=attempt > 1)
            try:
                with path.open("rb") as handle:
                    raw = self.session.post(
                        server["upload_url"],
                        files={"file1": (path.name, handle, mime)},
                        timeout=self.vk.upload_timeout,
                    )
                data = raw.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                logger.warning("Загрузка %s сорвалась (попытка %d): %s", path.name, attempt, str(exc)[:120])
                continue

            code, message = self._upload_error(data)
            if code == 107:
                # VK не принимает повторно один и тот же снимок: это не повод ронять пост
                logger.info("VK отклонил дубль фото %s — пропускаю снимок", path.name)
                return ""
            if code or message:
                error = VkError(message or str(data)[:200], code=code, response=data)
                if code in (100, 123, 310, 311, 312):
                    # проблема в самом файле: новая попытка с другим сервером её не решит
                    raise error
                last_error = error
                logger.warning("Загрузка %s отклонена (попытка %d): %s", path.name, attempt, error)
                continue

            items = self._parse_upload_items(data)
            if not items:
                last_error = VkError(f"Сервер загрузки вернул непонятный ответ: {str(data)[:200]}")
                logger.warning("Ответ загрузки без photo/hash: %s", str(data)[:160])
                continue

            saved = self._call(
                "photos.saveWallPhoto",
                group_id=self._group_id,
                photo=items[0].get("photo"),
                server=items[0].get("server"),
                hash=items[0].get("hash"),
            )
            photos = self._saved_photos(saved)
            if not photos:
                raise VkError(f"photos.saveWallPhoto не вернул снимок: {str(saved)[:200]}")
            photo = photos[0]
            photo_id = photo.get("id") or photo.get("pid")
            # в старом формате owner_id отсутствует: снимок лежит на стене сообщества,
            # куда его отдавал getWallUploadServer(group_id=...)
            owner_id = photo.get("owner_id") or (-(self._group_id or 0))
            if not photo_id or not owner_id:
                raise VkError(f"photos.saveWallPhoto вернул снимок без id/owner_id: {str(photo)[:200]}")
            attachment = f"photo{owner_id}_{photo_id}"
            # сбрасываем кэш сервера: upload_url одноразовый по факту
            self._upload_server = {}
            return attachment

        raise VkError(f"Не удалось загрузить фото {path.name}: {last_error}")

    def _photo_paths(self, ad: dict[str, Any], allow_download: bool = True) -> list[Path]:
        """Локальные файлы фотографий объявления; при необходимости докачиваем с Авито."""
        files = [Path(p) for p in (ad.get("photo_files") or []) if Path(str(p)).is_file()]
        if files or not allow_download:
            return files
        if not self.vk.download_missing_photos:
            return []
        urls = ad.get("images") or []
        if not urls:
            return []
        downloader = PhotoDownloader(
            self.config.parser,
            user_agent=self.session.headers.get("User-Agent", ""),
            proxy=self._proxy,
        )
        dest = Path(self.config.parser.photos_dir) / str(ad.get("avito_id") or "unknown")
        files = downloader.download(urls, dest, max_photos=self.vk.max_photos_per_post,
                                    ad_id=str(ad.get("avito_id") or ""))
        logger.info("Докачал %d фото для %s", len(files), ad.get("avito_id"))
        return list(files)

    def collect_photos(self, ad: dict[str, Any], allow_download: bool = True) -> list[Path]:
        """Локальные фото объявления (публичный доступ для CLI/UI)."""
        return self._photo_paths(ad, allow_download=allow_download)[: self.vk.max_photos_per_post]

    def build_attachments(self, ad: dict[str, Any]) -> list[str]:
        """Загрузить фото объявления и собрать список attachment для wall.post."""
        paths = self._photo_paths(ad)[: self.vk.max_photos_per_post]
        if not paths:
            return []
        attachments: list[str] = []
        for path in paths:
            try:
                attachment = self.upload_photo(path)
            except VkError as exc:
                logger.warning("Фото %s не загружено: %s", path.name, exc)
                continue
            if attachment:
                attachments.append(attachment)
        return attachments

    # ------------------------------------------------------------------ #
    # текст поста
    # ------------------------------------------------------------------ #
    def build_message(self, ad: dict[str, Any]) -> str:
        """Собрать текст поста по шаблону из VK_POST_TEMPLATE."""
        description = " ".join(str(ad.get("description") or "").split())
        if self.vk.max_description and len(description) > self.vk.max_description:
            cut = description[: self.vk.max_description]
            cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
            description = cut + "…"

        price_raw = str(ad.get("price") or "").strip()
        price_rub = ad.get("price_rub")
        if not price_raw and price_rub:
            price_raw = f"{price_rub:,} руб.".replace(",", " ")
        price = "Договорная" if not price_raw or price_raw.lower() in ("0", "бесплатно") else price_raw

        values = {
            "title": str(ad.get("title") or "Объявление на Авито").strip(),
            "price": price,
            "price_rub": str(price_rub or ""),
            "description": description or "Описание не указано на Авито.",
            "url": str(ad.get("url") or ""),
            "location": str(ad.get("location") or "").strip(),
            "id": str(ad.get("avito_id") or ""),
            "date": (str(ad.get("parsed_at") or "")[:10]),
        }
        template = self.vk.template or "{title}\n{price}\n\n{url}"
        try:
            text = template.format_map(dict(values))
        except KeyError as exc:
            logger.warning("В шаблоне неизвестный плейсхолдер %s — пробую базовый", exc)
            text = "{title}\n{price}\n\n{url}".format_map(values)

        if values["url"] and values["url"] not in text:
            text = text.rstrip() + f"\n\n{values['url']}"
        if self.vk.hashtags:
            text = text.rstrip() + "\n\n" + self.vk.hashtags.strip()

        # VK не принимает пустой message вместе с attachments, да и в ленте такой пост мёртвый
        text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
        if not text:
            text = values["url"] or values["title"]
        if self.vk.max_message_length and len(text) > self.vk.max_message_length:
            text = text[: self.vk.max_message_length].rsplit("\n", 1)[0]
        return text

    # ------------------------------------------------------------------ #
    # публикация
    # ------------------------------------------------------------------ #
    def wait_interval(self) -> None:
        """Выдержать паузу между постами (ТЗ: 3-5 минут) с небольшим разбросом."""
        if not self._last_post_at or not self.vk.min_interval_sec:
            return
        elapsed = time.time() - self._last_post_at
        need = self.vk.min_interval_sec * random.uniform(1.0, 1.25) - elapsed
        if need > 0:
            logger.info("Пауза перед следующим постом: %.0f сек", need)
            time.sleep(need)

    def post_ad(self, ad: dict[str, Any], dry_run: bool = False,
                with_photos: bool | None = None) -> PostResult:
        """Один пост: фото → текст → wall.post → отметка в базе.

        dry_run ничего не отправляет, только собирает и возвращает текст поста.
        """
        avito_id = str(ad.get("avito_id") or "")
        with_photos = True if with_photos is None else with_photos
        message = self.build_message(ad)
        result = PostResult(avito_id=avito_id, ok=False, message=message)

        if dry_run:
            # предпросмотр не должен создавать сетевой трафик к Авито и VK
            paths = (self._photo_paths(ad, allow_download=False)[: self.vk.max_photos_per_post]
                     if with_photos else [])
            result.ok = True
            result.dry_run = True
            result.attachments = [f"file:{p.name}" for p in paths]
            if not paths and self.vk.require_photos:
                result.skipped = "фото не загружены — с VK_REQUIRE_PHOTOS такой пост не уйдёт"
            logger.info("DRY-RUN пост для %s: %d фото, %d знаков", avito_id, len(paths), len(message))
            return result

        self.resolve_group()
        attachments = self.build_attachments(ad) if with_photos else []
        if not attachments and self.vk.require_photos:
            result.skipped = "нет загруженных фотографий (VK_REQUIRE_PHOTOS=True)"
            logger.warning("Пост %s пропущен: %s", avito_id, result.skipped)
            return result

        self.wait_interval()
        try:
            response = self._call(
                "wall.post",
                owner_id=self.owner_id,
                from_group=1,
                message=message,
                attachments=",".join(attachments) or None,
                disable_comments=1 if self.vk.disable_comments else None,
            )
        except VkError as exc:
            # VK считает полностью совпадающий текст дублем (код 1002) —
            # спасает только любое отличие, например id объявления в конце
            if exc.code != 1002:
                raise
            logger.info("VK отклонил пост как дубликат — повторяю с меткой объявления")
            message = message + f"\n\n(объявление №{avito_id})"
            response = self._call(
                "wall.post",
                owner_id=self.owner_id,
                from_group=1,
                message=message,
                attachments=",".join(attachments) or None,
                disable_comments=1 if self.vk.disable_comments else None,
            )
        result.message = message
        post_id = str(response.get("post_id") or "") if isinstance(response, dict) else ""
        result.ok = bool(post_id)
        result.post_id = post_id
        result.attachments = attachments
        result.post_url = self.wall_url(post_id) if post_id else ""
        self._last_post_at = time.time()

        if result.ok:
            logger.info("Опубликован пост %s → %s (%d фото)", avito_id, result.post_url, len(attachments))
            if self.db:
                self.db.mark_posted(avito_id, True, post_id=post_id, post_url=result.post_url)
                ad["posted_to_vk"] = 1
        else:
            result.error = f"VK не вернул post_id: {response}"
        return result

    def publish_pending(self, limit: int | None = None, dry_run: bool = False,
                        on_progress: Callable[[str], None] | None = None,
                        on_result: Callable[[PostResult], None] | None = None) -> list[PostResult]:
        """Опубликовать все неопубликованные объявления из базы (по одному за проход)."""
        report = on_progress or (lambda message: None)
        if not self.db:
            raise VkError("Для пакетной публикации нужен Database (save_to_db)")

        ads = self.db.get_unposted(limit=limit)
        if not ads:
            report("Неопубликованных объявлений нет")
            logger.info("Очередь публикации пуста")
            return []
        report(f"К публикации: {len(ads)} шт.")
        logger.info("Начинаю публикацию %d объявлений (сухой прогон: %s)", len(ads), dry_run)

        results: list[PostResult] = []
        for index, ad in enumerate(ads, 1):
            title = str(ad.get("title") or "")[:60]
            try:
                result = self.post_ad(ad, dry_run=dry_run)
            except VkPublishLimit as exc:
                logger.error("Постинг остановлен: %s", exc)
                report(f"Стоп: {exc}")
                results.append(PostResult(avito_id=str(ad.get("avito_id")), ok=False, error=str(exc)))
                break
            except VkCaptchaRequired as exc:
                logger.error("Нужна капча: %s (сид %s)", exc.captcha_img, exc.captcha_sid)
                results.append(PostResult(avito_id=str(ad.get("avito_id")), ok=False, error=str(exc)))
                break
            except VkError as exc:
                logger.error("Пост %s не опубликован: %s", ad.get("avito_id"), exc)
                results.append(PostResult(avito_id=str(ad.get("avito_id")), ok=False, error=str(exc)))
                continue

            results.append(result)
            if on_result:
                on_result(result)
            status = "готово" if result.ok else (result.skipped or result.error)
            report(f"{index}/{len(ads)}: {title} — {status}")
        return results

    # ------------------------------------------------------------------ #
    # служебное
    # ------------------------------------------------------------------ #
    def delete_post(self, post_id: str | int) -> bool:
        """Удалить запись (нужен для отладочных постов)."""
        self.resolve_group()
        response = self._call("posts.delete", owner_id=self.owner_id, post_id=post_id)
        return bool(response)

    def publish_text(self, text: str, photo_paths: list[Path | str] | None = None) -> PostResult:
        """Тестовый/служебный пост с произвольным текстом."""
        self.resolve_group()
        attachments = []
        for path in (photo_paths or []):
            attachment = self.upload_photo(path)
            if attachment:
                attachments.append(attachment)
        response = self._call("wall.post", owner_id=self.owner_id, from_group=1,
                              message=text, attachments=",".join(attachments) or None)
        post_id = str(response.get("post_id") or "") if isinstance(response, dict) else ""
        return PostResult(avito_id="", ok=bool(post_id), post_id=post_id,
                          post_url=self.wall_url(post_id) if post_id else "",
                          message=text, attachments=attachments)

    def status(self) -> dict[str, Any]:
        """Короткая сводка для UI: настроен ли канал и что в очереди."""
        info: dict[str, Any] = {
            "token_set": bool(self.vk.access_token),
            "group_set": bool(self.vk.group_id),
            "group_id": self._group_id,
            "group_name": self._group_info.get("name", ""),
            "wall": "",
            "min_interval_sec": self.vk.min_interval_sec,
            "require_photos": self.vk.require_photos,
            "template": self.vk.template,
            "pending": None,
            "posted": None,
            "last_post_at": None,
            "error": "",
        }
        if self._group_info.get("screen_name"):
            info["wall"] = f"https://vk.com/{self._group_info['screen_name']}"
        if self.db:
            stats = self.db.stats()
            info["pending"] = stats.get("pending")
            info["posted"] = stats.get("posted")
            last = self.db.last_posted()
            if last:
                info["last_post_at"] = last.get("posted_at")
                info["last_post_url"] = last.get("vk_post_url")
        if not info["token_set"]:
            info["error"] = "VK_ACCESS_TOKEN не задан"
        elif not info["group_set"]:
            info["error"] = "VK_GROUP_ID не задан"
        return info

    def close(self) -> None:
        # сессию подменяют тесты и планировщик — не падаем, если у неё нет close()
        closer = getattr(self.session, "close", None)
        if callable(closer):
            closer()

    def __enter__(self) -> "VKPublisher":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
