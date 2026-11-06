"""Массовый импорт прокси из файла с проверкой.

Пример:
    python manage.py import_proxies ~/Downloads/data.txt
    python manage.py import_proxies data.txt --workers 30 --limit 100
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import urllib3
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import ProxyEndpoint
from core.proxies import ParsedProxy, ProxyParseError, check_proxy, parse_proxy_line

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SCHEMES = ["http", "socks5", "socks4"]


class Command(BaseCommand):
    help = "Импортировать прокси из файла, проверить и сохранить только рабочие"

    def add_arguments(self, parser):
        parser.add_argument("path", help="Файл: один прокси на строку")
        parser.add_argument("--workers", type=int, default=20, help="Параллельных проверок")
        parser.add_argument("--timeout", type=int, default=6, help="Таймаут одной проверки, сек")
        parser.add_argument("--limit", type=int, default=0, help="Проверить только первые N прокси")
        parser.add_argument("--dry-run", action="store_true", help="Не сохранять, только показать результат")
        parser.add_argument("--show-bad", action="store_true", help="Показать первые ошибки")

    def handle(self, *args, **options):
        path = Path(options["path"]).expanduser()
        if not path.is_file():
            raise CommandError(f"Файл не найден: {path}")

        parsed: list[ParsedProxy] = []
        errors: list[str] = []
        seen: set[tuple[str, str, int, str]] = set()
        for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
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
            if options["limit"] and len(parsed) >= options["limit"]:
                break

        total = len(parsed)
        if not total:
            self.stdout.write(self.style.WARNING("В файле нет валидных строк с прокси."))
            for error in errors[:20]:
                self.stdout.write(f"  {error}")
            return

        self.stdout.write(f"Прочитано уникальных прокси: {total}. Проверяю через Авито и VK…")
        checks: dict[int, dict[str, tuple[bool, str]]] = {index: {} for index in range(total)}
        tasks = []
        for index, item in enumerate(parsed):
            schemes = [item.scheme] if item.scheme_explicit else SCHEMES
            for scheme in schemes:
                tasks.append((index, scheme))

        done = 0
        with ThreadPoolExecutor(max_workers=max(1, options["workers"])) as pool:
            futures = {}
            for index, scheme in tasks:
                item = parsed[index]
                probe = ParsedProxy(scheme=scheme, host=item.host, port=item.port,
                                    username=item.username, password=item.password,
                                    scheme_explicit=True)
                future = pool.submit(check_proxy, probe, options["timeout"])
                futures[future] = (index, scheme)
            for future in as_completed(futures):
                index, scheme = futures[future]
                try:
                    ok, error = future.result()
                except Exception as exc:  # noqa: BLE001
                    ok, error = False, f"{type(exc).__name__}: {exc}"
                checks[index][scheme] = (ok, error)
                done += 1
                if done % 50 == 0:
                    self.stdout.write(f"  проверок: {done}/{len(tasks)}")

        saved = bad = 0
        bad_samples: list[str] = []
        for index, item in enumerate(parsed):
            results = checks[index]
            if item.scheme_explicit:
                ok, error = results.get(item.scheme, (False, "нет результата"))
                chosen = item if ok else None
            else:
                chosen = None
                error_parts = []
                for scheme in SCHEMES:
                    ok, error = results.get(scheme, (False, "нет результата"))
                    if ok:
                        chosen = ParsedProxy(scheme, item.host, item.port,
                                             item.username, item.password, True)
                        break
                    error_parts.append(f"{scheme.upper()}: {error}")
                error = "; ".join(error_parts)

            if not ok or chosen is None:
                bad += 1
                if len(bad_samples) < 20:
                    bad_samples.append(f"{item.host}:{item.port} — {error}")
                continue

            if options["dry_run"]:
                saved += 1
                continue

            duplicates = list(ProxyEndpoint.objects.filter(
                scheme=chosen.scheme, host=chosen.host, port=chosen.port, username=chosen.username
            ).order_by("pk"))
            proxy = duplicates[0] if duplicates else ProxyEndpoint(
                scheme=chosen.scheme, host=chosen.host, port=chosen.port, username=chosen.username
            )
            for duplicate in duplicates[1:]:
                duplicate.delete()
            if chosen.password:
                proxy.set_password(chosen.password)
            proxy.scope = ProxyEndpoint.SCOPE_SHARED
            proxy.status = ProxyEndpoint.STATUS_OK
            proxy.is_active = True
            proxy.last_error = ""
            proxy.last_checked_at = timezone.now()
            proxy.save()
            saved += 1

        self.stdout.write(self.style.SUCCESS(
            f"Готово: проверено {total}, рабочих {saved}, нерабочих {bad}. "
            f"{'Ничего не сохранено (dry-run).' if options['dry_run'] else 'Сохранены только рабочие.'}"
        ))
        if errors:
            self.stdout.write(f"Строк с ошибками разбора: {len(errors)}")
            for error in errors[:20]:
                self.stdout.write(f"  {error}")
        if options["show_bad"] and bad_samples:
            self.stdout.write("Примеры нерабочих:")
            for sample in bad_samples:
                self.stdout.write(f"  {sample}")
