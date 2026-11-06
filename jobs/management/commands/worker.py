"""Воркер ручных задач: парсинг и публикация.

Запуск: python manage.py worker
В Docker — отдельный сервис worker.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import JobRun
from jobs.handlers import run_job


class Command(BaseCommand):
    help = "Выполнять ручные задачи парсинга и публикации из очереди"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Выполнить одну задачу и выйти")
        parser.add_argument("--poll", type=float, default=2.0, help="Пауза между опросами, сек")

    def handle(self, *args, **options):
        # После падения воркера задача не должна навсегда остаться «выполняется».
        stale = JobRun.objects.filter(status=JobRun.STATUS_RUNNING).update(
            status=JobRun.STATUS_ERROR,
            error="Воркер был перезапущен во время выполнения задачи. Запустите её снова.",
            finished_at=timezone.now(),
        )
        if stale:
            self.stdout.write(f"Помечено прерванных задач: {stale}")

        self.stdout.write("Воркер запущен. Ctrl+C — остановить.")
        while True:
            job = self._claim()
            if job is None:
                if options["once"]:
                    return
                time.sleep(max(0.5, float(options["poll"])))
                continue
            run_job(job)
            if options["once"]:
                return

    @staticmethod
    def _claim() -> JobRun | None:
        candidate = JobRun.objects.filter(status=JobRun.STATUS_QUEUED).order_by("created_at").first()
        if not candidate:
            return None
        # Атомарный захват: если второй воркер успел раньше, update вернёт 0.
        claimed = JobRun.objects.filter(pk=candidate.pk, status=JobRun.STATUS_QUEUED).update(
            status=JobRun.STATUS_RUNNING,
            started_at=timezone.now(),
        )
        if not claimed:
            return None
        return JobRun.objects.get(pk=candidate.pk)
