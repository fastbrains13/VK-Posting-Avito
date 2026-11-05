"""Логирование: консоль + файл.

Все логгеры проекта живут в ветке `avito.*`, поэтому обработчики вешаются один раз
на родительский логгер `avito` (setup_logging), а get_logger лишь возвращает дочерний.
Так уровень и файл лога задаются из конфигурации до начала парсинга.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT_LOGGER_NAME = "avito"
_configured = False


def setup_logging(level: str = "INFO", log_file: Path | str | None = None) -> logging.Logger:
    """Идемпотентно настроить обработчики: консоль + (опционально) файл.

    Можно вызывать сколько угодно раз — дубликаты хендлеров не появляются,
    а при смене пути лога файловый хендлер пересоздаётся.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    has_stream = any(h for h in root.handlers
                     if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler))
    if not has_stream:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(formatter)
        root.addHandler(stream)

    wanted = Path(log_file).resolve() if log_file else None
    current_files = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    current = Path(current_files[0].baseFilename).resolve() if current_files else None

    if wanted != current:
        for handler in current_files:
            handler.close()
            root.removeHandler(handler)
        if wanted:
            try:
                wanted.parent.mkdir(parents=True, exist_ok=True)
                file_handler = logging.FileHandler(wanted, encoding="utf-8")
                file_handler.setFormatter(formatter)
                root.addHandler(file_handler)
            except OSError:
                root.warning("Не удалось открыть файл лога %s", log_file)

    global _configured
    _configured = True
    return root


def get_logger(name: str = "avito.parser", level: str | None = None,
               log_file: Path | str | None = None) -> logging.Logger:
    """Вернуть логгер; при первом обращении инициализировать обработчики."""
    if not _configured:
        setup_logging(level or "INFO", log_file)
    logger = logging.getLogger(name)
    if level:
        logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    return logger
