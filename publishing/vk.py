"""Клиент VK API для MVP: пользовательский токен, сообщества, фото, wall.post."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import requests
from django.conf import settings

from core.models import ProxyEndpoint

logger = logging.getLogger("publishing.vk")

ERROR_HINTS = {
    5: "токен недействителен или истёк",
    6: "слишком частые запросы к VK — увеличьте интервал",
    7: "недостаточно прав: нужен пользовательский токен с правами wall, photos, groups",
    9: "флуд-контроль VK — повтор через паузу",
    14: "VK требует капчу",
    15: "wall.post разрешён только standalone-приложениям. Добавьте ключ сообщества "
        "или получите пользовательский токен standalone-приложения",
    27: "токен сообщества не умеет загружать фото на стену — нужен пользовательский токен",
    29: "превышен лимит запросов VK — повтор через паузу",
    100: "некорректные параметры запроса",
    102: "текст отклонён модерацией VK",
    103: "ссылка в посте запрещена",
    104: "превышен суточный лимит постов",
    205: "нет прав на действие",
    236: "слишком много постов за день",
    340: "слишком длинный текст поста",
    902: "сообщество ограничено спам-фильтром VK",
}


class VKError(RuntimeError):
    def __init__(self, message: str, code: int = 0):
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def hint(self) -> str:
        return ERROR_HINTS.get(self.code, "")

    def __str__(self) -> str:
        return f"{self.message} (код {self.code})" if self.code else self.message


class VKCaptcha(VKError):
    pass


class VKTemporaryPhotoLimit(VKError):
    """VK временно не принимает фото (пустой photo / 405): обычно отпускает за 10-15 минут."""

    def __init__(self, message: str, code: int = 0):
        super().__init__(message, code)


class VKClient:
    """Один клиент на токен. Все методы бросают VKError с понятным текстом."""

    def __init__(self, token: str, proxy: ProxyEndpoint | None = None):
        if not token:
            raise VKError("Токен VK не задан")
        self.token = token
        self.proxy = proxy
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "AvitoVK-MVP/0.1",
            "Accept": "application/json",
        })
        if proxy:
            self.session.proxies.update({"http": proxy.requests_url, "https": proxy.requests_url})
            if settings.PROXY_INSECURE_TLS:
                self.session.verify = False
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._upload_servers: dict[int, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # низкий уровень
    # ------------------------------------------------------------------
    def _call(self, method: str, retries: int = 3, **params: Any) -> Any:
        payload = {k: v for k, v in params.items() if v is not None and v != ""}
        payload["access_token"] = self.token
        payload["v"] = settings.VK_API_VERSION
        url = f"{settings.VK_API_BASE}/{method}"
        last_error: VKError | None = None

        for attempt in range(1, retries + 1):
            try:
                response = self.session.post(url, data=payload, timeout=settings.VK_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                last_error = VKError(f"Сеть недоступна при вызове {method}: {exc}")
                if attempt < retries:
                    time.sleep(2 * attempt)
                    continue
                raise last_error from exc

            try:
                data = response.json()
            except ValueError as exc:
                raise VKError(f"VK вернул не JSON (HTTP {response.status_code})") from exc

            if not isinstance(data, dict):
                return data
            if "error" not in data:
                return data.get("response", data)

            error = data.get("error")
            if not isinstance(error, dict):
                raise VKError(f"VK вернул ошибку неожиданного формата: {str(error)[:300]}")
            code = int(error.get("error_code") or 0)
            message = str(error.get("error_msg") or "неизвестная ошибка VK")
            hint = ERROR_HINTS.get(code, "")
            text = f"{message}" + (f" — {hint}" if hint else "")
            last_error = VKError(text, code)
            if code == 14:
                raise VKCaptcha(text, code)
            if code in (6, 9, 29) and attempt < retries:
                wait = 2 * attempt
                logger.warning("VK %s: %s, пауза %s сек", method, message, wait)
                time.sleep(wait)
                continue
            raise last_error

        raise last_error or VKError("VK API недоступен")

    # ------------------------------------------------------------------
    # аккаунт и сообщества
    # ------------------------------------------------------------------
    def validate(self) -> dict[str, Any]:
        response = self._call("users.get", fields="screen_name,photo_100")
        users = response if isinstance(response, list) else []
        if not users:
            raise VKError("VK не вернул пользователя по токену")
        user = users[0]
        return {
            "id": int(user.get("id") or 0),
            "name": " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part),
            "screen_name": user.get("screen_name") or "",
        }

    def list_admin_communities(self) -> list[dict[str, Any]]:
        """Сообщества, где пользователь администратор. Другие роли не поддерживаются."""
        response = self._call(
            "groups.get",
            filter="admin",
            extended=1,
            count=1000,
            fields="name,screen_name,photo_200",
        )
        items = (response or {}).get("items") if isinstance(response, dict) else []
        result: list[dict[str, Any]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            group_id = int(item.get("id") or 0)
            if not group_id:
                continue
            result.append({
                "group_id": group_id,
                "name": str(item.get("name") or f"Сообщество {group_id}"),
                "screen_name": str(item.get("screen_name") or ""),
                "photo_url": str(item.get("photo_200") or ""),
                "is_admin": bool(item.get("is_admin", True)),
            })
        return result

    def community_info(self, group_id: int) -> dict[str, Any]:
        response = self._call(
            "groups.getById",
            group_id=str(abs(int(group_id))),
            fields="name,screen_name,photo_200,is_admin",
        )
        data = response
        if isinstance(data, dict) and isinstance(data.get("groups"), list):
            data = data["groups"]
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            data = {}
        actual_id = int(data.get("id") or abs(int(group_id)))
        return {
            "group_id": actual_id,
            "name": str(data.get("name") or f"Сообщество {actual_id}"),
            "screen_name": str(data.get("screen_name") or ""),
            "photo_url": str(data.get("photo_200") or ""),
            "is_admin": bool(data.get("is_admin", False)),
            "can_post": bool(data.get("can_post", data.get("is_admin", False))),
        }

    def check_photo_capability(self, group_id: int) -> bool:
        """Проверить, что токен может получить upload server для фото на стену."""
        try:
            self._upload_server(group_id)
            return True
        except VKError as exc:
            if exc.code == 27:
                logger.warning("Фото недоступны для группы %s: %s", group_id, exc)
            return False

    # ------------------------------------------------------------------
    # фото
    # ------------------------------------------------------------------
    def _upload_server(self, group_id: int, force: bool = False) -> dict[str, Any]:
        group_id = abs(int(group_id))
        if not force and group_id in self._upload_servers:
            return self._upload_servers[group_id]
        response = self._call("photos.getWallUploadServer", group_id=group_id)
        if not isinstance(response, dict) or not response.get("upload_url"):
            raise VKError("VK не вернул адрес загрузки фото")
        self._upload_servers[group_id] = response
        return response

    def upload_photo(self, group_id: int, path: Path | str) -> str:
        group_id = abs(int(group_id))
        file_path = Path(path)
        if not file_path.is_file():
            raise VKError(f"Файл фото не найден: {file_path.name}")
        import mimetypes

        content_type = mimetypes.guess_type(file_path.name)[0] or "image/jpeg"
        uploaded = None
        response = None
        for attempt in (1, 2):
            server = self._upload_server(group_id, force=attempt > 1)
            with file_path.open("rb") as handle:
                try:
                    response = self.session.post(
                        server["upload_url"],
                        files={"file": (file_path.name, handle, content_type)},
                        timeout=settings.VK_UPLOAD_TIMEOUT,
                    )
                except requests.RequestException as exc:
                    if attempt == 1:
                        self._upload_servers.pop(group_id, None)
                        time.sleep(2)
                        continue
                    raise VKError(f"Не удалось загрузить фото в VK: {exc}") from exc
            try:
                uploaded = response.json()
                break
            except ValueError as exc:
                # 405/5xx бывают при устаревшем upload server или троттлинге:
                # один раз перезапрашиваем сервер и пробуем снова.
                if attempt == 1 and response.status_code in (405, 429, 500, 502, 503, 504):
                    self._upload_servers.pop(group_id, None)
                    time.sleep(2)
                    continue
                if response.status_code == 405:
                    raise VKTemporaryPhotoLimit(
                        "VK временно не принимает фото (HTTP 405). Подождите 10–15 минут "
                        "и повторите публикацию."
                    ) from exc
                raise VKError(
                    f"VK вернул не JSON при загрузке фото (HTTP {response.status_code}): "
                    f"{(response.text or '')[:200]}"
                ) from exc
        if uploaded is None or response is None:
            raise VKError("Не удалось загрузить фото в VK")
        if not isinstance(uploaded, dict):
            raise VKError("VK вернул неожиданный ответ при загрузке фото")
        if uploaded.get("error"):
            error = uploaded["error"]
            code = int(error.get("error_code") or 0) if isinstance(error, dict) else 0
            message = str(error.get("error_msg") if isinstance(error, dict) else error)
            raise VKError(f"Загрузка фото: {message}", code)
        photo, server_token, hash_token = uploaded.get("photo"), uploaded.get("server"), uploaded.get("hash")
        if not photo or not server_token or not hash_token:
            raise VKTemporaryPhotoLimit(
                "VK временно не принял фото (пустой photo). Обычно ограничение снимается "
                "через 10–15 минут; не повторяйте загрузку сразу."
            )

        saved = self._call(
            "photos.saveWallPhoto",
            group_id=group_id,
            photo=photo,
            server=server_token,
            hash=hash_token,
        )
        items = saved
        if isinstance(items, dict):
            items = items.get("items") or ([items] if items.get("id") else [])
        if isinstance(items, list) and items:
            item = items[0]
        elif isinstance(saved, dict) and saved.get("id"):
            item = saved
        else:
            raise VKError("VK не вернул сохранённое фото")
        photo_id = item.get("id")
        owner_id = item.get("owner_id") or -group_id
        if not photo_id:
            raise VKError("VK не вернул id фото")
        return f"photo{owner_id}_{photo_id}"

    # ------------------------------------------------------------------
    # стена
    # ------------------------------------------------------------------
    def post(self, group_id: int, message: str, attachments: list[str], guid: str) -> dict[str, Any]:
        group_id = abs(int(group_id))
        params = {
            "owner_id": -group_id,
            "from_group": 1,
            "message": message,
            "attachments": ",".join(attachments) if attachments else None,
            "guid": guid,
        }
        try:
            response = self._call("wall.post", **params)
        except VKError as exc:
            # Некоторые версии API/токены не принимают guid. Повторяем без него,
            # но только если ошибка явно про параметр.
            if exc.code == 100 and "guid" in str(exc).lower():
                params.pop("guid", None)
                response = self._call("wall.post", **params)
            else:
                raise
        post_id = str((response or {}).get("post_id") or "") if isinstance(response, dict) else ""
        if not post_id:
            raise VKError(f"VK не вернул post_id: {response}")
        return {"post_id": post_id, "post_url": f"https://vk.com/wall-{group_id}_{post_id}"}

    def recent_posts(self, group_id: int, count: int = 30) -> list[dict[str, Any]]:
        response = self._call("wall.get", owner_id=-abs(int(group_id)), count=count, filter="all")
        items = (response or {}).get("items") if isinstance(response, dict) else []
        return [item for item in (items or []) if isinstance(item, dict)]

    def find_post_by_url(self, group_id: int, url: str) -> dict[str, Any] | None:
        """Сверка после падения: ищем пост, в тексте которого есть ссылка на объявление."""
        if not url:
            return None
        for item in self.recent_posts(group_id, count=30):
            if url in str(item.get("text") or ""):
                return item
        return None

    def delete_post(self, group_id: int, post_id: str | int) -> bool:
        response = self._call("wall.delete", owner_id=-abs(int(group_id)), post_id=post_id)
        return bool(response)
