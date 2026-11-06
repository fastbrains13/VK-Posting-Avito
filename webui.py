#!/usr/bin/env python3
"""Веб-админка парсера Авито и постинга в сообщество VK.

Запуск:  python webui.py --host 0.0.0.0 --port 8000
Открыть: http://127.0.0.1:8000 (логин/пароль из ADMIN_USERNAME/ADMIN_PASSWORD)

Возможности:
  * вход по логину/паролю (cookie-сессия, HMAC-подпись);
  * крон: планировщик сам парсит источники каждые N минут и публикует
    очередь в VK раз в M минут (интервалы настраиваются в админке);
  * управление ссылками Авито: добавить / включить / выключить / удалить;
    новая ссылка в первый прогон парсится не более first_run_limit объявлений;
  * настройки VK: пауза между постами, require_photos, размер пачки;
  * ручные запуск парсинга и публикация очереди, живой лог задач.

Реализовано на stdlib http.server, чтобы не тянуть веб-фреймворк.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import io
import json
import secrets
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from avito_parser.config import Config, split_urls
from avito_parser.database import Database
from avito_parser.logger import get_logger, setup_logging
from avito_parser.scraper import AvitoScraper, source_label
from avito_parser.vk_publisher import VKPublisher, VkError
from avito_parser.browser import ProxySettings

ROOT = Path(__file__).resolve().parent
PHOTOS_ROOT = (ROOT / "data" / "photos").resolve()
MAX_DESCRIPTION = 600
SESSION_COOKIE = "avito_admin"
SESSION_TTL = 7 * 24 * 3600

logger = get_logger("avito.webui")


# --------------------------------------------------------------------- #
# авторизация
# --------------------------------------------------------------------- #
class AuthService:
    """Cookie-сессии с HMAC-подписью; пароль и секрет берутся из .env."""

    def __init__(self, config: Config):
        self.username = config.admin_username or "admin"
        self.password = config.admin_password or secrets.token_urlsafe(8)
        self.secret = config.admin_secret or secrets.token_hex(32)
        if not config.admin_password:
            logger.warning("ADMIN_PASSWORD не задан — сгенерирован временный: %s", self.password)

    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def issue(self, username: str) -> str:
        expires = int(time.time()) + SESSION_TTL
        payload = f"{username}:{expires}"
        return f"{payload}:{self._sign(payload)}"

    def verify(self, token: str | None) -> bool:
        if not token or token.count(":") < 2:
            return False
        username, expires, sign = token.rsplit(":", 2)
        payload = f"{username}:{expires}"
        if not hmac.compare_digest(sign, self._sign(payload)):
            return False
        try:
            return int(expires) > time.time()
        except ValueError:
            return False

    def check_login(self, username: str, password: str) -> bool:
        return (hmac.compare_digest(username, self.username)
                and hmac.compare_digest(password, self.password))


# --------------------------------------------------------------------- #
# страницы (HTML вынесен в webui_page.py)
# --------------------------------------------------------------------- #
from webui_page import LOGIN_PAGE, PAGE  # noqa: E402


# --------------------------------------------------------------------- #
# задачи (jobs) и сервисы
# --------------------------------------------------------------------- #
@dataclass
class Job:
    """Одна задача парсинга/постинга: статус, лог и результат для опроса из UI."""

    id: str
    params: dict
    status: str = "queued"
    progress: str = ""
    error: str = ""
    ads: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    posts: list = field(default_factory=list)
    log: list = field(default_factory=list)
    blocked: int = 0
    proxy_used: str = ""
    elapsed: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)


def post_payload(result) -> dict:
    """PostResult → то, что показывает форма."""
    return {
        "avito_id": result.avito_id,
        "ok": result.ok,
        "dry_run": result.dry_run,
        "post_id": result.post_id,
        "post_url": result.post_url,
        "photos": len(result.attachments),
        "chars": len(result.message or ""),
        "error": result.error,
        "skipped": result.skipped,
    }


def tail_traceback(depth: int = 5) -> str:
    """Хвост трейсбека для журнала задачи.

    limit=2 у format_exc показывал только кадры сервиса: настоящий источник
    ошибки (например, внутри vk_publisher) оставался за кадром.
    """
    exc_type, exc_value, tb = sys.exc_info()
    frames = traceback.extract_tb(tb)[-depth:] if tb is not None else []
    lines = ["Traceback (most recent call last):"]
    for frame in frames:
        lines.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n')
        lines.append(f"    {frame.line or ''}\n")
    if exc_type is not None:
        lines.extend(traceback.format_exception_only(exc_type, exc_value))
    return "".join(lines).rstrip()


class PublishService:
    """Постинг в сообщество VK: один клиент и одна очередь на все запросы."""

    def __init__(self, base_config: Config, db: Database | None = None):
        self.config = base_config
        self.db = db or Database(base_config.parser)
        self.publisher = VKPublisher(base_config, self.db)
        self.lock = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self._group_checked_at = 0.0
        self.apply_settings()

    def apply_settings(self) -> None:
        """Настройки из БД применяются к конфигу VK перед каждым запуском.

        Токен и сообщество можно сменить из админки: они переопределяют .env,
        пока в БД хранится непустое значение.
        """
        vk = self.config.vk
        token = self.db.setting_get("vk_access_token", "") or ""
        if token:
            vk.access_token = token
        group = self.db.setting_get("vk_group_id", "") or ""
        if group:
            vk.group_id = group
        vk.min_interval_sec = float(self.db.setting_int("vk_min_interval_sec", 240))
        vk.require_photos = self.db.setting_bool("vk_require_photos", False)

    def describe(self) -> dict:
        """Сводка канала для UI; сообщество подтверждается не чаще раза в 5 минут."""
        info = self.publisher.status()
        if info["token_set"] and info["group_set"] and time.time() - self._group_checked_at > 300:
            try:
                group = self.publisher.resolve_group(refresh=True)
                info["group_id"] = group["group_id"]
                info["group_name"] = group["name"]
                info["is_admin"] = group["is_admin"]
                if group.get("screen_name"):
                    info["wall"] = f"https://vk.com/{group['screen_name']}"
                self._group_checked_at = time.time()
            except VkError as exc:
                info["error"] = str(exc)
        return info

    def publish(self, job: Job, dry_run: bool, limit: int) -> None:
        """Пройтись по очереди неопубликованных и записать итог в job."""
        if not self.lock.acquire(blocking=False):
            raise VkError("Уже идёт публикация — VK требует паузу между постами")
        try:
            self.apply_settings()
            results = self.publisher.publish_pending(
                limit=limit,
                dry_run=dry_run,
                on_progress=lambda message: (setattr(job, "progress", message),
                                             job.log.append(message)),
                on_result=lambda result: job.posts.append(post_payload(result)),
            )
            published = sum(1 for r in results if r.ok)
            job.log.append(f"VK: {('собрано' if dry_run else 'опубликовано')} {published} из {len(results)}")
        finally:
            self.lock.release()

    def submit(self, params: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], params=params)
        self.jobs[job.id] = job
        self._prune()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def submit_one(self, avito_id: str, dry_run: bool = False) -> Job:
        """Пост одного объявления из админки."""
        return self.submit({"one": True, "avito_id": avito_id, "dry_run": dry_run})

    def _prune(self) -> None:
        """История задач ограничена: все активные + последние 30 завершённых."""
        if len(self.jobs) <= 80:
            return
        finished = [k for k, v in self.jobs.items() if v.status in ("done", "error")]
        for key in finished[: max(0, len(finished) - 30)]:
            self.jobs.pop(key, None)

    def _run(self, job: Job) -> None:
        started = datetime.now()
        job.status = "running"
        try:
            if job.params.get("one"):
                self._publish_one(job)
            else:
                dry_run = bool(job.params.get("dry_run"))
                limit = int(job.params.get("limit") or self.db.setting_int("publish_batch", 5))
                self.publish(job, dry_run=dry_run, limit=limit)
            job.status = "done"
        except VkError as exc:
            job.status = "error"
            job.error = str(exc)
            job.log.append(f"VK: {exc}")
        except Exception as exc:  # не роняем сервер ради одной задачи
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            logger.error("Задача %s (%s) упала", job.id, job.params, exc_info=True)
            job.log.append(tail_traceback())
        finally:
            job.elapsed = (datetime.now() - started).total_seconds()

    def _publish_one(self, job: Job) -> None:
        """Пост одного объявления из админки (кнопка «Опубликовать» в таблице)."""
        if not self.lock.acquire(blocking=False):
            raise VkError("Уже идёт публикация — VK требует паузу между постами")
        try:
            self.apply_settings()
            avito_id = str(job.params.get("avito_id") or "")
            ad = self.db.get_ad(avito_id)
            if not ad:
                raise VkError(f"Объявление {avito_id} не найдено в базе")
            if ad.get("posted_to_vk") and not job.params.get("dry_run"):
                raise VkError(f"Уже опубликовано: {ad.get('vk_post_url') or 'без ссылки'}")
            result = self.publisher.post_ad(ad, dry_run=bool(job.params.get("dry_run")))
            job.posts.append(post_payload(result))
            note = result.post_url or result.skipped or result.error or avito_id
            job.log.append(("собрано: " if result.dry_run else "опубликовано: ") + str(note))
            if not result.ok and not result.dry_run:
                raise VkError(result.error or result.skipped or "пост не удался")
        finally:
            self.lock.release()

    def close(self) -> None:
        self.publisher.close()
        self.db.close()


class ParseService:
    """Держит один скрейпер и сериализует парсинг (браузер не для конкурентных запросов)."""

    def __init__(self, base_config: Config, publish_service: "PublishService | None" = None,
                 db: Database | None = None):
        self.base_config = base_config
        self.publish_service = publish_service
        self.db = db or Database(base_config.parser)
        self.scraper: AvitoScraper | None = None
        self.signature: tuple = ()
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    @staticmethod
    def request_urls(params: dict) -> list[str]:
        """Ссылки из формы: поле `urls` (по одной на строку), историч. поле `url`, запятые."""
        raw = params.get("urls") or params.get("url") or ""
        return split_urls(raw)

    def _config_for(self, params: dict) -> tuple[Config, tuple]:
        """Собрать конфигурацию прогона; подпись нужна для решения «пересоздавать ли браузер»."""
        config = Config.load()
        urls = self.request_urls(params)
        if params.get("use_sources"):
            # крон/кнопка «парсить всё»: берём включённые источники из базы
            urls = [s["url"] for s in self.db.source_summary() if s["enabled"]]
        if urls:
            config.parser.set_sources(urls)
        pages = self.db.setting_int("pages_per_source", 1)
        config.parser.pages = int(params.get("pages") or pages)
        config.parser.max_photos = max(1, int(params.get("max_photos") or 5))
        config.parser.details_sample = int(params.get("limit") or 0)
        config.parser.fetch_details = bool(self.db.setting_int("details_on", 1))
        config.parser.download_photos = bool(self.db.setting_int("photos_on", 1))
        config.browser.headless = bool(params.get("headless", True))
        proxy = (params.get("proxy") or "").strip()
        if proxy or not params.get("use_sources"):
            config.browser.proxy_string = proxy
        signature = (config.browser.proxy_string, config.browser.headless)
        return config, signature

    def _ensure_scraper(self, config: Config, signature: tuple) -> AvitoScraper:
        if self.scraper and self.signature != signature:
            self._close_scraper()
        if self.scraper is None:
            self.scraper = AvitoScraper(config)
            self.scraper.start()
            self.signature = signature
        return self.scraper

    def _close_scraper(self) -> None:
        if self.scraper:
            try:
                self.scraper.close()
            except Exception:
                pass
            self.scraper = None
            self.signature = ()

    def submit(self, params: dict) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], params=params)
        self.jobs[job.id] = job
        self._prune()
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _prune(self) -> None:
        """Хранить в памяти все активные задачи и последние 30 завершённых."""
        if len(self.jobs) <= 80:
            return
        finished = [k for k, v in self.jobs.items() if v.status in ("done", "error")]
        for key in finished[: max(0, len(finished) - 30)]:
            self.jobs.pop(key, None)

    def _run(self, job: Job) -> None:
        if not self.lock.acquire(timeout=1):
            job.status = "error"
            job.error = "Уже идёт другой парсинг, повторите через минуту"
            return
        started = datetime.now()
        try:
            job.status = "running"
            config, signature = self._config_for(job.params)
            urls = config.parser.sources()
            if not urls:
                job.log.append("Нет ссылок для парсинга (источники выключены или не заданы)")
                job.status = "done"
                return
            job.log.append(f"Ссылок в очереди: {len(urls)}")
            for index, item in enumerate(urls, 1):
                job.log.append(f"  {index}. {item}")
            job.log.append(f"Прокси: {config.browser.proxy_string or 'не задан (прямой IP)'}")
            scraper = self._ensure_scraper(config, signature)
            job.proxy_used = str(scraper.session.proxy or "нет")
            job.log.append(f"Браузер: {'headless' if config.browser.headless else 'с окном'}, прокси {job.proxy_used}")

            # лимит первого прогона: новая ссылка (runs == 0) парсится не более N объявлений,
            # чтобы за один цикл не улетать в сотню карточек незнакомой категории
            first_run_limit = self.db.setting_int("first_run_limit", 10)
            effective_limit = config.parser.details_sample or None
            if first_run_limit:
                fresh_sources = [s["url"] for s in self.db.source_summary()
                                 if s["url"] in urls and not s["runs"]]
                if fresh_sources:
                    job.log.append(f"  новые ссылки ({len(fresh_sources)}): первый прогон — "
                                   f"максимум {first_run_limit} объявлений")
                    effective_limit = min(effective_limit or first_run_limit, first_run_limit)

            ads = scraper.scrape(
                url=urls,
                pages=config.parser.pages,
                with_details=config.parser.fetch_details,
                with_photos=config.parser.download_photos,
                only_new=not job.params.get("all"),
                limit=effective_limit,
                on_progress=lambda message: (setattr(job, "progress", message), job.log.append(message)),
                on_ad=lambda ad: job.ads.append(self._public_ad(ad)),
            )
            if not job.ads:
                job.ads = [self._public_ad(ad) for ad in ads]
            job.sources = [
                {"url": item, "label": source_label(item),
                 "found": int(stats.get("found", 0)), "new": int(stats.get("new", 0)),
                 "status": str(stats.get("status", "error"))}
                for item, stats in scraper.sources_stats.items()
            ]
            job.blocked = scraper.blocked_count
            if job.params.get("publish") and self.publish_service:
                job.log.append("→ Публикую новые объявления в сообщество VK…")
                try:
                    self.publish_service.publish(
                        job,
                        dry_run=bool(job.params.get("publish_dry")),
                        limit=int(job.params.get("publish_limit") or self.db.setting_int("publish_batch", 5)),
                    )
                except VkError as exc:
                    job.log.append(f"VK: {exc}")
            job.status = "done"
            job.log.append(f"Готово: {len(job.ads)} объявлений по {len(job.sources)} источникам")
        except Exception as exc:
            job.status = "error"
            job.error = f"{type(exc).__name__}: {exc}"
            job.log.append("Исключение: " + job.error)
            logger.error("Парсинг %s упал", job.id, exc_info=True)
            job.log.append(tail_traceback())
            self._close_scraper()
        finally:
            job.elapsed = (datetime.now() - started).total_seconds()
            self.lock.release()

    @staticmethod
    def _public_ad(ad: dict) -> dict:
        """Убрать из ответа служебное, добавить относительные ссылки на скачанные фото."""
        files = ad.get("photo_files") or []
        photo_urls = [f"/photo?path={Path(f).name}&ad={ad.get('avito_id', '')}" for f in files]
        source = ad.get("source_url") or ""
        return {
            "avito_id": ad.get("avito_id"),
            "title": ad.get("title"),
            "price": ad.get("price"),
            "price_rub": ad.get("price_rub"),
            "url": ad.get("url"),
            "location": ad.get("location"),
            "source_url": source,
            "source_label": source_label(source),
            "description": (ad.get("description") or "")[:MAX_DESCRIPTION],
            "images": ad.get("images") or [],
            "photo_files": files,
            "photo_urls": photo_urls,
            "params": ad.get("params") or {},
            "status": ad.get("status") or "partial",
            "parsed_at": ad.get("parsed_at"),
            "posted_to_vk": ad.get("posted_to_vk"),
            "posted_at": ad.get("posted_at"),
            "vk_post_url": ad.get("vk_post_url"),
        }

    def cleanup(self) -> None:
        self._close_scraper()


class SchedulerService:
    """Крон: периодический парсинг источников и публикация очереди в VK.

    Интервалы и параметры читаются из таблицы settings в каждом цикле,
    поэтому изменения из админки подхватываются без перезапуска.
    """

    def __init__(self, parse_service: ParseService, publish_service: PublishService,
                 db: Database, enabled: bool = True):
        self.parse_service = parse_service
        self.publish_service = publish_service
        self.db = db
        self.next_parse_at = time.time() + 60       # первый цикл через минуту
        self.next_publish_at = time.time() + 180
        self.last_parse_result = "ожидание"
        self.last_parse_job: str | None = None
        self._stop = threading.Event()
        if enabled:
            threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(20)
            now = time.time()
            try:
                if self.db.setting_bool("cron_paused", False):
                    self.last_parse_result = "пауза"
                else:
                    if now >= self.next_publish_at:
                        self._publish_cycle()
                    if now >= self.next_parse_at:
                        self._parse_cycle()
            except Exception:
                logger.exception("Ошибка цикла планировщика")
                self.last_parse_result = "ошибка (см. лог)"
            # интервалы могут меняться на лету
            parse_min = max(1, self.db.setting_int("parse_interval_min", 15))
            publish_min = max(1, self.db.setting_int("publish_interval_min", 30))
            self.next_parse_at = min(self.next_parse_at, now + parse_min * 60)
            self.next_publish_at = min(self.next_publish_at, now + publish_min * 60)

    def _parse_cycle(self) -> None:
        parse_min = max(1, self.db.setting_int("parse_interval_min", 15))
        self.next_parse_at = time.time() + parse_min * 60
        enabled = [s["url"] for s in self.db.source_summary() if s["enabled"]]
        if not enabled:
            self.last_parse_result = "нет включённых ссылок"
            return
        job = self.parse_service.submit({"urls": "", "use_sources": True, "headless": True})
        self.last_parse_job = job.id
        self.last_parse_result = f"запущен в {datetime.now().strftime('%H:%M:%S')}"

    def _publish_cycle(self) -> None:
        publish_min = max(1, self.db.setting_int("publish_interval_min", 30))
        self.next_publish_at = time.time() + publish_min * 60
        pending = self.db.stats().get("pending", 0)
        if not pending:
            logger.info("Крон VK: очередь пуста")
            return
        self.publish_service.submit({"dry_run": False,
                                     "limit": self.db.setting_int("publish_batch", 5)})

    def state(self) -> dict:
        parse_min = max(1, self.db.setting_int("parse_interval_min", 15))
        publish_min = max(1, self.db.setting_int("publish_interval_min", 30))
        return {
            "parse_interval_min": parse_min,
            "publish_interval_min": publish_min,
            "next_parse": datetime.fromtimestamp(self.next_parse_at).isoformat(timespec="seconds"),
            "next_publish": datetime.fromtimestamp(self.next_publish_at).isoformat(timespec="seconds"),
            "last_parse_result": self.last_parse_result,
            "browser_alive": bool(self.parse_service.scraper),
            "paused": self.db.setting_bool("cron_paused", False),
        }

    def stop(self) -> None:
        self._stop.set()


class Handler(BaseHTTPRequestHandler):
    service: ParseService = None  # type: ignore[assignment]
    publish: PublishService = None  # type: ignore[assignment]
    auth: AuthService = None  # type: ignore[assignment]
    scheduler: SchedulerService = None  # type: ignore[assignment]
    no_auth: bool = False  # только для локальной отладки интерфейса (--no-auth)

    protocol_version = "HTTP/1.1"

    # ------------------------- служебное ------------------------- #
    def _send(self, body: bytes, content_type: str, status: int = 200, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _authorized(self) -> bool:
        if Handler.no_auth:
            return True
        cookies = parse_qs(self.headers.get("Cookie") or "")
        token = (cookies.get(SESSION_COOKIE) or [""])[0]
        return self.auth.verify(token)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    # ------------------------- GET ------------------------- #
    def do_GET(self) -> None:  # noqa: N802 (сигнатура stdlib)
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/login":
            if self._authorized():
                self._redirect("/")
                return
            self._send(LOGIN_PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/logout":
            # гасим cookie-сессию, а не только перебрасываем на вход
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if not self._authorized():
            if path.startswith(("/api/", "/job/")):
                self._json({"error": "unauthorized"}, 401)
            else:
                self._redirect("/login")
            return

        if path == "/":
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/api/state":
            self._json(self._state())
            return

        if path == "/api/listings":
            self._json(self._listings(parse_qs(parsed.query)))
            return

        if path == "/api/jobs":
            self._json({"jobs": self._jobs_payload()})
            return

        if path == "/api/logs":
            self._serve_logs(parse_qs(parsed.query))
            return

        if path == "/api/proxy":
            self._json(self._proxy_payload())
            return

        if path == "/api/preview":
            self._json(self._preview_payload())
            return

        if path == "/export.csv":
            self._export_csv(parse_qs(parsed.query))
            return

        if path == "/vk":
            self._json(self.publish.describe())
            return

        if path.startswith("/job/"):
            parts = path.split("/")
            job_id = parts[2] if len(parts) > 2 else ""
            job = self.service.jobs.get(job_id) or self.publish.jobs.get(job_id)
            if not job:
                self._json({"error": "задача не найдена"}, 404)
                return
            if len(parts) > 3 and parts[3] == "raw":
                self._json({"status": job.status, "params": job.params, "ads": job.ads,
                            "sources": job.sources, "posts": job.posts,
                            "elapsed": job.elapsed, "proxy_used": job.proxy_used})
                return
            self._json({"status": job.status, "progress": job.progress, "error": job.error,
                        "log": job.log[-40:], "ads": job.ads, "sources": job.sources,
                        "posts": job.posts,
                        "elapsed": job.elapsed, "blocked": job.blocked,
                        "proxy_used": job.proxy_used})
            return

        if path == "/photo":
            self._serve_photo(parse_qs(parsed.query))
            return

        self._json({"error": "not found"}, 404)

    def _state(self) -> dict:
        db = self.service.db
        recent = db.get_unposted(limit=8) or []
        vk = self.publish.describe()
        settings = db.all_settings()
        # ключ не отдаём в браузер целиком — только маску для подсказки
        token = settings.pop("vk_access_token", "") or ""
        settings["vk_access_token_mask"] = token[:10] + "…" + token[-4:] if token else ""
        return {
            "db": db.stats(),
            "sources": db.source_summary(),
            "settings": settings,
            "scheduler": self.scheduler.state(),
            "vk": {"pending": vk.get("pending"), "posted": vk.get("posted"),
                   "group_name": vk.get("group_name"), "last_post_url": vk.get("last_post_url"),
                   "error": vk.get("error"), "token_set": vk.get("token_set"),
                   "require_photos": vk.get("require_photos"),
                   "app_id": self.publish.config.vk.app_id},
            "recent": [self.service._public_ad(ad) for ad in recent],
        }

    def _listings(self, q: dict) -> dict:
        """Страница объявлений для таблицы + счётчики фильтров."""
        db = self.service.db
        flt = (q.get("filter") or ["all"])[0]
        if flt not in ("all", "pending", "posted", "partial"):
            flt = "all"
        srch = (q.get("q") or [""])[0].strip()
        try:
            page = max(1, int((q.get("page") or ["1"])[0]))
        except ValueError:
            page = 1
        try:
            per = min(200, max(5, int((q.get("per") or ["50"])[0])))
        except ValueError:
            per = 50
        items, total = db.list_ads(flt, srch, limit=per, offset=(page - 1) * per)
        return {
            "filter": flt, "page": page, "per": per, "total": total,
            "counts": db.counts_by_filter(),
            "items": [self.service._public_ad(ad) for ad in items],
        }

    @staticmethod
    def _jobs_payload() -> list[dict]:
        """Объединённый журнал задач парсинга и постинга для страницы «Задачи»."""
        items: list[dict] = []
        for svc, kind in ((Handler.service, "parse"), (Handler.publish, "publish")):
            for job in svc.jobs.values():
                summary = ""
                if job.status == "running":
                    summary = job.progress or "…"
                elif job.status == "error":
                    summary = job.error
                elif kind == "parse":
                    summary = f"{len(job.ads)} объявл., {len(job.sources)} источников"
                    if job.blocked:
                        summary += f", блокировок {job.blocked}"
                else:
                    ok = sum(1 for p in job.posts if p.get("ok"))
                    summary = f"постов {ok}/{len(job.posts)}"
                items.append({
                    "id": job.id, "kind": ("one" if job.params.get("one") else kind),
                    "status": job.status, "created_at": job.created_at.isoformat(timespec="seconds"),
                    "elapsed": job.elapsed, "progress": job.progress, "error": job.error,
                    "summary": summary,
                })
        items.sort(key=lambda x: x["created_at"], reverse=True)
        return items

    def _proxy_payload(self) -> dict:
        """Статус прокси: что в .env, что живо, что в карантине."""
        cfg = self.service.base_config
        payload = {
            "configured": [str(p) for p in ProxySettings.parse_pool(cfg.browser.proxy_string)],
            "allow_direct": bool(cfg.browser.allow_direct_fallback),
            "browser_alive": False,
            "log_path": str(cfg.parser.log_file),
        }
        scraper = self.service.scraper
        session = getattr(scraper, "session", None) if scraper else None
        if session is not None:
            payload.update({
                "browser_alive": True,
                "current": str(session.proxy) if session.proxy else "прямой IP",
                "pool_total": len(session.proxies),
                "pool_healthy": len(session.healthy_proxies()),
                "quarantined": sorted(session._quarantined),
            })
        return payload

    def _preview_payload(self) -> dict:
        """Предпросмотр следующего поста: текст по шаблону + фото без докачки."""
        ads = self.service.db.get_unposted(limit=1)
        if not ads:
            return {"empty": True}
        ad = ads[0]
        publisher = self.publish.publisher
        photos = publisher.collect_photos(ad, allow_download=False)
        photo_urls = [f"/photo?path={Path(p).name}&ad={ad.get('avito_id', '')}" for p in photos]
        return {
            "empty": False,
            "avito_id": ad.get("avito_id"),
            "title": ad.get("title"),
            "price": ad.get("price"),
            "url": ad.get("url"),
            "message": publisher.build_message(ad),
            "photo_urls": photo_urls,
        }

    def _serve_logs(self, q: dict) -> None:
        """Хвост файла лога для просмотра в админке; ?download=1 отдаёт файлом."""
        log_path = Path(self.service.base_config.parser.log_file)
        if not log_path.is_absolute():
            log_path = ROOT / log_path
        try:
            tail = min(2000, max(10, int((q.get("tail") or ["300"])[0])))
        except ValueError:
            tail = 300
        if not log_path.exists():
            if q.get("download"):
                self._json({"error": "лог-файл ещё не создан"}, 404)
            else:
                self._json({"path": str(log_path), "lines": [], "exists": False})
            return
        max_bytes = 4_000_000 if q.get("download") else 300_000
        with log_path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            text = fh.read().decode("utf-8", "replace")
        lines = text.splitlines()[-tail:]
        if q.get("download"):
            body = ("\n".join(lines) + "\n").encode("utf-8")
            self._send(body, "text/plain; charset=utf-8",
                       extra={"Content-Disposition":
                              f'attachment; filename="{log_path.name}"'})
            return
        self._json({"path": str(log_path), "lines": lines, "exists": True, "size": size})

    def _export_csv(self, q: dict) -> None:
        """Выгрузка объявлений под текущим фильтром в CSV (с BOM для Excel)."""
        flt = (q.get("filter") or ["all"])[0]
        if flt not in ("all", "pending", "posted", "partial"):
            flt = "all"
        srch = (q.get("q") or [""])[0].strip()
        ads, _total = self.service.db.list_ads(flt, srch, limit=10000, offset=0)
        buf = io.StringIO()
        writer = csv.writer(buf)
        cols = ["avito_id", "title", "price", "price_rub", "location", "url",
                "source_url", "status", "parsed_at", "posted_to_vk", "posted_at", "vk_post_url"]
        writer.writerow(cols)
        for ad in ads:
            writer.writerow([ad.get(col) for col in cols])
        stamp = datetime.now().strftime("%Y%m%d")
        body = buf.getvalue().encode("utf-8-sig")
        self._send(body, "text/csv; charset=utf-8",
                   extra={"Content-Disposition": f'attachment; filename="avito_ads_{stamp}.csv"'})
        logger.info("Экспорт CSV: %d строк (фильтр %s)", len(ads), flt)

    def _serve_photo(self, query: dict) -> None:
        """Отдать скачанный файл из data/photos (только jpg/png, без выхода за директорию)."""
        name = (query.get("path") or [""])[0]
        ad_id = (query.get("ad") or [""])[0]
        candidate = (PHOTOS_ROOT / ad_id / Path(name).name).resolve()
        if not str(candidate).startswith(str(PHOTOS_ROOT)) or not candidate.is_file():
            self._json({"error": "файл не найден"}, 404)
            return
        suffix = candidate.suffix.lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp"}.get(suffix, "application/octet-stream")
        self._send(candidate.read_bytes(), mime, extra={"Cache-Control": "max-age=3600"})

    # ------------------------- POST ------------------------- #
    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path.rstrip("/")

        if route == "/login":
            params = self._read_json()
            if self.auth.check_login(str(params.get("username") or ""), str(params.get("password") or "")):
                token = self.auth.issue(str(params.get("username")))
                self.send_response(200)
                self.send_header("Set-Cookie",
                                 f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL}")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")
            else:
                self._json({"error": "неверный логин или пароль"}, 401)
            return

        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return

        params = self._read_json()

        if route == "/api/sources":
            self._handle_sources(params)
            return

        if route == "/api/ads":
            self._handle_ads(params)
            return

        if route == "/api/scheduler":
            self.service.db.setting_set("cron_paused", "1" if params.get("paused") else "0")
            self._json({"ok": True, "paused": bool(params.get("paused"))})
            return

        if route == "/api/settings":
            self._handle_settings(params)
            return

        if route == "/vk/publish":
            job = self.publish.submit(params)
            self._json({"id": job.id})
            return

        if route == "/vk/publish-one":
            avito_id = str(params.get("avito_id") or "").strip()
            if not avito_id:
                self._json({"error": "не передан avito_id"}, 400)
                return
            job = self.publish.submit_one(avito_id, dry_run=bool(params.get("dry_run")))
            self._json({"id": job.id})
            return

        if route == "/parse":
            urls = ParseService.request_urls(params)
            if not params.get("use_sources") and not urls:
                self._json({"error": "Укажите хотя бы одну ссылку на выдачу Авито"}, 400)
                return
            wrong = [u for u in urls if not u.startswith(("http://", "https://"))]
            if wrong:
                self._json({"error": "Ссылки должны начинаться с http(s):// — " + ", ".join(wrong)}, 400)
                return
            job = self.service.submit(params)
            self._json({"id": job.id, "urls": urls or "sources"})
            return

        self._json({"error": "not found"}, 404)

    def _handle_sources(self, params: dict) -> None:
        action = str(params.get("action") or "")
        url = str(params.get("url") or "").strip()
        db = self.service.db
        if action == "add":
            if not url.startswith(("http://", "https://")):
                self._json({"error": "ссылка должна начинаться с http(s)://"}, 400)
                return
            if "avito.ru" not in urlparse(url).netloc:
                self._json({"error": "добавляйте ссылки только на avito.ru"}, 400)
                return
            db.register_source(url, source_label(url))
            db.set_source_enabled(url, True)
            self._json({"ok": True, "message": "добавлена; первый прогон — максимум "
                        f"{db.setting_int('first_run_limit', 10)} объявлений"})
        elif action == "remove":
            with db._lock:
                db._conn.execute("DELETE FROM sources WHERE url = ?", (url,))
                db._conn.commit()
            self._json({"ok": True})
        elif action == "toggle":
            row = next((s for s in db.source_summary() if s["url"] == url), None)
            if not row:
                self._json({"error": "источник не найден"}, 404)
                return
            db.set_source_enabled(url, not row["enabled"])
            self._json({"ok": True, "enabled": not row["enabled"]})
        else:
            self._json({"error": "неизвестное действие"}, 400)

    def _handle_ads(self, params: dict) -> None:
        """Действия над объявлением из таблицы: удалить или вернуть в очередь."""
        action = str(params.get("action") or "")
        avito_id = str(params.get("avito_id") or "").strip()
        if not avito_id:
            self._json({"error": "не передан avito_id"}, 400)
            return
        db = self.service.db
        if action == "delete":
            if db.delete_ad(avito_id):
                self._json({"ok": True})
            else:
                self._json({"error": "объявление не найдено"}, 404)
        elif action == "requeue":
            if not db.get_ad(avito_id):
                self._json({"error": "объявление не найдено"}, 404)
                return
            db.mark_posted(avito_id, posted=False)
            logger.info("Объявление %s возвращено в очередь публикации", avito_id)
            self._json({"ok": True})
        else:
            self._json({"error": "неизвестное действие"}, 400)

    def _handle_settings(self, params: dict) -> None:
        allowed = {
            "parse_interval_min", "publish_interval_min", "first_run_limit",
            "pages_per_source", "details_on", "photos_on", "vk_min_interval_sec",
            "vk_require_photos", "vk_max_photos_per_post", "publish_batch",
            "vk_access_token", "vk_group_id", "cron_paused",
        }
        values = {k: str(v).strip() for k, v in params.items() if k in allowed}
        # пустой токен в форме не затирает ключ, сохранённый ранее
        if not values.get("vk_access_token"):
            values.pop("vk_access_token", None)
        if not values:
            self._json({"error": "нет допустимых полей"}, 400)
            return
        self.service.db.settings_bulk(values)
        logged = dict(values)
        if "vk_access_token" in logged:
            logged["vk_access_token"] = logged["vk_access_token"][:10] + "…"
        logger.info("Настройки обновлены из админки: %s", logged)
        # VK-ключ и сообщество применяем сразу, не дожидаясь следующего цикла
        self.publish.apply_settings()
        self._json({"ok": True, "saved": {k: ("…" if k == "vk_access_token" else v)
                                          for k, v in values.items()}})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[ui] {self.address_string()} {fmt % args}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Веб-админка парсера Авито и VK-публикации")
    ap.add_argument("--host", default="127.0.0.1", help="адрес (0.0.0.0 для внешнего доступа)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-headless", action="store_true", help="показывать окно браузера (локально)")
    ap.add_argument("--no-auth", action="store_true",
                    help="отключить вход (только для локальной отладки интерфейса!)")
    ap.add_argument("--no-cron", action="store_true",
                    help="не запускать фоновый планировщик (для тестов и отладки)")
    args = ap.parse_args(argv)

    config = Config.load()
    setup_logging(config.parser.log_level, config.parser.log_file)
    auth = AuthService(config)

    db = Database(config.parser)
    # синхронизируем источники из .env при старте; дальше админка — источник истины
    for url in config.parser.sources():
        db.register_source(url, source_label(url))

    publish_service = PublishService(config, db)
    service = ParseService(config, publish_service, db)
    scheduler = SchedulerService(service, publish_service, db, enabled=not args.no_cron)

    Handler.service = service
    Handler.publish = publish_service
    Handler.auth = auth
    Handler.scheduler = scheduler
    Handler.no_auth = args.no_auth

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Админка: http://{args.host}:{args.port}")
    if args.no_auth:
        print("ВНИМАНИЕ: вход отключён (--no-auth) — только для локальной отладки!")
    else:
        print(f"Логин: {auth.username} / пароль: "
              f"{'задан в .env' if config.admin_password else auth.password + ' (сгенерирован — задайте ADMIN_PASSWORD в .env)'}")
    try:
        vk = publish_service.describe()
        if vk.get("error"):
            print(f"VK: {vk['error']} — постинг недоступен, парсинг работает")
        else:
            print(f"VK: сообщество «{vk.get('group_name')}» (id {vk.get('group_id')}), "
                  f"в очереди {vk.get('pending')}, опубликовано {vk.get('posted')}")
    except Exception as exc:
        print(f"VK: статус не получен: {exc}")
    print(f"Крон: парсинг каждые {db.setting_int('parse_interval_min', 15)} мин, "
          f"публикация каждые {db.setting_int('publish_interval_min', 30)} мин")
    print("Ctrl+C — остановить")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстанавливаю…")
    finally:
        scheduler.stop()
        service.cleanup()
        publish_service.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())