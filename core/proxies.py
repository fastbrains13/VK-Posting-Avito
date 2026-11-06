"""Разбор, проверка и ротация единого пула прокси.

Формат строки:
    http://user:pass@host:port
    socks5://user:pass@host:port
    user:pass@host:port          (схема определится автоматически)
    host:port                    (схема определится автоматически)

Один пул используется и для Авито, и для VK. Прокси считается рабочим,
только если через него доступны оба сервиса; иначе он не попадёт в ротацию.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import unquote

import requests
from django.db.models import F, Q
from django.utils import timezone

from .models import ProxyEndpoint

logger = logging.getLogger("core.proxies")

MAX_PROXIES_PER_ADD = 50
CHECK_TIMEOUT = 8
CHECK_TARGETS = (
    ("Авито", "https://www.avito.ru/robots.txt"),
    ("VK", "https://api.vk.com/method/utils.getServerTime?v=5.199"),
)


class ProxyParseError(ValueError):
    pass


@dataclass
class ParsedProxy:
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""
    # Если схема не указана, при проверке пробуем и HTTP, и SOCKS5.
    scheme_explicit: bool = True

    @property
    def key(self) -> tuple[str, str, int, str]:
        return self.scheme, self.host, self.port, self.username


def parse_proxy_line(raw: str) -> ParsedProxy:
    value = (raw or "").strip()
    if not value or value.startswith("#"):
        raise ProxyParseError("пустая строка")

    scheme = "http"
    scheme_explicit = "://" in value
    if "://" in value:
        scheme_part, _, value = value.partition("://")
        scheme = scheme_part.lower()
        if scheme == "socks5h":
            scheme = "socks5"
        if scheme in ("socks4a",):
            scheme = "socks4"
        if scheme == "https":
            scheme = "http"
        if scheme not in ("http", "socks4", "socks5"):
            raise ProxyParseError(f"неизвестная схема {scheme}")

    credentials, sep, hostport = value.rpartition("@")
    username = password = ""
    if sep:
        username, _, password = credentials.partition(":")
        username = unquote(username)
        password = unquote(password)
    else:
        hostport = value

    if hostport.startswith("["):
        closing = hostport.find("]")
        if closing == -1:
            raise ProxyParseError("некорректный IPv6-адрес")
        host = hostport[1:closing]
        rest = hostport[closing + 1:]
        if not rest.startswith(":"):
            raise ProxyParseError("не указан порт")
        port_raw = rest[1:]
    else:
        host, sep, port_raw = hostport.rpartition(":")
        if not sep:
            raise ProxyParseError("не указан порт")
    host = host.strip()
    if not host or re.search(r"\s", host):
        raise ProxyParseError("некорректный хост")
    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise ProxyParseError("некорректный порт") from exc
    if not 1 <= port <= 65535:
        raise ProxyParseError("порт вне диапазона 1..65535")
    return ParsedProxy(scheme=scheme, host=host, port=port, username=username,
                       password=password, scheme_explicit=scheme_explicit)


def _requests_url(parsed: ParsedProxy) -> str:
    proxy = ProxyEndpoint(
        scheme=parsed.scheme, host=parsed.host, port=parsed.port,
        username=parsed.username,
    )
    proxy.set_password(parsed.password)
    return proxy.requests_url


def check_proxy(parsed: ParsedProxy, timeout: int = CHECK_TIMEOUT) -> tuple[bool, str]:
    """Проверить прокси на обоих сервисах: Авито и VK API."""
    proxies = {"http": _requests_url(parsed), "https": _requests_url(parsed)}
    for name, url in CHECK_TARGETS:
        try:
            response = requests.get(
                url, proxies=proxies, timeout=timeout, verify=False,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AvitoVK-MVP/0.1)"},
            )
        except requests.RequestException as exc:
            return False, f"{name}: {type(exc).__name__}: {str(exc)[:220]}"
        if response.status_code == 407:
            return False, f"{name}: прокси требует авторизации (HTTP 407)"
        if name == "Авито":
            if response.status_code not in (200, 301, 302, 403, 429):
                return False, f"Авито вернул HTTP {response.status_code}"
        else:
            if response.status_code != 200:
                return False, f"VK API вернул HTTP {response.status_code}"
            try:
                payload = response.json()
            except ValueError:
                return False, "VK API вернул не JSON"
            if isinstance(payload, dict) and payload.get("error"):
                return False, f"VK API: {payload['error']}"
    return True, ""


def _check_scheme(item: ParsedProxy, scheme: str) -> tuple[bool, str]:
    probe = ParsedProxy(
        scheme=scheme, host=item.host, port=item.port,
        username=item.username, password=item.password, scheme_explicit=True,
    )
    return check_proxy(probe)


def add_proxy_lines(text: str) -> dict:
    """Проверить список и сохранить только рабочие прокси в общий пул."""
    parsed: list[ParsedProxy] = []
    errors: list[str] = []
    seen: set[tuple[str, str, int, str]] = set()
    for line_no, line in enumerate((text or "").splitlines(), 1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        try:
            item = parse_proxy_line(raw)
        except ProxyParseError as exc:
            errors.append(f"строка {line_no}: {exc}")
            continue
        if item.key in seen:
            continue
        seen.add(item.key)
        parsed.append(item)
        if len(parsed) >= MAX_PROXIES_PER_ADD:
            errors.append(f"обработаны первые {MAX_PROXIES_PER_ADD} прокси")
            break

    if not parsed:
        return {"parsed": 0, "added": 0, "updated": 0, "ok": 0, "bad": 0, "errors": errors}

    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    checks: dict[int, dict[str, tuple[bool, str]]] = {index: {} for index in range(len(parsed))}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = []
        for index, item in enumerate(parsed):
            schemes = [item.scheme] if item.scheme_explicit else ["http", "socks5", "socks4"]
            for scheme in schemes:
                futures.append((index, scheme, pool.submit(_check_scheme, item, scheme)))
        for index, scheme, future in futures:
            try:
                ok, error = future.result()
            except Exception as exc:  # noqa: BLE001 — проверка не должна ронять страницу
                ok, error = False, f"{type(exc).__name__}: {exc}"
            checks[index][scheme] = (ok, error)

    added = updated = ok_count = bad_count = 0
    for index, item in enumerate(parsed):
        results = checks[index]
        if item.scheme_explicit:
            ok, error = results.get(item.scheme, (False, "нет результата проверки"))
            chosen = item if ok else None
        else:
            http_ok, http_error = results.get("http", (False, "нет результата"))
            socks_ok, socks_error = results.get("socks5", (False, "нет результата"))
            socks4_ok, socks4_error = results.get("socks4", (False, "нет результата"))
            if http_ok:
                chosen = ParsedProxy("http", item.host, item.port, item.username, item.password, True)
                ok, error = True, ""
            elif socks_ok:
                chosen = ParsedProxy("socks5", item.host, item.port, item.username, item.password, True)
                ok, error = True, ""
            elif socks4_ok:
                chosen = ParsedProxy("socks4", item.host, item.port, item.username, item.password, True)
                ok, error = True, ""
            else:
                chosen = None
                ok = False
                error = f"HTTP: {http_error}; SOCKS5: {socks_error}; SOCKS4: {socks4_error}"

        if not ok or chosen is None:
            bad_count += 1
            errors.append(f"{item.host}:{item.port}: {error}")
            schemes = [item.scheme] if item.scheme_explicit else ["http", "socks5", "socks4"]
            for existing in ProxyEndpoint.objects.filter(
                host=item.host, port=item.port, username=item.username, scheme__in=schemes
            ):
                existing.status = ProxyEndpoint.STATUS_BAD
                existing.last_error = error[:2000]
                existing.last_checked_at = timezone.now()
                existing.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
            continue

        duplicates = list(ProxyEndpoint.objects.filter(
            scheme=chosen.scheme, host=chosen.host, port=chosen.port, username=chosen.username
        ).order_by("pk"))
        existing = duplicates[0] if duplicates else None
        for duplicate in duplicates[1:]:
            duplicate.delete()
        proxy = existing or ProxyEndpoint(
            scheme=chosen.scheme, host=chosen.host, port=chosen.port, username=chosen.username,
        )
        if chosen.password:
            proxy.set_password(chosen.password)
        proxy.scope = ProxyEndpoint.SCOPE_SHARED
        proxy.status = ProxyEndpoint.STATUS_OK
        proxy.last_error = ""
        proxy.last_checked_at = timezone.now()
        proxy.is_active = True
        proxy.save()
        if existing:
            updated += 1
        else:
            added += 1
        ok_count += 1
    return {
        "parsed": len(parsed), "added": added, "updated": updated,
        "ok": ok_count, "bad": bad_count, "errors": errors,
    }


def recheck_all() -> dict:
    """Проверить все сохранённые прокси общего пула."""
    proxies = list(ProxyEndpoint.objects.all())
    if not proxies:
        return {"total": 0, "ok": 0, "bad": 0}

    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def check(proxy: ProxyEndpoint) -> tuple[ProxyEndpoint, bool, str]:
        parsed = ParsedProxy(
            scheme=proxy.scheme, host=proxy.host, port=proxy.port,
            username=proxy.username, password=proxy.password, scheme_explicit=True,
        )
        return proxy, *check_proxy(parsed)

    ok_count = bad_count = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for proxy, ok, error in pool.map(check, proxies):
            proxy.mark_checked(ok, error)
            if ok:
                ok_count += 1
            else:
                bad_count += 1
    return {"total": len(proxies), "ok": ok_count, "bad": bad_count}


def recheck_proxy(proxy: ProxyEndpoint) -> tuple[bool, str]:
    parsed = ParsedProxy(
        scheme=proxy.scheme, host=proxy.host, port=proxy.port,
        username=proxy.username, password=proxy.password, scheme_explicit=True,
    )
    ok, error = check_proxy(parsed)
    proxy.mark_checked(ok, error)
    return ok, error


def pick_proxy(require_browser: bool = False) -> ProxyEndpoint | None:
    """Выбрать следующий прокси для ротации: давно не использованный и рабочий."""
    qs = ProxyEndpoint.objects.filter(is_active=True, status=ProxyEndpoint.STATUS_OK)
    if require_browser:
        qs = qs.filter(Q(scheme=ProxyEndpoint.SCHEME_HTTP) | Q(
            scheme__in=(ProxyEndpoint.SCHEME_SOCKS4, ProxyEndpoint.SCHEME_SOCKS5), username=""
        ))
    proxy = qs.order_by(F("last_used_at").asc(nulls_first=True), "pk").first()
    if proxy:
        proxy.mark_used()
    return proxy
