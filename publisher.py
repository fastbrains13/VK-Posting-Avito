#!/usr/bin/env python3
"""Публикация объявлений из avito.db в сообщество ВКонтакте.

Примеры:
    python publisher.py --check                 # проверить ключ и сообщество
    python publisher.py --preview               # показать тексты постов (ничего не отправлять)
    python publisher.py --publish 5             # опубликовать 5 неопубликованных объявлений
    python publisher.py --publish               # всю очередь
    python publisher.py --ad 8309226157         # одно конкретное объявление
    python publisher.py --watch                 # дежурить: постить по мере появления новых
    python publisher.py --test "Тестовый пост"  # произвольный пост (для проверки прав)

Ключ сообщества и id задаются в .env: VK_ACCESS_TOKEN, VK_GROUP_ID.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from avito_parser.config import Config
from avito_parser.database import Database
from avito_parser.logger import get_logger, setup_logging
from avito_parser.vk_publisher import VKPublisher, VkCaptchaRequired, VkError, VkPublishLimit


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="vk-publisher",
        description="Постинг новых объявлений Авито в сообщество ВКонтакте (фото + текст + ссылка)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="проверить токен и права на сообщество")
    mode.add_argument("--preview", action="store_true", help="показать тексты постов без отправки")
    mode.add_argument("--publish", action="store_true", help="опубликовать очередь объявлений")
    mode.add_argument("--watch", action="store_true", help="непрерывно постить новые объявления")
    mode.add_argument("--ad", metavar="AVITO_ID", help="опубликовать одно объявление по id")
    mode.add_argument("--test", metavar="TEXT", help="опубликовать произвольный тестовый пост")
    mode.add_argument("--delete", metavar="POST_ID", help="удалить запись стены по id поста")
    mode.add_argument("--stats", action="store_true", help="статистика очереди публикации")

    ap.add_argument("--dry-run", action="store_true", help="не отправлять в VK, только собрать пост")
    ap.add_argument("--no-photos", action="store_true", help="постить без фотографий")
    ap.add_argument("--limit", type=int, help="сколько объявлений взять из очереди (для --preview/--publish)")
    ap.add_argument("--interval", type=float, help="минимальный интервал между постами, сек")
    ap.add_argument("--group", help="сообщество: id или короткий адрес (VK_GROUP_ID)")
    ap.add_argument("--token", help="ключ сообщества (VK_ACCESS_TOKEN)")
    ap.add_argument("--cycle", type=int, default=60, help="пауза между проверками очереди в --watch, сек")
    ap.add_argument("-v", "--verbose", action="store_true", help="отладочный уровень логов")
    return ap


def print_post(publisher: VKPublisher, ad: dict, index: int, total: int) -> None:
    message = publisher.build_message(ad)
    photos = publisher.collect_photos(ad, allow_download=False)
    print(f"\n--- пост {index}/{total}: объявление {ad.get('avito_id')} ---")
    print(f"фото локально: {len(photos)} файл(ов)")
    print(message)
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load()
    if args.verbose:
        config.parser.log_level = "DEBUG"
    if args.token:
        config.vk.access_token = args.token
    if args.group:
        config.vk.group_id = str(args.group)
    if args.interval is not None:
        config.vk.min_interval_sec = args.interval
    if args.no_photos:
        config.vk.require_photos = False

    setup_logging(config.parser.log_level, config.parser.log_file)
    logger = get_logger("avito.vk.main")

    with Database(config.parser) as db:
        publisher = VKPublisher(config, db)

        if args.stats:
            print(json.dumps(publisher.status(), ensure_ascii=False, indent=2))
            for ad in db.get_unposted(limit=10):
                print(f"  в очереди: [{ad['avito_id']}] {ad['title'][:60]}")
            for ad in db.posted_ads(limit=5):
                print(f"  опубликовано: {ad['posted_at']} {ad['vk_post_url'] or ad['vk_post_id']}")
            return 0

        if args.check:
            try:
                info = publisher.resolve_group(refresh=True)
                print(json.dumps(info, ensure_ascii=False, indent=2))
                print("Ключ рабочий, публикация разрешена." if info.get("is_admin", True)
                      else "Внимание: у ключа нет прав администратора сообщества.")
                return 0
            except VkError as exc:
                print(f"Проверка не прошла: {exc}")
                return 1

        if args.delete:
            ok = publisher.delete_post(args.delete)
            print("Пост удалён" if ok else f"Не удалось удалить пост {args.delete}")
            return 0 if ok else 1

        if args.test:
            result = publisher.publish_text(args.test)
            print(f"Тестовый пост: {'OK' if result.ok else 'ОШИБКА'} {result.post_url or result.error}")
            return 0 if result.ok else 1

        if args.preview:
            ads = db.get_unposted(limit=args.limit)
            if not ads:
                print("Очередь пуста: сначала запустите парсер (main.py)")
                return 1
            for index, ad in enumerate(ads, 1):
                print_post(publisher, ad, index, len(ads))
            print(f"\nГотово к публикации: {len(ads)} шт. "
                  f"(интервал {config.vk.min_interval_sec:.0f} сек → ~{len(ads) * config.vk.min_interval_sec / 60:.0f} мин)")
            return 0

        if args.ad:
            ad = db.get_ad(args.ad)
            if not ad:
                print(f"Объявление {args.ad} не найдено в базе")
                return 1
            result = publisher.post_ad(ad, dry_run=args.dry_run)
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            print(result.message)
            return 0 if result.ok else 1

        if args.watch:
            logger.info("Дежурный режим: очередь проверяется каждые %d сек", args.cycle)
            while True:
                try:
                    results = publisher.publish_pending(on_progress=lambda message: logger.info(message))
                    for result in results:
                        if result.ok:
                            print(f"✓ {result.avito_id} → {result.post_url}")
                        else:
                            print(f"✗ {result.avito_id}: {result.error or result.skipped}")
                except VkError as exc:
                    logger.error("Публикация не удалась: %s", exc)
                print(f"Следующая проверка очереди через {args.cycle} сек (Ctrl+C — выход)…")
                time.sleep(max(10, args.cycle))

        # по умолчанию (без флага режима) и по --publish: выложить очередь
        results = publisher.publish_pending(limit=args.limit, dry_run=args.dry_run)
        if not results:
            print("Нечего публиковать: очередь пуста (запустите парсер main.py или --preview)")
            return 1
        ok = [r for r in results if r.ok]
        for result in results:
            if args.dry_run and result.ok:
                print(f"• {result.avito_id}: собран пост ({len(result.message)} знаков, "
                      f"{len(result.attachments)} фото) — в VK не отправлялся")
                continue
            mark = "✓" if result.ok else ("—" if result.skipped else "✗")
            print(f"{mark} {result.avito_id}: {result.post_url or result.skipped or result.error}")
        verb = "собрано в dry-run" if args.dry_run else "опубликовано"
        print(f"\nИтог: {len(ok)} из {len(results)} {verb}")
        return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nОстановлено пользователем")
        sys.exit(130)
    except (VkPublishLimit, VkCaptchaRequired) as exc:
        print(f"\nПубликация остановлена: {exc}")
        sys.exit(1)
