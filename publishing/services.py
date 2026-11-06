"""Сервисы подключения VK и публикации."""

from __future__ import annotations

import logging
import time

from django.utils import timezone

from avito.models import Ad
from core.crypto import TokenCipherError
from core.models import JobRun, ProxyEndpoint, VKAccount, VKCommunity
from core.proxies import pick_proxy

from .models import Publication
from .renderer import build_message
from .vk import VKClient, VKError, VKTemporaryPhotoLimit

logger = logging.getLogger("publishing.services")


class ServiceError(RuntimeError):
    pass


class PublishTooSoon(ServiceError):
    def __init__(self, seconds: int):
        self.seconds = max(1, int(seconds))
        super().__init__(f"Следующий пост можно опубликовать через {self.seconds} сек.")


def connect_account(raw_token: str) -> tuple[VKAccount, list[dict]]:
    """Проверить токен, сохранить аккаунт и вернуть список admin-сообществ."""
    token = (raw_token or "").strip()
    if not token:
        raise ServiceError("Вставьте пользовательский токен VK.")
    client = VKClient(token)
    try:
        user = client.validate()
        communities = client.list_admin_communities()
    except VKError as exc:
        account = VKAccount.objects.first()
        if account:
            account.mark_invalid(str(exc))
        raise

    account = VKAccount.objects.first() or VKAccount()
    try:
        old_token = account.token if account.pk else ""
    except TokenCipherError:
        old_token = ""
    changed = bool(account.pk) and old_token != token
    account.set_token(token)
    account.display_name = user.get("name") or account.display_name
    account.vk_user_id = user.get("id") or account.vk_user_id
    account.status = VKAccount.STATUS_ACTIVE
    account.error = ""
    account.last_checked_at = timezone.now()
    account.save()
    if changed:
        # Новый токен может принадлежать другому пользователю: старые
        # сообщества больше не считаем проверенными, пока их не выберут снова.
        account.communities.update(is_active=False, can_post=False, can_upload_photos=False)
    return account, communities


def select_community(account: VKAccount, group_id: int) -> tuple[VKCommunity, list[str]]:
    """Проверить сообщество, сохранить его и сделать активным."""
    warnings: list[str] = []
    client = VKClient(account.token)
    info = client.community_info(group_id)
    if not info.get("is_admin"):
        raise ServiceError("Вы не являетесь администратором этого сообщества. "
                           "MVP поддерживает только сообщества, где пользователь — админ.")
    can_upload = client.check_photo_capability(info["group_id"])
    if not can_upload:
        warnings.append(
            "Не удалось проверить загрузку фото. Убедитесь, что токен пользовательский "
            "и у него есть право photos, а вы админ сообщества."
        )
    community, _ = VKCommunity.objects.update_or_create(
        account=account,
        group_id=info["group_id"],
        defaults={
            "name": info.get("name") or f"Сообщество {info['group_id']}",
            "screen_name": info.get("screen_name") or "",
            "photo_url": info.get("photo_url") or "",
            "is_admin": True,
            "can_post": bool(info.get("can_post") or info.get("is_admin")),
            "can_upload_photos": can_upload,
            "is_active": True,
        },
    )
    return community, warnings


def active_community() -> VKCommunity | None:
    return VKCommunity.objects.filter(is_active=True).select_related("account").first()


def set_community_token(community: VKCommunity, raw_token: str) -> VKCommunity:
    """Сохранить ключ сообщества для wall.post.

    Ключ сообщества нельзя проверить через wall.get: VK отвечает
    «method is unavailable with group auth» (код 27). Поэтому сохраняем его
    без сетевой проверки; корректность выяснится при первой публикации.
    """
    token = (raw_token or "").strip()
    community.set_community_token(token)
    community.community_token_checked_at = None
    community.save(update_fields=["community_token_encrypted", "community_token_mask",
                                  "community_token_last4", "community_token_checked_at",
                                  "updated_at"])
    return community


def build_publication(ad: Ad, community: VKCommunity) -> Publication:
    publication, created = Publication.objects.get_or_create(ad=ad, community=community)
    if created or not publication.message:
        publication.message = build_message(ad)
        publication.save(update_fields=["message", "updated_at"])
    return publication


def create_publish_job(ad: Ad, community: VKCommunity) -> JobRun:
    """Поставить ручную публикацию в очередь. Повтор для опубликованного запрещён."""
    if not community.can_post:
        raise ServiceError("У сообщества нет подтверждённого права на публикацию.")
    if not community.can_upload_photos:
        raise ServiceError(
            "У сообщества не подтверждена загрузка фото. Добавьте пользовательский токен "
            "с правом photos и права администратора."
        )
    publication = build_publication(ad, community)
    if publication.is_posted:
        raise ServiceError("Это объявление уже опубликовано в этом сообществе.")
    if JobRun.objects.filter(
        kind=JobRun.KIND_PUBLISH,
        status__in=(JobRun.STATUS_QUEUED, JobRun.STATUS_RUNNING),
        params__publication_id=publication.pk,
    ).exists():
        raise ServiceError("Публикация этого объявления уже стоит в очереди.")
    wait = community.seconds_until_next_post()
    if wait > 0:
        raise PublishTooSoon(wait)
    job = JobRun.objects.create(
        kind=JobRun.KIND_PUBLISH,
        params={"publication_id": publication.pk, "ad_id": ad.pk, "community_id": community.pk},
    )
    return job


def _attach_photos(publication: Publication, job: JobRun, proxy: ProxyEndpoint | None = None) -> list[str]:
    community = publication.community
    ad = publication.ad

    # Повторная попытка после ошибки wall.post не должна заново загружать
    # те же фото: VK на повторную загрузку может вернуть пустой photo или 405.
    if publication.attachments:
        job.append_log(f"Использую ранее загруженные фото: {len(publication.attachments)}")
        return list(publication.attachments)

    photos = list(ad.photos.filter(status="downloaded").order_by("position", "id")[: community.max_photos])
    if not photos:
        if community.require_photos:
            raise ServiceError("У объявления нет скачанных фотографий, а сообщество требует фото.")
        return []

    client = VKClient(community.account.token, proxy=proxy)
    attachments: list[str] = []
    temporary: VKTemporaryPhotoLimit | None = None
    for index, photo in enumerate(photos):
        if index:
            # Не бомбим VK загрузками подряд: это провоцирует пустой photo/405.
            time.sleep(2.0)
        try:
            if not photo.file:
                continue
            attachment = client.upload_photo(community.group_id, photo.file.path)
        except VKTemporaryPhotoLimit as exc:
            temporary = exc
            job.append_log(f"Фото {photo.position} не загружено: {exc}")
            continue
        except VKError as exc:
            job.append_log(f"Фото {photo.position} не загружено: {exc}")
            continue
        if attachment:
            attachments.append(attachment)
            job.append_log(f"Фото {photo.position} загружено: {attachment}")
    if not attachments and community.require_photos:
        if temporary:
            raise ServiceError(str(temporary))
        raise ServiceError("Ни одно фото не удалось загрузить в VK.")
    return attachments


def publish_publication(publication_id: int, job: JobRun) -> Publication:
    """Опубликовать существующую Publication. Ретрай — та же запись, не новая."""
    publication = Publication.objects.select_related("ad", "community", "community__account").get(pk=publication_id)
    community = publication.community
    ad = publication.ad

    if publication.is_posted:
        job.append_log("Публикация уже выполнена, повтор не нужен.")
        return publication

    if not community.is_active or community.account.status != VKAccount.STATUS_ACTIVE:
        raise ServiceError("Сообщество или VK-аккаунт не активны. Проверьте подключение.")

    # Фото загружаются пользовательским токеном (community-токен не умеет
    # photos.getWallUploadServer), а wall.post — ключом сообщества, если он есть.
    proxy = pick_proxy()
    job.append_log(f"Прокси VK: {proxy.display if proxy else 'прямой IP'}")
    post_token = community.community_token if community.has_community_token else community.account.token
    post_client = VKClient(post_token, proxy=proxy)

    # Восстановление после падения: статус posting означает, что пост мог уйти.
    # wall.get делаем пользовательским токеном: ключ сообщества не умеет wall.get.
    if publication.status == Publication.STATUS_POSTING:
        found = VKClient(community.account.token, proxy=proxy).find_post_by_url(community.group_id, ad.url)
        if found:
            publication.mark_posted(str(found.get("id")), f"https://vk.com/wall-{community.group_id}_{found.get('id')}")
            community.last_post_at = timezone.now()
            community.save(update_fields=["last_post_at", "updated_at"])
            job.append_log("Пост уже был опубликован — восстановили статус без повтора.")
            return publication
        publication.status = Publication.STATUS_FAILED
        publication.save(update_fields=["status", "updated_at"])

    wait = community.seconds_until_next_post()
    if wait > 0:
        raise PublishTooSoon(wait)

    if not publication.message:
        publication.message = build_message(ad)
        publication.save(update_fields=["message", "updated_at"])

    try:
        attachments = _attach_photos(publication, job, proxy)
    except ServiceError as exc:
        publication.mark_failed(str(exc))
        raise
    publication.attachments = attachments
    publication.status = Publication.STATUS_POSTING
    publication.attempts += 1
    publication.error = ""
    publication.save(update_fields=["attachments", "status", "attempts", "error", "updated_at"])
    job.append_log("Публикую пост в VK…")

    try:
        result = post_client.post(
            community.group_id,
            publication.message,
            attachments,
            guid=str(publication.guid),
        )
    except VKError as exc:
        if proxy and exc.code == 0:
            proxy.mark_failure(str(exc))
        # Код 0 — сеть/неожиданный ответ: пост мог уйти. Оставляем posting,
        # чтобы следующая попытка сначала сверилась со стеной.
        if exc.code == 0:
            publication.status = Publication.STATUS_POSTING
            publication.error = str(exc)[:4000]
            publication.save(update_fields=["status", "error", "updated_at"])
        else:
            publication.mark_failed(str(exc))
        raise

    publication.mark_posted(result["post_id"], result["post_url"])
    community.last_post_at = timezone.now()
    community.save(update_fields=["last_post_at", "updated_at"])
    if proxy:
        proxy.mark_success()
    job.append_log(f"Опубликовано: {publication.vk_post_url}")
    return publication


def publication_for(ad: Ad, community: VKCommunity) -> Publication | None:
    return Publication.objects.filter(ad=ad, community=community).first()
