"""Сервисы парсинга Авито и сохранения объявлений."""

from __future__ import annotations

import logging

from django.core.files.base import ContentFile
from django.utils import timezone

from core.models import JobRun
from core.proxies import pick_proxy

from .client import AvitoClient, AvitoError, PhotoPayload
from .models import Ad, AdPhoto, AvitoSource

logger = logging.getLogger("avito.services")


class ParseError(RuntimeError):
    pass


def parse_listing(source: AvitoSource, job: JobRun) -> int:
    job.set_progress("Открываю страницу выдачи Авито…")
    proxy = pick_proxy(require_browser=True)
    job.append_log(f"Прокси Авито: {proxy.display if proxy else 'прямой IP'}")
    client = AvitoClient(proxy=proxy)
    try:
        cards = client.fetch_listing(source.url)
    except AvitoError as exc:
        if proxy:
            proxy.mark_failure(str(exc))
        source.last_status = "error"
        source.last_error = str(exc)[:4000]
        source.save(update_fields=["last_status", "last_error", "updated_at"])
        raise
    else:
        if proxy:
            proxy.mark_success()

    if not cards:
        source.last_status = "empty"
        source.last_error = "На странице не найдено объявлений"
        source.save(update_fields=["last_status", "last_error", "updated_at"])
        raise ParseError("На странице не найдено объявлений. Проверьте ссылку и разметку Авито.")

    created = 0
    updated = 0
    for card in cards:
        defaults = {
            "source": source,
            "url": card["url"],
            "title": card.get("title", ""),
            "price_text": card.get("price_text", ""),
            "price_rub": card.get("price_rub"),
            "location": card.get("location", ""),
            "card_image": card.get("card_image", ""),
            "listing_position": card.get("listing_position", 0),
            "raw": card,
        }
        __, is_created = Ad.objects.update_or_create(avito_id=card["avito_id"], defaults=defaults)
        if is_created:
            created += 1
        else:
            updated += 1
    source.last_parsed_at = timezone.now()
    source.last_status = "ok"
    source.last_error = ""
    source.save(update_fields=["last_parsed_at", "last_status", "last_error", "updated_at"])
    job.append_log(f"Найдено карточек: {len(cards)}; новых: {created}; обновлено: {updated}")
    job.result = {"found": len(cards), "created": created, "updated": updated, "source_id": source.pk}
    job.save(update_fields=["result"])
    return len(cards)


def _save_photos(ad: Ad, photos: list[PhotoPayload], job: JobRun) -> int:
    ad.photos.all().delete()
    saved = 0
    for payload in photos:
        photo = AdPhoto(
            ad=ad,
            position=payload.position,
            image_url=payload.url,
            content_type=payload.content_type,
            status=AdPhoto.STATUS_DOWNLOADED,
            sha256=payload.sha256,
        )
        photo.file.save(payload.filename, ContentFile(payload.content), save=False)
        photo.save()
        saved += 1
    job.append_log(f"Скачано фотографий: {saved}")
    return saved


def parse_detail(ad: Ad, job: JobRun) -> Ad:
    job.set_progress(f"Открываю объявление {ad.avito_id}…")
    proxy = pick_proxy(require_browser=True)
    job.append_log(f"Прокси Авито: {proxy.display if proxy else 'прямой IP'}")
    client = AvitoClient(proxy=proxy)
    try:
        data = client.fetch_detail(ad.url)
        job.set_progress("Скачиваю фотографии…")
        photos = client.download_photos(data.get("images") or [])
    except AvitoError as exc:
        if proxy:
            proxy.mark_failure(str(exc))
        ad.detail_status = Ad.DETAIL_ERROR
        ad.detail_error = str(exc)[:4000]
        ad.save(update_fields=["detail_status", "detail_error", "last_seen_at"])
        raise
    else:
        if proxy:
            proxy.mark_success()

    if data.get("title"):
        ad.title = data["title"][:500]
    if data.get("price_text"):
        ad.price_text = data["price_text"][:120]
    if data.get("price_rub"):
        ad.price_rub = data["price_rub"]
    if data.get("description"):
        ad.description = data["description"]
    if data.get("location"):
        ad.location = data["location"][:255]
    ad.detail_status = Ad.DETAIL_LOADED
    ad.detail_error = ""
    ad.detail_loaded_at = timezone.now()
    ad.save(update_fields=[
        "title", "price_text", "price_rub", "description", "location",
        "detail_status", "detail_error", "detail_loaded_at", "last_seen_at",
    ])
    _save_photos(ad, photos, job)
    job.result = {"ad_id": ad.pk, "photos": len(photos)}
    job.save(update_fields=["result"])
    return ad


def ensure_detail(ad: Ad, job: JobRun) -> Ad:
    if ad.detail_status == Ad.DETAIL_LOADED:
        return ad
    return parse_detail(ad, job)
