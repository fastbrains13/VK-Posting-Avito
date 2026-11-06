"""Модели VK-аккаунта, сообщества и фоновых задач."""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone

from .crypto import decrypt_token, encrypt_token


class VKAccount(models.Model):
    """Пользователь VK, чей токен используется для загрузки фото и постинга."""

    STATUS_ACTIVE = "active"
    STATUS_INVALID = "invalid"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Активен"),
        (STATUS_INVALID, "Недействителен"),
    ]

    display_name = models.CharField("Имя пользователя VK", max_length=255, blank=True)
    vk_user_id = models.BigIntegerField("VK user id", null=True, blank=True)
    token_encrypted = models.TextField("Зашифрованный токен")
    token_mask = models.CharField("Маска токена", max_length=64, blank=True)
    token_last4 = models.CharField("Последние 4 символа", max_length=8, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    last_checked_at = models.DateTimeField("Последняя проверка", null=True, blank=True)
    error = models.TextField("Ошибка проверки", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "VK-аккаунт"
        verbose_name_plural = "VK-аккаунты"

    def __str__(self) -> str:
        return self.display_name or f"VK-аккаунт #{self.pk}"

    @property
    def token(self) -> str:
        return decrypt_token(self.token_encrypted)

    def set_token(self, raw_token: str) -> None:
        token = (raw_token or "").strip()
        self.token_encrypted = encrypt_token(token)
        self.token_last4 = token[-4:] if token else ""
        self.token_mask = f"…{token[-4:]}" if token else ""

    def mark_valid(self, display_name: str = "", vk_user_id: int | None = None) -> None:
        self.status = self.STATUS_ACTIVE
        self.error = ""
        self.last_checked_at = timezone.now()
        if display_name:
            self.display_name = display_name
        if vk_user_id:
            self.vk_user_id = vk_user_id
        self.save(update_fields=["status", "error", "last_checked_at", "display_name",
                                 "vk_user_id", "updated_at"])

    def mark_invalid(self, error: str) -> None:
        self.status = self.STATUS_INVALID
        self.error = error[:2000]
        self.last_checked_at = timezone.now()
        self.save(update_fields=["status", "error", "last_checked_at", "updated_at"])


class VKCommunity(models.Model):
    """Сообщество, выбранное для публикации. В MVP активно ровно одно."""

    account = models.ForeignKey(VKAccount, on_delete=models.CASCADE, related_name="communities")
    group_id = models.BigIntegerField("VK group id")
    name = models.CharField("Название", max_length=255)
    screen_name = models.CharField("Короткий адрес", max_length=255, blank=True)
    photo_url = models.URLField("Аватар", max_length=1000, blank=True)
    is_admin = models.BooleanField("Пользователь — администратор", default=False)
    can_post = models.BooleanField("Можно публиковать", default=False)
    can_upload_photos = models.BooleanField("Можно загружать фото", default=False)
    is_active = models.BooleanField("Выбрано для публикации", default=False)
    # Ключ сообщества нужен только для wall.post, если пользовательский токен
    # выдан non-standalone приложению (VK отвечает кодом 15). Фото всё равно
    # загружаются пользовательским токеном.
    community_token_encrypted = models.TextField("Ключ сообщества (зашифрован)", blank=True)
    community_token_mask = models.CharField("Маска ключа сообщества", max_length=64, blank=True)
    community_token_last4 = models.CharField("Последние 4 символа ключа", max_length=8, blank=True)
    community_token_checked_at = models.DateTimeField("Ключ сообщества проверен", null=True, blank=True)
    min_interval_sec = models.PositiveIntegerField(
        "Минимальный интервал между постами, сек",
        default=settings.VK_DEFAULT_MIN_INTERVAL,
    )
    max_photos = models.PositiveSmallIntegerField(
        "Максимум фото в посте", default=10, validators=[MaxValueValidator(10)]
    )
    require_photos = models.BooleanField("Требовать фото", default=True)
    last_post_at = models.DateTimeField("Последний успешный пост", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "VK-сообщество"
        verbose_name_plural = "VK-сообщества"
        constraints = [
            models.UniqueConstraint(fields=["account", "group_id"], name="uniq_account_group"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.group_id})"

    @property
    def wall_url(self) -> str:
        return f"https://vk.com/{self.screen_name or 'club' + str(self.group_id)}"

    @property
    def community_token(self) -> str:
        return decrypt_token(self.community_token_encrypted) if self.community_token_encrypted else ""

    @property
    def has_community_token(self) -> bool:
        return bool(self.community_token_encrypted)

    def set_community_token(self, raw_token: str) -> None:
        token = (raw_token or "").strip()
        self.community_token_encrypted = encrypt_token(token) if token else ""
        self.community_token_last4 = token[-4:] if token else ""
        self.community_token_mask = f"…{token[-4:]}" if token else ""

    def seconds_until_next_post(self) -> int:
        if not self.last_post_at:
            return 0
        elapsed = (timezone.now() - self.last_post_at).total_seconds()
        return max(0, int(self.min_interval_sec - elapsed))

    def save(self, *args, **kwargs):
        # В MVP одно активное сообщество: при выборе нового старое снимаем.
        if self.is_active:
            VKCommunity.objects.exclude(pk=self.pk).filter(is_active=True).update(is_active=False)
        super().save(*args, **kwargs)


class ProxyEndpoint(models.Model):
    """HTTP/SOCKS5-прокси для Авито или VK.

    Пароль хранится зашифрованным. Ротация выбирает активные и проверенные
    записи по времени последнего использования.
    """

    # Один общий пул. Поле оставлено для совместимости со старыми записями,
    # новые прокси сохраняются как shared и используются и для Авито, и для VK.
    SCOPE_SHARED = "shared"
    SCOPE_AVITO = "avito"
    SCOPE_VK = "vk"
    SCOPE_CHOICES = [
        (SCOPE_SHARED, "Общий"),
        (SCOPE_AVITO, "Авито"),
        (SCOPE_VK, "VK"),
    ]
    SCHEME_HTTP = "http"
    SCHEME_SOCKS4 = "socks4"
    SCHEME_SOCKS5 = "socks5"
    SCHEME_CHOICES = [
        (SCHEME_HTTP, "HTTP"),
        (SCHEME_SOCKS4, "SOCKS4"),
        (SCHEME_SOCKS5, "SOCKS5"),
    ]
    STATUS_UNKNOWN = "unknown"
    STATUS_OK = "ok"
    STATUS_BAD = "bad"
    STATUS_CHOICES = [
        (STATUS_UNKNOWN, "Не проверен"),
        (STATUS_OK, "Работает"),
        (STATUS_BAD, "Не работает"),
    ]

    scope = models.CharField("Пул", max_length=16, choices=SCOPE_CHOICES, default=SCOPE_SHARED)
    scheme = models.CharField(max_length=16, choices=SCHEME_CHOICES, default=SCHEME_HTTP)
    host = models.CharField("Хост", max_length=255)
    port = models.PositiveIntegerField("Порт")
    username = models.CharField("Логин", max_length=255, blank=True)
    password_encrypted = models.TextField("Пароль (зашифрован)", blank=True)
    password_mask = models.CharField("Маска пароля", max_length=32, blank=True)
    is_active = models.BooleanField("Включён", default=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_UNKNOWN)
    last_checked_at = models.DateTimeField("Проверен", null=True, blank=True)
    last_error = models.TextField("Ошибка проверки", blank=True)
    last_used_at = models.DateTimeField("Использован", null=True, blank=True)
    success_count = models.PositiveIntegerField("Успешно", default=0)
    fail_count = models.PositiveIntegerField("Ошибок", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Прокси"
        verbose_name_plural = "Прокси"
        ordering = ["scope", "scheme", "host", "port"]
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "scheme", "host", "port", "username"],
                name="uniq_proxy_endpoint",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def password(self) -> str:
        return decrypt_token(self.password_encrypted) if self.password_encrypted else ""

    def set_password(self, raw: str) -> None:
        value = raw or ""
        self.password_encrypted = encrypt_token(value) if value else ""
        self.password_mask = "••••" if value else ""

    @property
    def auth(self) -> str:
        if not self.username:
            return ""
        from urllib.parse import quote

        user = quote(self.username, safe="")
        password = quote(self.password, safe="")
        return f"{user}:{password}@" if password else f"{user}@"

    @property
    def chrome_url(self) -> str:
        # Chrome не принимает логин/пароль в --proxy-server; для HTTP-авторизации
        # используется CDP, для SOCKS5 с паролем браузер не поддерживается.
        return f"{self.scheme}://{self.host}:{self.port}"

    @property
    def requests_url(self) -> str:
        scheme = "socks5h" if self.scheme == self.SCHEME_SOCKS5 else self.scheme
        return f"{scheme}://{self.auth}{self.host}:{self.port}"

    @property
    def display(self) -> str:
        auth = f"{self.username}:***@" if self.username else ""
        return f"{self.scheme}://{auth}{self.host}:{self.port}"

    @property
    def browser_supported(self) -> bool:
        # Chrome умеет HTTP-прокси с авторизацией (через CDP) и SOCKS5 без пароля.
        return not (self.scheme in (self.SCHEME_SOCKS4, self.SCHEME_SOCKS5) and self.username)

    def mark_checked(self, ok: bool, error: str = "") -> None:
        self.status = self.STATUS_OK if ok else self.STATUS_BAD
        self.last_error = "" if ok else error[:2000]
        self.last_checked_at = timezone.now()
        self.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])

    def mark_used(self) -> None:
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at", "updated_at"])

    def mark_success(self) -> None:
        self.success_count += 1
        self.status = self.STATUS_OK
        self.last_error = ""
        self.save(update_fields=["success_count", "status", "last_error", "updated_at"])

    def mark_failure(self, error: str = "") -> None:
        self.fail_count += 1
        self.last_error = error[:2000]
        if self.fail_count >= 3:
            self.status = self.STATUS_BAD
        self.save(update_fields=["fail_count", "last_error", "status", "updated_at"])


class JobRun(models.Model):
    """Ручная задача: парсинг выдачи, деталей или публикация."""

    KIND_PARSE_LISTING = "parse_listing"
    KIND_PARSE_DETAIL = "parse_detail"
    KIND_PUBLISH = "publish"
    KIND_CHOICES = [
        (KIND_PARSE_LISTING, "Парсинг выдачи"),
        (KIND_PARSE_DETAIL, "Парсинг объявления"),
        (KIND_PUBLISH, "Публикация"),
    ]

    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_QUEUED, "В очереди"),
        (STATUS_RUNNING, "Выполняется"),
        (STATUS_DONE, "Готово"),
        (STATUS_ERROR, "Ошибка"),
    ]

    kind = models.CharField("Тип", max_length=32, choices=KIND_CHOICES)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED)
    params = models.JSONField("Параметры", default=dict, blank=True)
    progress = models.CharField("Прогресс", max_length=255, blank=True)
    log = models.TextField("Журнал", blank=True)
    error = models.TextField("Ошибка", blank=True)
    result = models.JSONField("Результат", default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} #{self.pk} ({self.get_status_display()})"

    @property
    def is_finished(self) -> bool:
        return self.status in (self.STATUS_DONE, self.STATUS_ERROR)

    def append_log(self, message: str) -> None:
        line = f"{timezone.now():%H:%M:%S}  {message}"
        self.log = f"{self.log}\n{line}" if self.log else line
        self.save(update_fields=["log"])

    def set_progress(self, message: str) -> None:
        self.progress = message[:255]
        line = f"{timezone.now():%H:%M:%S}  {message}"
        self.log = f"{self.log}\n{line}" if self.log else line
        self.save(update_fields=["progress", "log"])
