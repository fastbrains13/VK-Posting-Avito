"""Пакет парсера Авито + постинга ВК (ТЗ: Парсер авито + постинг ВК).

Модули:
    config    — настройки из окружения (.env)
    logger    — логирование
    browser   — запуск Chrome с обходом детекта автоматизации, UA-ротация, прокси
    human     — имитация поведения человека
    scraper   — парсинг выдачи и страниц объявлений (Selenium)
    photos    — скачивание фотографий объявления
    database  — SQLite avito.db, дедупликация
    export    — выгрузка в CSV/JSON
    vk_publisher — публикация объявлений в сообщество ВКонтакте
"""

from .config import CONFIG, BrowserConfig, Config, ParserConfig, VkConfig
from .database import Database
from .scraper import AvitoScraper, extract_ad_id, parse_price
from .vk_publisher import VKPublisher, VkError

__all__ = ["CONFIG", "BrowserConfig", "Config", "ParserConfig", "VkConfig", "Database",
           "AvitoScraper", "extract_ad_id", "parse_price", "VKPublisher", "VkError"]
__version__ = "0.1.0"
