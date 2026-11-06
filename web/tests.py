from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from avito.models import Ad, AvitoSource
from core.crypto import encrypt_token
from core.models import JobRun, VKAccount, VKCommunity


class WebTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("admin", password="pass")
        self.client.force_login(self.user)
        self.account = VKAccount(token_encrypted=encrypt_token("token"))
        self.account.save()
        self.community = VKCommunity.objects.create(
            account=self.account, group_id=123, name="Тест", is_admin=True,
            can_post=True, can_upload_photos=True, is_active=True,
        )

    def test_login_required(self):
        self.client.logout()
        response = self.client.get(reverse("web:ads"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_dashboard_renders(self):
        response = self.client.get(reverse("web:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Порядок работы")

    def test_source_add_and_parse_job(self):
        response = self.client.post(reverse("web:sources"), {
            "url": "https://www.avito.ru/moskva/avtomobili",
            "city": "Москва",
            "title": "Авто",
        })
        self.assertEqual(response.status_code, 302)
        source = AvitoSource.objects.get()
        self.assertEqual(source.city, "Москва")
        response = self.client.post(reverse("web:parse_source"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(JobRun.objects.filter(kind=JobRun.KIND_PARSE_LISTING).count(), 1)

    def test_ad_detail_and_publish_requires_detail(self):
        source = AvitoSource.objects.create(url="https://www.avito.ru/moskva")
        ad = Ad.objects.create(
            source=source, avito_id="1234567", url="https://www.avito.ru/a_1234567",
            title="Авто", price_text="100 ₽",
        )
        response = self.client.get(reverse("web:ad_detail", args=[ad.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Загрузить описание и фото")

        response = self.client.post(reverse("web:publish_ad", args=[ad.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(JobRun.objects.count(), 0)

    def test_prepare_creates_job(self):
        source = AvitoSource.objects.create(url="https://www.avito.ru/moskva")
        ad = Ad.objects.create(source=source, avito_id="1234567",
                               url="https://www.avito.ru/a_1234567", title="Авто")
        response = self.client.post(reverse("web:prepare_ad", args=[ad.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(JobRun.objects.filter(kind=JobRun.KIND_PARSE_DETAIL).count(), 1)

    def test_job_status_json(self):
        job = JobRun.objects.create(kind=JobRun.KIND_PARSE_LISTING, params={})
        response = self.client.get(reverse("web:job_status", args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "queued")


class PageSmokeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("admin2", password="pass")
        self.client.force_login(self.user)
        self.account = VKAccount(token_encrypted=encrypt_token("token"))
        self.account.save()
        self.community = VKCommunity.objects.create(
            account=self.account, group_id=123, name="Тест", is_admin=True,
            can_post=True, can_upload_photos=True, is_active=True,
        )
        self.source = AvitoSource.objects.create(url="https://www.avito.ru/moskva", city="Москва")
        self.ad = Ad.objects.create(
            source=self.source, avito_id="7654321", url="https://www.avito.ru/a_7654321",
            title="Тестовое объявление", price_text="100 ₽", description="Описание",
            detail_status=Ad.DETAIL_LOADED,
        )

    def test_all_pages_render(self):
        urls = [
            reverse("web:dashboard"),
            reverse("web:connect"),
            reverse("web:sources"),
            reverse("web:ads"),
            reverse("web:ad_detail", args=[self.ad.pk]),
            reverse("web:publications"),
            reverse("web:jobs"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_job_page_renders(self):
        job = JobRun.objects.create(kind=JobRun.KIND_PARSE_DETAIL, params={"ad_id": self.ad.pk})
        response = self.client.get(reverse("web:job_detail", args=[job.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Журнал")


    def test_settings_page_and_add_proxy(self):
        from unittest.mock import patch

        from core.models import ProxyEndpoint

        response = self.client.get(reverse("web:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Единый пул для Авито и VK")
        with patch("core.proxies.check_proxy", return_value=(True, "")):
            response = self.client.post(reverse("web:settings"), {
                "action": "add_proxies", "proxies": "1.1.1.1:8080",
            }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProxyEndpoint.objects.count(), 1)
        self.assertContains(response, "1.1.1.1:8080")
