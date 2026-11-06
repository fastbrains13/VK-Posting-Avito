import tempfile
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from avito.models import Ad, AdPhoto, AvitoSource
from core.crypto import encrypt_token
from core.models import JobRun, VKAccount, VKCommunity
from publishing.models import Publication
from publishing.renderer import build_message, clean_multiline
from publishing.services import (
    PublishTooSoon,
    ServiceError,
    create_publish_job,
    publish_publication,
)


class FakeVK:
    uploads = 0
    posts = 0
    post_tokens = []

    def __init__(self, token, proxy=None):
        self.token = token
        self.proxy = proxy

    def upload_photo(self, group_id, path):
        FakeVK.uploads += 1
        return f"photo-{group_id}_1"

    def post(self, group_id, message, attachments, guid):
        FakeVK.posts += 1
        FakeVK.post_tokens.append(self.token)
        assert message
        assert attachments
        return {"post_id": "77", "post_url": f"https://vk.com/wall-{group_id}_77"}

    def find_post_by_url(self, group_id, url):
        return None


class PublishTests(TestCase):
    def setUp(self):
        FakeVK.uploads = 0
        FakeVK.posts = 0
        FakeVK.post_tokens = []
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.tmp)
        self.override.enable()
        self.account = VKAccount(token_encrypted=encrypt_token("token"))
        self.account.save()
        self.community = VKCommunity.objects.create(
            account=self.account, group_id=123, name="Тест", is_admin=True,
            can_post=True, can_upload_photos=True, is_active=True,
        )
        self.source = AvitoSource.objects.create(url="https://www.avito.ru/moskva")
        self.ad = Ad.objects.create(
            source=self.source, avito_id="1234567", url="https://www.avito.ru/a_1234567",
            title="Автомобиль", price_text="100 000 ₽", description="Описание",
            detail_status=Ad.DETAIL_LOADED,
        )
        photo = AdPhoto(ad=self.ad, position=1, status=AdPhoto.STATUS_DOWNLOADED)
        photo.file.save("1.jpg", SimpleUploadedFile("1.jpg", b"jpeg-bytes"), save=True)

    def tearDown(self):
        self.override.disable()

    @patch("publishing.services.VKClient", FakeVK)
    def test_publish_once_and_no_repeat(self):
        publication = Publication.objects.create(ad=self.ad, community=self.community)
        job = JobRun.objects.create(kind=JobRun.KIND_PUBLISH, params={})
        result = publish_publication(publication.pk, job)
        self.assertEqual(result.status, Publication.STATUS_POSTED)
        self.assertEqual(result.vk_post_id, "77")
        self.assertEqual(FakeVK.posts, 1)
        self.assertEqual(FakeVK.uploads, 1)
        self.assertIn(self.ad.url, result.message)

        # Повторный вызов возвращает уже опубликованную запись и не публикует снова.
        again = publish_publication(publication.pk, job)
        self.assertEqual(again.status, Publication.STATUS_POSTED)
        self.assertEqual(FakeVK.posts, 1)

    @patch("publishing.services.VKClient", FakeVK)
    def test_create_job_rejects_posted(self):
        publication = Publication.objects.create(ad=self.ad, community=self.community)
        job = JobRun.objects.create(kind=JobRun.KIND_PUBLISH, params={})
        publish_publication(publication.pk, job)
        with self.assertRaises(ServiceError):
            create_publish_job(self.ad, self.community)

    def test_create_job_rejects_too_soon(self):
        from django.utils import timezone

        self.community.last_post_at = timezone.now()
        self.community.save(update_fields=["last_post_at"])
        with self.assertRaises(PublishTooSoon):
            create_publish_job(self.ad, self.community)

    def test_publication_unique_per_community(self):
        from django.db import IntegrityError, transaction

        Publication.objects.create(ad=self.ad, community=self.community)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Publication.objects.create(ad=self.ad, community=self.community)


    def test_create_job_rejects_duplicate_queue(self):
        publication = Publication.objects.create(ad=self.ad, community=self.community)
        JobRun.objects.create(
            kind=JobRun.KIND_PUBLISH,
            params={"publication_id": publication.pk},
        )
        with self.assertRaises(ServiceError):
            create_publish_job(self.ad, self.community)


    @patch("publishing.services.VKClient", FakeVK)
    def test_wall_post_uses_community_token(self):
        self.community.set_community_token("community-token")
        self.community.save()
        publication = Publication.objects.create(ad=self.ad, community=self.community)
        job = JobRun.objects.create(kind=JobRun.KIND_PUBLISH, params={})
        publish_publication(publication.pk, job)
        self.assertEqual(FakeVK.post_tokens, ["community-token"])


class RendererTests(TestCase):
    def test_description_keeps_paragraphs_and_emoji(self):
        text = clean_multiline("Привет 👋<br><br>Первый абзац ✅\nВторой абзац 🚀")
        self.assertIn("👋", text)
        self.assertIn("Первый абзац ✅", text)
        self.assertIn("Второй абзац 🚀", text)
        self.assertIn("\n\n", text)

    def test_build_message_keeps_emoji_and_link(self):
        from avito.models import Ad

        ad = Ad(
            avito_id="1", title="Тест 🚀", price_text="100 ₽",
            description="Описание 👋\n\n• пункт 1\n• пункт 2",
            url="https://www.avito.ru/test_1",
        )
        message = build_message(ad)
        self.assertIn("🚀", message)
        self.assertIn("👋", message)
        self.assertIn("• пункт 1", message)
        self.assertIn("https://www.avito.ru/test_1", message)
