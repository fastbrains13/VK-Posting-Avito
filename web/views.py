"""Представления MVP v0. Только ручные действия и серверный рендеринг."""

from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from avito.models import Ad, AdPhoto, AvitoSource
from core.crypto import TokenCipherError
from core.models import JobRun, ProxyEndpoint, VKAccount, VKCommunity
from core.proxies import ProxyParseError, add_proxy_lines, recheck_all, recheck_proxy
from publishing.models import Publication
from publishing.renderer import build_message
from publishing.services import (
    PublishTooSoon,
    ServiceError,
    active_community,
    connect_account,
    create_publish_job,
    publication_for,
    select_community,
    set_community_token,
)
from publishing.vk import VKClient, VKError

from .forms import SourceForm, VKTokenForm

logger = logging.getLogger("web.views")


def _account() -> VKAccount | None:
    return VKAccount.objects.first()


def _community() -> VKCommunity | None:
    return active_community()


@login_required
def dashboard(request):
    community = _community()
    source = AvitoSource.objects.first()
    ads_count = Ad.objects.count()
    posted_count = Publication.objects.filter(status=Publication.STATUS_POSTED).count()
    jobs = JobRun.objects.all()[:8]
    return render(request, "web/dashboard.html", {
        "community": community,
        "account": _account(),
        "source": source,
        "ads_count": ads_count,
        "posted_count": posted_count,
        "jobs": jobs,
        "title": "Обзор",
    })


@login_required
def connect(request):
    account = _account()
    form = VKTokenForm()
    communities = request.session.get("vk_communities", [])

    if request.method == "POST":
        action = request.POST.get("action", "token")
        if action == "token":
            form = VKTokenForm(request.POST)
            if form.is_valid():
                try:
                    account, communities = connect_account(form.cleaned_data["token"])
                except (ServiceError, VKError, TokenCipherError) as exc:
                    messages.error(request, f"Не удалось подключить токен: {exc}")
                else:
                    request.session["vk_communities"] = communities
                    messages.success(request, "Токен проверен. Выберите сообщество.")
                    return redirect("web:connect")
        elif action == "refresh" and account:
            try:
                communities = VKClient(account.token).list_admin_communities()
            except (VKError, TokenCipherError) as exc:
                messages.error(request, f"Не удалось обновить список: {exc}")
            else:
                request.session["vk_communities"] = communities
                messages.success(request, f"Загружено сообществ: {len(communities)}.")
                return redirect("web:connect")
        elif action == "community" and account:
            raw_group_id = request.POST.get("group_id", "")
            try:
                group_id = int(raw_group_id)
            except (TypeError, ValueError):
                messages.error(request, "Некорректный id сообщества.")
            else:
                try:
                    community, warnings = select_community(account, group_id)
                except (ServiceError, VKError, TokenCipherError) as exc:
                    messages.error(request, f"Сообщество не выбрано: {exc}")
                else:
                    for warning in warnings:
                        messages.warning(request, warning)
                    messages.success(request, f"Сообщество «{community.name}» выбрано.")
                    return redirect("web:connect")
        elif action == "community_token":
            community = _community()
            if not community:
                messages.error(request, "Сначала выберите сообщество.")
            else:
                try:
                    set_community_token(community, request.POST.get("community_token", ""))
                except (ServiceError, VKError, TokenCipherError) as exc:
                    messages.error(request, f"Ключ сообщества не сохранён: {exc}")
                else:
                    messages.success(request, "Ключ сообщества сохранён для wall.post.")
                    return redirect("web:connect")

    community = _community()
    return render(request, "web/connect.html", {
        "form": form,
        "account": account,
        "communities": communities,
        "community": community,
        "title": "Подключение VK",
    })


@login_required
def source_view(request):
    source = AvitoSource.objects.first()
    form = SourceForm(request.POST or None, instance=source)
    if request.method == "POST" and form.is_valid():
        source = form.save()
        messages.success(request, "Источник сохранён. Теперь загрузите объявления.")
        return redirect("web:sources")
    community = _community()
    return render(request, "web/sources.html", {
        "form": form,
        "source": source,
        "community": community,
        "title": "Источник Авито",
    })


@login_required
@require_POST
def parse_source(request):
    source = AvitoSource.objects.first()
    if not source:
        messages.error(request, "Сначала добавьте ссылку на выдачу Авито.")
        return redirect("web:sources")
    job = JobRun.objects.create(
        kind=JobRun.KIND_PARSE_LISTING,
        params={"source_id": source.pk},
    )
    messages.info(request, "Загружаю объявления. Это может занять до минуты.")
    return redirect("web:job_detail", job_id=job.pk)


@login_required
def ads(request):
    community = _community()
    if not community:
        messages.info(request, "Сначала подключите и выберите сообщество VK.")
        return redirect("web:connect")
    source = AvitoSource.objects.first()
    items = list(Ad.objects.filter(source=source).order_by("listing_position", "id")) if source else []
    pub_map = {
        pub.ad_id: pub
        for pub in Publication.objects.filter(community=community, ad__in=items)
    }
    # Для списка предпочитаем локальное фото: внешние URL Авито иногда
    # не отдаются браузеру, а скачанные уже лежат у нас.
    thumb_map: dict[int, AdPhoto] = {}
    for photo in AdPhoto.objects.filter(ad__in=items, status=AdPhoto.STATUS_DOWNLOADED).order_by("ad_id", "position"):
        thumb_map.setdefault(photo.ad_id, photo)
    for ad in items:
        ad.publication = pub_map.get(ad.pk)
        photo = thumb_map.get(ad.pk)
        ad.thumbnail_url = f"/photos/{photo.pk}/" if photo else ad.card_image
    return render(request, "web/ads.html", {
        "items": items,
        "source": source,
        "community": community,
        "title": "Объявления",
    })


@login_required
def ad_detail(request, ad_id: int):
    ad = get_object_or_404(Ad, pk=ad_id)
    community = _community()
    publication = publication_for(ad, community) if community else None
    message = publication.message if publication and publication.message else build_message(ad)
    wait = community.seconds_until_next_post() if community else 0
    return render(request, "web/ad_detail.html", {
        "ad": ad,
        "community": community,
        "publication": publication,
        "message": message,
        "wait": wait,
        "title": ad.title or f"Объявление {ad.avito_id}",
    })


@login_required
@require_POST
def prepare_ad(request, ad_id: int):
    ad = get_object_or_404(Ad, pk=ad_id)
    job = JobRun.objects.create(
        kind=JobRun.KIND_PARSE_DETAIL,
        params={"ad_id": ad.pk},
    )
    messages.info(request, "Загружаю описание и фотографии объявления.")
    return redirect("web:job_detail", job_id=job.pk)


@login_required
@require_POST
def publish_ad(request, ad_id: int):
    ad = get_object_or_404(Ad, pk=ad_id)
    community = _community()
    if not community:
        messages.error(request, "Сначала выберите сообщество VK.")
        return redirect("web:connect")
    if not ad.detail_loaded:
        messages.error(request, "Сначала загрузите описание и фотографии объявления.")
        return redirect("web:ad_detail", ad_id=ad.pk)
    try:
        job = create_publish_job(ad, community)
    except (ServiceError, PublishTooSoon) as exc:
        messages.error(request, str(exc))
        return redirect("web:ad_detail", ad_id=ad.pk)
    messages.info(request, "Публикую пост. Это может занять до минуты.")
    return redirect("web:job_detail", job_id=job.pk)


@login_required
@login_required
def settings_view(request):
    community = _community()
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "add_proxies":
            try:
                result = add_proxy_lines(request.POST.get("proxies", ""))
            except ProxyParseError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Прокси проверены: работают {result['ok']}, не работают {result['bad']}. "
                    f"Добавлено рабочих: {result['added']}, обновлено: {result['updated']}. "
                    "Нерабочие новые прокси в базу не добавлены.",
                )
                for error in result["errors"][:8]:
                    messages.warning(request, error)
            return redirect("web:settings")
        if action == "check_all":
            result = recheck_all()
            messages.success(
                request,
                f"Проверено {result['total']}: работают {result['ok']}, не работают {result['bad']}.",
            )
            return redirect("web:settings")
        if action == "delete_bad":
            count, _ = ProxyEndpoint.objects.filter(status=ProxyEndpoint.STATUS_BAD).delete()
            messages.success(request, f"Удалено нерабочих прокси: {count}.")
            return redirect("web:settings")
        if action == "check_proxy":
            proxy = ProxyEndpoint.objects.filter(pk=request.POST.get("proxy_id")).first()
            if not proxy:
                messages.error(request, "Прокси не найден.")
            else:
                ok, error = recheck_proxy(proxy)
                if ok:
                    messages.success(request, f"Прокси {proxy.display} работает.")
                else:
                    messages.error(request, f"Прокси {proxy.display} не работает: {error}")
            return redirect("web:settings")
        if action == "toggle_proxy":
            proxy = ProxyEndpoint.objects.filter(pk=request.POST.get("proxy_id")).first()
            if proxy:
                proxy.is_active = not proxy.is_active
                proxy.save(update_fields=["is_active", "updated_at"])
            return redirect("web:settings")
        if action == "delete_proxy":
            ProxyEndpoint.objects.filter(pk=request.POST.get("proxy_id")).delete()
            return redirect("web:settings")
        if action == "save_community" and community:
            try:
                interval = max(30, min(86400, int(request.POST.get("min_interval_sec") or 240)))
                max_photos = max(1, min(10, int(request.POST.get("max_photos") or 10)))
            except ValueError:
                messages.error(request, "Интервал и количество фото должны быть числами.")
            else:
                community.min_interval_sec = interval
                community.max_photos = max_photos
                community.require_photos = bool(request.POST.get("require_photos"))
                community.save(update_fields=["min_interval_sec", "max_photos",
                                              "require_photos", "updated_at"])
                messages.success(request, "Настройки сообщества сохранены.")
            return redirect("web:settings")

    proxies = list(ProxyEndpoint.objects.all())
    return render(request, "web/settings.html", {
        "community": community,
        "proxies": proxies,
        "title": "Настройки",
    })


def publications(request):
    items = Publication.objects.select_related("ad", "community").order_by("-created_at")
    return render(request, "web/publications.html", {
        "items": items,
        "title": "Публикации",
    })


@login_required
def jobs(request):
    items = JobRun.objects.all()[:100]
    return render(request, "web/jobs.html", {"items": items, "title": "Задачи"})


def _next_url(job: JobRun) -> str:
    if job.kind == JobRun.KIND_PARSE_LISTING:
        return reverse("web:ads")
    if job.kind == JobRun.KIND_PARSE_DETAIL:
        ad_id = job.params.get("ad_id")
        return reverse("web:ad_detail", args=[ad_id]) if ad_id else reverse("web:ads")
    if job.kind == JobRun.KIND_PUBLISH:
        ad_id = job.params.get("ad_id")
        return reverse("web:ad_detail", args=[ad_id]) if ad_id else reverse("web:publications")
    return reverse("web:jobs")


@login_required
def job_detail(request, job_id: int):
    job = get_object_or_404(JobRun, pk=job_id)
    return render(request, "web/job_detail.html", {
        "job": job,
        "next_url": _next_url(job),
        "title": f"Задача #{job.pk}",
    })


@login_required
def job_status(request, job_id: int):
    job = get_object_or_404(JobRun, pk=job_id)
    return JsonResponse({
        "id": job.pk,
        "kind": job.kind,
        "kind_label": job.get_kind_display(),
        "status": job.status,
        "status_label": job.get_status_display(),
        "progress": job.progress,
        "error": job.error,
        "log": "\n".join(job.log.splitlines()[-80:]),
        "result": job.result,
        "finished": job.is_finished,
        "next_url": _next_url(job),
    })


@login_required
def photo(request, photo_id: int):
    item = get_object_or_404(AdPhoto, pk=photo_id)
    try:
        handle = item.file.open("rb")
    except (FileNotFoundError, ValueError):
        raise Http404("Фото не найдено") from None
    return FileResponse(handle, content_type=item.content_type or "image/jpeg")
