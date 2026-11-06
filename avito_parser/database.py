"""Модуль хранения данных (ТЗ, п.3.2).

Инициализирует SQLite `avito.db`, хранит таблицу `parsed_ads` и предоставляет
быструю проверку дедупликации `is_parsed(avito_id)` — чтобы не парсить детали
и не качать фото для объявлений, которые мы уже видели.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import ParserConfig
from .logger import get_logger

logger = get_logger("avito.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS parsed_ads (
    avito_id      TEXT PRIMARY KEY,
    title         TEXT,
    price         TEXT,
    price_rub     INTEGER,
    url           TEXT,
    location      TEXT,
    description   TEXT,
    images        TEXT,          -- JSON: прямые ссылки на фото с Авито
    photo_files   TEXT,          -- JSON: пути скачанных файлов
    params        TEXT,          -- JSON: доп. параметры из выдачи
    parsed_at     TEXT,          -- ISO-8601 UTC
    posted_to_vk  INTEGER NOT NULL DEFAULT 0,
    posted_at     TEXT,
    vk_post_id    TEXT,          -- id записи на стене сообщества
    vk_post_url   TEXT,          -- постоянная ссылка vk.com/wall-<gid>_<pid>
    attempts      INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'partial',  -- complete | partial
    source_url    TEXT           -- ссылка выдачи, по которой объявление найдено
);
CREATE INDEX IF NOT EXISTS idx_parsed_ads_posted ON parsed_ads (posted_to_vk, parsed_at);

-- отслеживаемые ссылки: одна строка на источник, статистика последних прогонов
CREATE TABLE IF NOT EXISTS sources (
    url          TEXT PRIMARY KEY,
    label        TEXT,
    first_seen   TEXT,
    last_check   TEXT,
    last_status  TEXT,          -- ok | empty | blocked | error
    last_found   INTEGER NOT NULL DEFAULT 0,
    last_new     INTEGER NOT NULL DEFAULT 0,
    total_new    INTEGER NOT NULL DEFAULT 0,
    runs         INTEGER NOT NULL DEFAULT 0,
    enabled      INTEGER NOT NULL DEFAULT 1
);

-- настройки админки (перекрывают .env): интервалы крона, лимиты, VK-параметры
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# сколько раз пытаться дочитать «недолитое» объявление, прежде чем бросить
MAX_DETAIL_ATTEMPTS = 3


def _infer_status(ad: dict) -> str:
    """complete только если реально есть чем постить: описание или фото."""
    has_description = bool((ad.get("description") or "").strip())
    has_photos = bool(ad.get("photo_files") or ad.get("images"))
    return "complete" if (has_description or has_photos) else "partial"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Тонкая потокобезопасная обёртка над sqlite3 (одна база — один планировщик)."""

    def __init__(self, config: ParserConfig | None = None, db_path: Path | str | None = None):
        self.config = config or ParserConfig()
        self.db_path = Path(db_path or self.config.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        # WAL + busy_timeout: webui и worker пишут в одну базу одновременно,
        # без этого обычный journal — «database is locked» при параллельной записи
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate()
        logger.info("SQLite готов: %s", self.db_path)

    def _migrate(self) -> None:
        """Мягкая миграция: добавляем недостающие колонки у существующих баз."""
        with self._lock:
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(parsed_ads)")}
            if "status" not in columns:
                self._conn.execute("ALTER TABLE parsed_ads ADD COLUMN status TEXT NOT NULL DEFAULT 'partial'")
                # старые записи без описания и фото — недолитые, их надо перепарсить
                self._conn.execute(
                    "UPDATE parsed_ads SET status = 'complete' "
                    "WHERE COALESCE(description, '') != '' OR COALESCE(photo_files, '[]') != '[]'"
                )
                logger.info("Миграция БД: добавлена колонка status")
            if "attempts" not in columns:
                self._conn.execute("ALTER TABLE parsed_ads ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            if "source_url" not in columns:
                self._conn.execute("ALTER TABLE parsed_ads ADD COLUMN source_url TEXT")
                logger.info("Миграция БД: добавлена колонка source_url")
            if "vk_post_id" not in columns:
                self._conn.execute("ALTER TABLE parsed_ads ADD COLUMN vk_post_id TEXT")
                logger.info("Миграция БД: добавлена колонка vk_post_id")
            if "vk_post_url" not in columns:
                self._conn.execute("ALTER TABLE parsed_ads ADD COLUMN vk_post_url TEXT")
                logger.info("Миграция БД: добавлена колонка vk_post_url")
            # индексы по «новым» колонкам создаём только после того, как колонка точно есть:
            # иначе CREATE INDEX на старой базе падает с «no such column»
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_parsed_ads_status ON parsed_ads (status, attempts)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_parsed_ads_source ON parsed_ads (source_url)"
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # дедупликация
    # ------------------------------------------------------------------ #
    def is_parsed(self, avito_id: str | int) -> bool:
        """Есть ли объявление в базе (проверка до парсинга деталей и фото)."""
        if not avito_id:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM parsed_ads WHERE avito_id = ? LIMIT 1", (str(avito_id),)
            ).fetchone()
        return row is not None

    def is_posted(self, avito_id: str | int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT posted_to_vk FROM parsed_ads WHERE avito_id = ?", (str(avito_id),)
            ).fetchone()
        return bool(row and row["posted_to_vk"])

    # ------------------------------------------------------------------ #
    # запись
    # ------------------------------------------------------------------ #
    def save_ad(self, ad: dict[str, Any], update: bool = True) -> bool:
        """Сохранить/обновить объявление. Возвращает True, если запись новая."""
        avito_id = str(ad.get("avito_id") or "").strip()
        if not avito_id:
            logger.debug("Пропущена запись без avito_id: %s", ad.get("url"))
            return False

        payload = {
            "avito_id": avito_id,
            "title": ad.get("title"),
            "price": ad.get("price"),
            "price_rub": ad.get("price_rub"),
            "url": ad.get("url"),
            "location": ad.get("location"),
            "description": ad.get("description"),
            "images": json.dumps(ad.get("images") or [], ensure_ascii=False),
            "photo_files": json.dumps(ad.get("photo_files") or [], ensure_ascii=False),
            "params": json.dumps(ad.get("params") or {}, ensure_ascii=False),
            "parsed_at": ad.get("parsed_at") or _now(),
            "status": ad.get("status") or _infer_status(ad),
            "source_url": ad.get("source_url"),
        }
        columns = ", ".join(payload)
        placeholders = ", ".join("?" for _ in payload)
        values = list(payload.values())
        # при обновлении не затираем непустые данные пустыми (частичный апсейт из деталей)
        assignments = ", ".join(
            # статус только «апгрейдим»: неудачная повторная попытка не должна портить complete
            "status = CASE WHEN excluded.status = 'complete' THEN 'complete' ELSE parsed_ads.status END"
            if c == "status" else
            (f"{c} = COALESCE(NULLIF(excluded.{c}, ''), parsed_ads.{c})"
             if c != "price_rub" else f"{c} = COALESCE(excluded.{c}, parsed_ads.{c})")
            for c in payload if c != "avito_id"
        )

        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM parsed_ads WHERE avito_id = ?", (avito_id,)
            ).fetchone()
            if exists:
                if not update:
                    return False
                self._conn.execute(
                    f"INSERT INTO parsed_ads ({columns}) VALUES ({placeholders}) "
                    f"ON CONFLICT(avito_id) DO UPDATE SET {assignments}",
                    values,
                )
                return False
            self._conn.execute(f"INSERT INTO parsed_ads ({columns}) VALUES ({placeholders})", values)
            return True

    def mark_posted(self, avito_id: str | int, posted: bool = True,
                    post_id: str | int | None = None, post_url: str | None = None) -> None:
        """Отметить публикацию в VK и сохранить ссылку на пост (для переоткрытия из UI)."""
        with self._lock:
            self._conn.execute(
                "UPDATE parsed_ads SET posted_to_vk = ?, posted_at = ?, "
                "vk_post_id = COALESCE(?, vk_post_id), vk_post_url = COALESCE(?, vk_post_url) "
                "WHERE avito_id = ?",
                (1 if posted else 0, _now() if posted else None,
                 str(post_id) if post_id else None, post_url, str(avito_id)),
            )
            self._conn.commit()

    def last_posted(self) -> dict[str, Any] | None:
        """Последний опубликованный пост: время и ссылка."""
        with self._lock:
            row = self._conn.execute(
                "SELECT avito_id, posted_at, vk_post_id, vk_post_url, title FROM parsed_ads "
                "WHERE posted_to_vk = 1 ORDER BY posted_at DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def posted_ads(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT avito_id, title, posted_at, vk_post_url FROM parsed_ads "
                "WHERE posted_to_vk = 1 ORDER BY posted_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def list_ads(self, flt: str = "all", q: str = "", limit: int = 50,
                 offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Страница объявлений для админки: фильтр + поиск + пагинация.

        flt: all | pending (готовы к постингу) | posted (опубликованы) | partial (недолитые).
        Возвращает (строки, всего_под_фильтром) — total нужен пагинатору.
        """
        where = ["1=1"]
        params: list[Any] = []
        if flt == "pending":
            where.append("posted_to_vk = 0 AND status = 'complete'")
        elif flt == "posted":
            where.append("posted_to_vk = 1")
        elif flt == "partial":
            where.append("status = 'partial'")
        if q:
            where.append("(title LIKE ? OR description LIKE ? OR avito_id LIKE ? OR url LIKE ?)")
            like = f"%{q}%"
            params += [like, like, like, like]
        clause = " AND ".join(where)
        # опубликованные сортируем по моменту поста, остальные — по времени разбора
        order = ("posted_at DESC, parsed_at DESC" if flt == "posted"
                 else "parsed_at DESC, avito_id DESC")
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) c FROM parsed_ads WHERE {clause}", params).fetchone()["c"]
            rows = self._conn.execute(
                f"SELECT * FROM parsed_ads WHERE {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                (*params, int(limit), int(offset)),
            ).fetchall()
        return [self._row_to_ad(r) for r in rows], int(total)

    def counts_by_filter(self) -> dict[str, int]:
        """Счётчики для фильтра-карточек на странице «Объявления».

        Ключи совпадают с фильтрами list_ads(): all / pending / posted / partial.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) total, "
                "SUM(CASE WHEN posted_to_vk = 1 THEN 1 ELSE 0 END) posted, "
                "SUM(CASE WHEN posted_to_vk = 0 AND status = 'complete' THEN 1 ELSE 0 END) pending, "
                "SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) partial "
                "FROM parsed_ads"
            ).fetchone()
        c = {k: int(row[k] or 0) for k in ("total", "posted", "pending", "partial")}
        return {"all": c["total"], "pending": c["pending"],
                "posted": c["posted"], "partial": c["partial"]}

    def delete_ad(self, avito_id: str | int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM parsed_ads WHERE avito_id = ?", (str(avito_id),))
            self._conn.commit()
        if cur.rowcount:
            logger.info("Объявление %s удалено из базы через админку", avito_id)
        return bool(cur.rowcount)

    def bump_attempts(self, avito_id: str | int) -> int:
        with self._lock:
            self._conn.execute(
                "UPDATE parsed_ads SET attempts = attempts + 1 WHERE avito_id = ?", (str(avito_id),)
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT attempts FROM parsed_ads WHERE avito_id = ?", (str(avito_id),)
            ).fetchone()
        return int(row["attempts"]) if row else 0

    def commit(self) -> None:
        with self._lock:
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # отслеживаемые ссылки (источники)
    # ------------------------------------------------------------------ #
    def register_source(self, url: str, label: str | None = None) -> bool:
        """Занести ссылку в список отслеживаемых. True, если источник новый."""
        if not url:
            return False
        with self._lock:
            exists = self._conn.execute("SELECT 1 FROM sources WHERE url = ?", (url,)).fetchone()
            if exists:
                return False
            self._conn.execute(
                "INSERT INTO sources (url, label, first_seen) VALUES (?, ?, ?)",
                (url, label, _now()),
            )
            self._conn.commit()
            logger.info("Новый источник отслеживания: %s", url)
            return True

    def touch_source(self, url: str, status: str = "ok", found: int = 0, new: int = 0) -> None:
        """Обновить статистику источника по итогам прогона."""
        with self._lock:
            self.register_source(url)
            self._conn.execute(
                "UPDATE sources SET last_check = ?, last_status = ?, last_found = ?, "
                "last_new = ?, total_new = total_new + ?, runs = runs + 1 WHERE url = ?",
                (_now(), status, int(found), int(new), int(new), url),
            )
            self._conn.commit()

    def list_sources(self, enabled_only: bool = True) -> list[dict[str, Any]]:
        """Все отслеживаемые ссылки в порядке добавления."""
        sql = "SELECT * FROM sources"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY first_seen ASC"
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql)]

    def set_source_enabled(self, url: str, enabled: bool) -> None:
        with self._lock:
            self._conn.execute("UPDATE sources SET enabled = ? WHERE url = ?", (1 if enabled else 0, url))
            self._conn.commit()

    def sync_sources(self, urls: list[str]) -> None:
        """Занести в базу все рабочие ссылки (в т.ч. выключенные ранее не включаем)."""
        for url in urls:
            self.register_source(url)

    def ads_by_source(self, url: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) c FROM parsed_ads WHERE source_url = ?", (url,)
            ).fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------ #
    # настройки админки (key-value поверх .env)
    # ------------------------------------------------------------------ #
    # Дефолты только тех параметров, у которых нет значения в окружении: интервалы
    # крона и лимиты админки. Полный реестр настроек — в avito_parser/settings.py:
    # остальные перекрывают .env, лишь когда строка реально сохранена в таблице.
    DEFAULT_SETTINGS: dict[str, str] = {
        "parse_interval_min": "15",       # крон: как часто парсить источники
        "publish_interval_min": "30",     # крон: как часто публиковать очередь в VK
        "first_run_limit": "10",          # новая ссылка: сколько объявлений парсить в первый прогон
        "publish_batch": "5",             # сколько объявлений за один цикл публикации
        "cron_paused": "0",               # пауза крона из админки (0 = работает)
    }

    def setting_get(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row and row["value"] is not None:
            return row["value"]
        return self.DEFAULT_SETTINGS.get(key, default)

    def setting_int(self, key: str, default: int = 0) -> int:
        raw = self.setting_get(key)
        try:
            return int(float(raw)) if raw is not None else default
        except (TypeError, ValueError):
            return default

    def setting_bool(self, key: str, default: bool = False) -> bool:
        raw = self.setting_get(key)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "yes", "on", "да")

    def setting_set(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
            self._conn.commit()

    def settings_bulk(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            self.setting_set(key, value)

    def all_settings(self) -> dict[str, str]:
        with self._lock:
            rows = {r["key"]: r["value"] for r in self._conn.execute("SELECT key, value FROM settings")}
        merged = dict(self.DEFAULT_SETTINGS)
        merged.update(rows)
        return merged

    def raw_settings(self) -> dict[str, str]:
        """Только реально сохранённые строки, без DEFAULT_SETTINGS.

        Нужно для наложения настроек поверх .env (avito_parser/settings.py):
        отсутствующая строка и пустое значение означают «параметр не перекрывали».
        """
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: (r["value"] or "") for r in rows}

    def settings_clear(self, keys: list[str]) -> int:
        """Удалить строки настроек — параметры вернутся к значениям из окружения."""
        if not keys:
            return 0
        placeholders = ", ".join("?" for _ in keys)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM settings WHERE key IN ({placeholders})", tuple(keys)
            )
            self._conn.commit()
        removed = int(cur.rowcount or 0)
        if removed:
            logger.info("Настройки сброшены к значениям из .env: %s", ", ".join(sorted(keys)))
        return removed

    def source_summary(self) -> list[dict[str, Any]]:
        """Сводка по источникам для админки: статистика прогона + всего объявлений."""
        with self._lock:
            rows = [dict(r) for r in self._conn.execute(
                "SELECT * FROM sources ORDER BY first_seen ASC"
            )]
        for item in rows:
            item["ads"] = self.ads_by_source(item["url"])
        return rows

    # ------------------------------------------------------------------ #
    # чтение
    # ------------------------------------------------------------------ #
    def _row_to_ad(self, row: sqlite3.Row) -> dict[str, Any]:
        ad = dict(row)
        for key in ("images", "photo_files", "params"):
            try:
                ad[key] = json.loads(ad.get(key) or "[]") if key != "params" else json.loads(ad.get(key) or "{}")
            except (TypeError, json.JSONDecodeError):
                ad[key] = [] if key != "params" else {}
        return ad

    def get_unposted(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Объявления, готовые к публикации: полностью спарсенные и ещё не отправленные."""
        sql = ("SELECT * FROM parsed_ads WHERE posted_to_vk = 0 AND status = 'complete' "
               "ORDER BY parsed_at ASC")
        params: tuple = ()
        if limit:
            sql += " LIMIT ?"
            params = (limit,)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_ad(r) for r in rows]

    def get_incomplete_ids(self, limit: int = 200) -> set[str]:
        """Id «недолитых» объявлений (детали не пришли) — кандидаты на повторный парсинг."""
        sql = ("SELECT avito_id FROM parsed_ads WHERE status = 'partial' AND attempts < ? "
               "ORDER BY parsed_at ASC LIMIT ?")
        with self._lock:
            rows = self._conn.execute(sql, (MAX_DETAIL_ATTEMPTS, limit)).fetchall()
        return {r["avito_id"] for r in rows}

    def get_ad(self, avito_id: str | int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM parsed_ads WHERE avito_id = ?", (str(avito_id),)).fetchone()
        return self._row_to_ad(row) if row else None

    def all_ids(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT avito_id FROM parsed_ads").fetchall()
        return {r["avito_id"] for r in rows}

    def stats(self) -> dict[str, int]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) c FROM parsed_ads").fetchone()["c"]
            posted = self._conn.execute("SELECT COUNT(*) c FROM parsed_ads WHERE posted_to_vk = 1").fetchone()["c"]
            complete = self._conn.execute(
                "SELECT COUNT(*) c FROM parsed_ads WHERE status = 'complete'").fetchone()["c"]
            partial = self._conn.execute(
                "SELECT COUNT(*) c FROM parsed_ads WHERE status = 'partial'").fetchone()["c"]
            sources = self._conn.execute(
                "SELECT COUNT(*) c FROM sources WHERE enabled = 1").fetchone()["c"]
        return {
            "total": int(total),
            "posted": int(posted),
            "pending": int(complete - posted),
            "complete": int(complete),
            "partial": int(partial),
            "sources": int(sources),
        }

    def search(self, text: str, limit: int = 20) -> Iterable[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM parsed_ads WHERE title LIKE ? OR description LIKE ? ORDER BY parsed_at DESC LIMIT ?",
                (f"%{text}%", f"%{text}%", limit),
            ).fetchall()
        return [self._row_to_ad(r) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.commit()
            self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
