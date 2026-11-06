"""Сборка текста поста: заголовок, цена, описание, ссылка.

Это не шаблонизатор: в MVP формат фиксирован. Позже сюда придёт
полноценный конструктор, но снимок текста уже хранится в Publication.
"""

from __future__ import annotations

import re

from django.conf import settings

from avito.models import Ad

_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"[ \t\u00a0\u202f]+")


def clean_line(value: str | None) -> str:
    text = _TAG_RE.sub(" ", value or "")
    return _SPACES_RE.sub(" ", text).strip()


def clean_multiline(value: str | None) -> str:
    text = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _TAG_RE.sub(" ", text)
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    # Схлопываем больше двух пустых строк подряд, сохраняя абзацы.
    out: list[str] = []
    empty = 0
    for line in lines:
        if not line:
            empty += 1
            if empty > 1:
                continue
        else:
            empty = 0
        out.append(line)
    return "\n".join(out).strip()


def _price(ad: Ad) -> str:
    value = clean_line(ad.price_text)
    if value:
        return value
    if ad.price_rub:
        return f"{ad.price_rub:,}".replace(",", " ") + " ₽"
    return ""


def build_message(ad: Ad) -> str:
    """Заголовок + цена + описание + ссылка. Ссылка и заголовок не обрезаются."""
    title = clean_line(ad.title) or "Объявление на Авито"
    price = _price(ad)
    description = clean_multiline(ad.description)
    url = (ad.url or "").strip()
    limit = max(1000, int(settings.VK_MESSAGE_LIMIT))

    parts = [title]
    if price:
        parts.append(price)
    if description:
        parts.append(description)
    if url:
        parts.append(url)
    text = "\n\n".join(parts)
    if len(text) <= limit:
        return text

    # Обрезаем только описание: заголовок, цена и ссылка должны остаться.
    fixed_parts = [title]
    if price:
        fixed_parts.append(price)
    if url:
        fixed_parts.append(url)
    fixed = "\n\n".join(fixed_parts)
    room = limit - len(fixed) - 6  # запас на разделители и многоточие
    if room <= 0:
        # Совсем крайний случай: режем заголовок, но ссылку сохраняем.
        room = max(0, limit - len(url) - 6)
        shortened = title[:room].rstrip()
        return f"{shortened}…\n\n{url}"[:limit]

    cut = description[:room].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    middle = [title]
    if price:
        middle.append(price)
    middle.append(cut + "…")
    if url:
        middle.append(url)
    return "\n\n".join(middle)[:limit]
