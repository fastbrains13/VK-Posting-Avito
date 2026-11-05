"""Экспорт результатов парсинга в CSV/JSON (наследие `storage.py` из референсного проекта)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .logger import get_logger

logger = get_logger("avito.export")

FIELDS = ["avito_id", "title", "price", "price_rub", "url", "location", "description",
          "images", "photo_files", "params", "parsed_at", "posted_to_vk", "status",
          "source_url"]


def _flatten(ad: dict[str, Any]) -> dict[str, Any]:
    row = {key: ad.get(key) for key in FIELDS}
    for key in ("images", "photo_files"):
        value = row.get(key)
        if isinstance(value, list):
            row[key] = " | ".join(str(v) for v in value)
    params = row.get("params")
    if isinstance(params, dict):
        row["params"] = "; ".join(f"{k}: {v}" for k, v in params.items())
    return row


def save_to_csv(ads: list[dict[str, Any]], filename: str | Path = "avito_ads.csv") -> Path:
    """Сохранить объявления в CSV."""
    if not ads:
        logger.warning("Нет данных для сохранения в CSV")
        return Path(filename)
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(FIELDS) + [k for k in ads[0] if k not in FIELDS]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_flatten({**row, **{k: v for k, v in row.items()}}) for row in ads)
    logger.info("Сохранено %d объявлений в %s", len(ads), path)
    return path


def save_to_json(ads: list[dict[str, Any]], filename: str | Path = "avito_ads.json") -> Path:
    """Сохранить объявления в JSON."""
    if not ads:
        logger.warning("Нет данных для сохранения в JSON")
        return Path(filename)
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ads, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("Сохранено %d объявлений в %s", len(ads), path)
    return path
