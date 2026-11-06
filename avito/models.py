"""Модели источника Авито, объявления и фотографий."""

from __future__ import annotations

from pathlib import Path

from django.db import models


class AvitoSource(models.Model):
    """Одна страница выдачи Авито, которую парсим в MVP."""

    url = models.URLField("Ссылка на выдачу", max_length=1000)
    city = models.CharField("Город", max_length=120, blank=True)
    title = models.CharField("Название источника", max_length=255, blank=True)
    last_parsed_at = models.DateTimeField("Последний парсинг", null=True, blank=True)
    last_status = models.CharField("Последний статус", max_length=32, blank=True)
    last_error = models.TextField("Последняя ошибка", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Источник Авито"
        verbose_name_plural = "Источники Авито"

    def __str__(self) -> str:
        return self.title or self.city or self.url


def ad_photo_path(instance: AdPhoto, filename: str) -> str:
    suffix = Path(filename).suffix.lower() or ".jpg"
    return f"ads/{instance.ad.avito_id}/{instance.position:02d}{suffix}"


class Ad(models.Model):
    """Объявление. Одна запись на avito_id, независимо от количества источников."""

    DETAIL_CARD = "card"
    DETAIL_LOADED = "detail"
    DETAIL_ERROR = "error"
    DETAIL_CHOICES = [
        (DETAIL_CARD, "Только карточка выдачи"),
        (DETAIL_LOADED, "Детали загружены"),
        (DETAIL_ERROR, "Ошибка загрузки деталей"),
    ]

    source = models.ForeignKey(AvitoSource, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="ads")
    avito_id = models.CharField("Avito id", max_length=32, unique=True)
    url = models.URLField("Ссылка на объявление", max_length=1000)
    title = models.CharField("Заголовок", max_length=500, blank=True)
    price_text = models.CharField("Цена", max_length=120, blank=True)
    price_rub = models.BigIntegerField("Цена, руб.", null=True, blank=True)
    description = models.TextField("Описание", blank=True)
    location = models.CharField("Локация", max_length=255, blank=True)
    card_image = models.URLField("Превью из выдачи", max_length=2000, blank=True)
    listing_position = models.PositiveIntegerField("Позиция в выдаче", default=0)
    detail_status = models.CharField(max_length=16, choices=DETAIL_CHOICES, default=DETAIL_CARD)
    detail_error = models.TextField("Ошибка деталей", blank=True)
    detail_loaded_at = models.DateTimeField("Детали загружены", null=True, blank=True)
    raw = models.JSONField("Сырые данные", default=dict, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Объявление"
        verbose_name_plural = "Объявления"
        ordering = ["listing_position", "id"]

    def __str__(self) -> str:
        return self.title or self.avito_id

    @property
    def detail_loaded(self) -> bool:
        return self.detail_status == self.DETAIL_LOADED

    @property
    def photo_count(self) -> int:
        return self.photos.filter(status=AdPhoto.STATUS_DOWNLOADED).count()


class AdPhoto(models.Model):
    STATUS_PENDING = "pending"
    STATUS_DOWNLOADED = "downloaded"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Ожидает"),
        (STATUS_DOWNLOADED, "Скачано"),
        (STATUS_ERROR, "Ошибка"),
    ]

    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="photos")
    position = models.PositiveSmallIntegerField("Порядок", default=0)
    image_url = models.URLField("URL фото", max_length=2000, blank=True)
    file = models.FileField("Файл", upload_to=ad_photo_path, blank=True)
    content_type = models.CharField("Тип", max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error = models.TextField("Ошибка", blank=True)
    sha256 = models.CharField("SHA-256", max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Фото объявления"
        verbose_name_plural = "Фотографии объявлений"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(fields=["ad", "position"], name="uniq_ad_photo_position"),
        ]

    def __str__(self) -> str:
        return f"{self.ad.avito_id} / {self.position}"
