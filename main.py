#!/usr/bin/env python3
"""CLI для проверки модуля парсинга (ТЗ, п.3.1 + 3.2) и постинга в VK (п.3.4).

Парсер умеет отслеживать несколько ссылок одновременно. Примеры:
    python main.py "https://www.avito.ru/saransk/telefony/mobile" --details --photos
    python main.py "https://avito.ru/saransk/avtomobili" "https://avito.ru/saransk?q=iphone"
    python main.py --urls-file urls.txt --pages 2 --limit 20
    python main.py --watch 900            # опрашивать все ссылки каждые 15 минут
    python main.py --details --photos --publish        # и сразу постить новые в VK
    python main.py --details --photos --publish-dry-run  # собрать посты, не публикуя
    python main.py --stats
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from avito_parser.config import Config
from avito_parser.database import Database
from avito_parser.export import save_to_csv, save_to_json
from avito_parser.logger import get_logger, setup_logging
from avito_parser.scraper import AvitoScraper, source_label
from avito_parser.vk_publisher import VKPublisher, VkError


def publish_results(config: Config, limit: int | None, dry_run: bool) -> list:
    """Разослать свежие объявления в VK. Возвращает список PostResult."""
    with Database(config.parser) as db:
        publisher = VKPublisher(config, db)
        try:
            return publisher.publish_pending(limit=limit, dry_run=dry_run)
        except VkError as exc:
            print(f"VK: публикация остановлена: {exc}")
            return []
        finally:
            publisher.close()


def report_publish(results: list, dry_run: bool) -> None:
    for result in results:
        if dry_run and result.ok:
            print(f"  • dry-run {result.avito_id}: {len(result.message)} знаков, "
                  f"{len(result.attachments)} фото")
        elif result.ok:
            print(f"  ✓ {result.avito_id} → {result.post_url}")
        else:
            print(f"  ✗ {result.avito_id}: {result.skipped or result.error}")
    published = sum(1 for r in results if r.ok)
    print(f"  Итого {('собрано' if dry_run else 'опубликовано')}: {published} из {len(results)}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="avito-parser",
        description="Парсер новых объявлений Авито (Selenium + имитация поведения человека)",
    )
    ap.add_argument("urls", nargs="*", help=(
        "Одна или несколько ссылок на выдачу Авито; по умолчанию AVITO_TARGET_URL (можно "
        "списком через запятую) и/или SOURCES_FILE"))
    ap.add_argument("--urls-file", metavar="FILE", help="Файл со ссылками, по одной на строку")
    ap.add_argument("-p", "--pages", type=int, help="Количество страниц выдачи (по умолчанию 1)")
    ap.add_argument("--details", dest="details", action="store_true", default=None,
                    help="Парсить полные описания и фото со страниц объявлений")
    ap.add_argument("--no-details", dest="details", action="store_false")
    ap.add_argument("--photos", dest="photos", action="store_true", default=None,
                    help="Скачивать фотографии во временную директорию")
    ap.add_argument("--no-photos", dest="photos", action="store_false")
    ap.add_argument("--max-photos", type=int, help="Сколько фото качать на объявление (1-5)")
    ap.add_argument("--headless", dest="headless", action="store_true", default=None,
                    help="Запуск браузера без окна (HEADLESS_MODE)")
    ap.add_argument("--no-headless", dest="headless", action="store_false")
    ap.add_argument("--limit", type=int, help="Максимум новых объявлений за прогон")
    ap.add_argument("--sample", type=int, help="Парсить детали только у первых N новых объявлений")
    ap.add_argument("--watch", type=int, metavar="SECONDS", default=0,
                    help="Режим мониторинга: опрашивать все ссылки в цикле с интервалом (сек)")
    ap.add_argument("--all", dest="only_new", action="store_false", default=True,
                    help="Не учитывать базу: парсить детали у всех объявлений выдачи")
    ap.add_argument("--no-db", action="store_true", help="Не сохранять результаты в SQLite")
    ap.add_argument("--csv", metavar="FILE", help="Выгрузить результат в CSV")
    ap.add_argument("--json", metavar="FILE", help="Выгрузить результат в JSON")
    ap.add_argument("--stats", action="store_true", help="Показать статистику по базе и выйти")
    ap.add_argument("--publish", action="store_true",
                    help="После парсинга опубликовать новые объявления в сообщество VK")
    ap.add_argument("--publish-dry-run", action="store_true",
                    help="Собрать тексты и вложения VK-постов, ничего не публикуя")
    ap.add_argument("--publish-limit", type=int, default=10,
                    help="Сколько постов максимум за один подход (по умолчанию 10)")
    ap.add_argument("-v", "--verbose", action="store_true", help="Отладочный уровень логов")
    return ap


def print_ads(ads: list[dict], with_photos: bool, show_source: bool = False) -> None:
    print("\n" + "=" * 72)
    for ad in ads:
        print(f"[{ad['avito_id']}] {ad.get('title', '')}")
        print(f"    цена: {ad.get('price') or '—'} | {ad.get('url')}")
        if show_source and ad.get("source_url"):
            print(f"    источник: {source_label(ad['source_url'])}")
        if ad.get("location"):
            print(f"    регион: {ad['location']}")
        description = (ad.get("description") or "").strip()
        if description:
            preview = description[:220].replace("\n", " ")
            print(f"    описание: {preview}{'…' if len(description) > 220 else ''}")
        if ad.get("images"):
            print(f"    фото на сайте: {len(ad['images'])}")
        if with_photos and ad.get("photo_files"):
            print(f"    скачано файлов: {len(ad['photo_files'])} → {ad['photo_files'][0]}")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config.load()

    if args.verbose:
        config.parser.log_level = "DEBUG"
    if args.max_photos:
        config.parser.max_photos = max(1, min(args.max_photos, 10))
    if args.sample:
        config.parser.details_sample = args.sample
    if args.pages:
        config.parser.pages = args.pages

    setup_logging(config.parser.log_level, config.parser.log_file)
    logger = get_logger("avito.main")

    # режим «просто посмотреть базу»
    if args.stats:
        with Database(config.parser) as db:
            print(json.dumps(db.stats(), ensure_ascii=False, indent=2))
            for ad in db.get_unposted(limit=10):
                print(f"  не опубликовано: [{ad['avito_id']}] {ad['title'][:60]}")
        return 0

    if args.urls_file:
        config.parser.sources_file = Path(args.urls_file)
    if args.urls:
        config.parser.set_sources(args.urls)

    urls = config.parser.sources()
    if not urls:
        logger.error("Не задано ни одной ссылки: укажите URL, AVITO_TARGET_URL или SOURCES_FILE")
        return 2

    print(f"Отслеживаю {len(urls)} ссылк(и):")
    for index, item in enumerate(urls, 1):
        print(f"  {index}. {item}")

    all_ads: list[dict] = []
    cycle = 0
    interrupted = False
    try:
        with AvitoScraper(config, headless=args.headless, save_to_db=not args.no_db) as scraper:
            while True:
                cycle += 1
                if cycle > 1:
                    print(f"\n=== Цикл {cycle} ===")
                ads = scraper.scrape(
                    url=urls,
                    pages=args.pages or config.parser.pages,
                    with_details=args.details,
                    with_photos=args.photos,
                    only_new=args.only_new,
                    limit=args.limit,
                )
                all_ads.extend(ads)
                print_ads(ads, with_photos=args.photos, show_source=len(urls) > 1)
                if args.publish or args.publish_dry_run:
                    print("\n→ Постинг в сообщество VK:")
                    results = publish_results(
                        config, args.publish_limit, args.publish_dry_run
                    )
                    report_publish(results, args.publish_dry_run)
                if not args.watch:
                    break
                print(f"\nСледующий опрос через {args.watch} сек (Ctrl+C — выход)…")
                time.sleep(max(5, args.watch))
    except KeyboardInterrupt:
        interrupted = True
        print("\nОстановлено пользователем.")

    print(f"\nЦиклов выполнено: {cycle}; объявлений обработано: {len(all_ads)}")
    if not args.no_db:
        with Database(config.parser) as db:
            print(f"Статистика базы: {json.dumps(db.stats(), ensure_ascii=False)}")
            for source in db.list_sources():
                print(f"  {source['url']} → найдено {source['last_found']}, "
                      f"новых {source['last_new']}, всего {db.ads_by_source(source['url'])}, "
                      f"прогонов {source['runs']} ({source['last_status']})")

    if all_ads:
        if args.csv:
            save_to_csv(all_ads, args.csv)
        if args.json:
            save_to_json(all_ads, args.json)

    if not all_ads and not args.watch and not interrupted:
        print("\nНовых объявлений не найдено (или страница недоступна).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
