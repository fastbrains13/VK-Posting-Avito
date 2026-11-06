"""Настройки MVP v0: Django + PostgreSQL (SQLite для локального запуска и тестов)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or not value.strip() else value.strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on", "да")


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-secret-key-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "avito",
    "publishing",
    "jobs",
    "web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "web" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "web.context.active_community",
            ],
        },
    },
]

# PostgreSQL — основной вариант. SQLite остаётся для локального запуска без Docker
# и для тестов: без POSTGRES_DB база создаётся в data/db.sqlite3.
if env("POSTGRES_DB") and not env_bool("USE_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB"),
            "USER": env("POSTGRES_USER", "postgres"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "db"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }
else:
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "data" / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "web:login"
LOGIN_REDIRECT_URL = "web:dashboard"
LOGOUT_REDIRECT_URL = "web:login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if env_bool("HTTPS", False):
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# --- Параметры интеграций -------------------------------------------------
VK_API_VERSION = env("VK_API_VERSION", "5.199")
VK_API_BASE = env("VK_API_BASE", "https://api.vk.com/method")
VK_REQUEST_TIMEOUT = env_int("VK_REQUEST_TIMEOUT", 30)
VK_UPLOAD_TIMEOUT = env_int("VK_UPLOAD_TIMEOUT", 120)
VK_DEFAULT_MIN_INTERVAL = env_int("VK_POST_MIN_INTERVAL_SEC", 240)
VK_MESSAGE_LIMIT = env_int("VK_MAX_MESSAGE_LENGTH", 8000)

AVITO_HEADLESS = env_bool("AVITO_HEADLESS", True)
AVITO_PAGE_TIMEOUT = env_int("AVITO_PAGE_TIMEOUT", 40)
AVITO_RENDER_TIMEOUT = env_int("AVITO_RENDER_TIMEOUT", 30)
AVITO_PHOTO_TIMEOUT = env_int("AVITO_PHOTO_TIMEOUT", 30)
CHROME_BIN = env("CHROME_BIN", "")
CHROMEDRIVER_PATH = env("CHROMEDRIVER_PATH", "")
AVITO_USER_AGENT = env(
    "AVITO_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)
# Постоянный профиль Chrome: куки Авито переживают переход от выдачи к объявлению
# и следующий запуск воркера. Пустое значение — временный профиль на сессию.
AVITO_PROFILE_DIR = env("AVITO_PROFILE_DIR", "data/chrome-profile")
# Некоторые прокси перехватывают TLS. Для запросов через прокси можно отключить
# проверку сертификата (используйте осознанно).
PROXY_INSECURE_TLS = env_bool("PROXY_INSECURE_TLS", True)

MAX_PHOTOS_PER_POST = env_int("MAX_PHOTOS_PER_POST", 10)
PHOTO_MAX_BYTES = env_int("PHOTO_MAX_BYTES", 20 * 1024 * 1024)

# Ключ шифрования токенов. Если не задан — выводится из DJANGO_SECRET_KEY,
# поэтому при смене SECRET_KEY сохранённые токены перестанут читаться.
TOKEN_ENCRYPTION_KEY = env("TOKEN_ENCRYPTION_KEY", "")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "avito": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO"), "propagate": False},
        "publishing": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO"), "propagate": False},
        "jobs": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO"), "propagate": False},
    },
}

if DEBUG:
    # В отладке удобно видеть письма в консоли, но отправку не настраиваем.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
