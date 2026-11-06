"""Публикация объявления в сообщество."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils import timezone

from avito.models import Ad
from core.models import VKCommunity


class Publication(models.Model):
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_POSTING = "posting"
    STATUS_POSTED = "posted"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "В очереди"),
        (STATUS_RUNNING, "Подготовка"),
        (STATUS_POSTING, "Публикуется"),
        (STATUS_POSTED, "Опубликовано"),
        (STATUS_FAILED, "Ошибка"),
        (STATUS_SKIPPED, "Пропущено"),
    ]

    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="publications")
    community = models.ForeignKey(VKCommunity, on_delete=models.CASCADE, related_name="publications")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    message = models.TextField("Текст поста", blank=True)
    attachments = models.JSONField("Вложения", default=list, blank=True)
    vk_post_id = models.CharField("VK post id", max_length=64, blank=True)
    vk_post_url = models.URLField("Ссылка на пост", max_length=1000, blank=True)
    error = models.TextField("Ошибка", blank=True)
    attempts = models.PositiveSmallIntegerField("Попыток", default=0)
    guid = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    posted_at = models.DateTimeField("Опубликовано", null=True, blank=True)

    class Meta:
        verbose_name = "Публикация"
        verbose_name_plural = "Публикации"
        constraints = [
            # Главный инвариант MVP: одно объявление — один пост в сообществе.
            models.UniqueConstraint(fields=["ad", "community"], name="uniq_ad_community_publication"),
        ]

    def __str__(self) -> str:
        return f"{self.ad.avito_id} → {self.community.name} ({self.get_status_display()})"

    @property
    def is_posted(self) -> bool:
        return self.status == self.STATUS_POSTED and bool(self.vk_post_id)

    def mark_posted(self, post_id: str, post_url: str) -> None:
        self.status = self.STATUS_POSTED
        self.vk_post_id = str(post_id)
        self.vk_post_url = post_url
        self.error = ""
        self.posted_at = timezone.now()
        self.save(update_fields=["status", "vk_post_id", "vk_post_url", "error",
                                 "posted_at", "updated_at"])

    def mark_failed(self, error: str) -> None:
        self.status = self.STATUS_FAILED
        self.error = error[:4000]
        self.save(update_fields=["status", "error", "updated_at"])
