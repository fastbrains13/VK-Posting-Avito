"""Исполнение ручных фоновых задач."""

from __future__ import annotations

import logging
import traceback

from django.utils import timezone

from avito.client import AvitoError
from avito.models import Ad, AvitoSource
from avito.services import ParseError, parse_detail, parse_listing
from core.models import JobRun
from publishing.services import PublishTooSoon, ServiceError, publish_publication
from publishing.vk import VKError

logger = logging.getLogger("jobs.handlers")


def run_job(job: JobRun) -> None:
    """Выполнить задачу, обновляя её статус и журнал."""
    job.status = JobRun.STATUS_RUNNING
    job.started_at = job.started_at or timezone.now()
    job.save(update_fields=["status", "started_at"])
    logger.info("Задача %s (%s) запущена", job.pk, job.kind)
    try:
        if job.kind == JobRun.KIND_PARSE_LISTING:
            source = AvitoSource.objects.get(pk=job.params.get("source_id"))
            parse_listing(source, job)
        elif job.kind == JobRun.KIND_PARSE_DETAIL:
            ad = Ad.objects.get(pk=job.params.get("ad_id"))
            parse_detail(ad, job)
        elif job.kind == JobRun.KIND_PUBLISH:
            publication_id = int(job.params.get("publication_id") or 0)
            if not publication_id:
                raise ServiceError("В задаче публикации нет publication_id")
            publish_publication(publication_id, job)
        else:
            raise ServiceError(f"Неизвестный тип задачи: {job.kind}")
    except (ParseError, ServiceError, PublishTooSoon, AvitoError, VKError) as exc:
        job.status = JobRun.STATUS_ERROR
        job.error = str(exc)[:4000]
        job.append_log(f"Ошибка: {exc}")
        logger.warning("Задача %s завершилась ошибкой: %s", job.pk, exc)
    except Exception as exc:
        job.status = JobRun.STATUS_ERROR
        job.error = f"{type(exc).__name__}: {exc}"[:4000]
        job.log = (job.log + "\n" if job.log else "") + traceback.format_exc()[-3000:]
        logger.exception("Задача %s упала", job.pk)
    else:
        job.status = JobRun.STATUS_DONE
        job.progress = job.progress or "Готово"
    finally:
        job.finished_at = timezone.now()
        job.save(update_fields=["status", "error", "log", "finished_at", "progress", "result"])
        logger.info("Задача %s завершена: %s", job.pk, job.status)
