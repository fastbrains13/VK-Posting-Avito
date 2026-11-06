"""Шифрование пользовательских токенов VK.

Токен никогда не хранится в открытом виде и не отдаётся в интерфейс.
Ключ берётся из TOKEN_ENCRYPTION_KEY; если он не задан, выводится из
DJANGO_SECRET_KEY. Это удобно для MVP, но при смене SECRET_KEY старые
токены перестанут читаться — в продакшене лучше задать отдельный ключ.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class TokenCipherError(RuntimeError):
    """Не удалось зашифровать или расшифровать токен."""


def _fernet() -> Fernet:
    raw = (settings.TOKEN_ENCRYPTION_KEY or "").strip()
    if raw:
        try:
            return Fernet(raw.encode())
        except (ValueError, TypeError) as exc:
            raise TokenCipherError(
                "TOKEN_ENCRYPTION_KEY задан в неверном формате. "
                "Сгенерируйте ключ командой: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            ) from exc
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> str:
    if not token:
        return ""
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise TokenCipherError(
            "Не удалось расшифровать сохранённый токен. "
            "Проверьте TOKEN_ENCRYPTION_KEY / DJANGO_SECRET_KEY."
        ) from exc
