from unittest.mock import patch

from django.test import TestCase

from .models import Ad, AvitoSource
from .services import parse_listing


class ParseListingTests(TestCase):
    @patch("avito.services.AvitoClient")
    def test_upsert_is_idempotent(self, client_cls):
        client = client_cls.return_value
        client.fetch_listing.return_value = [
            {"avito_id": "1234567", "url": "https://www.avito.ru/a_1234567",
             "title": "Авто", "price_text": "100 ₽", "price_rub": 100,
             "location": "Москва", "card_image": "", "listing_position": 1},
            {"avito_id": "1234568", "url": "https://www.avito.ru/a_1234568",
             "title": "Дом", "price_text": "200 ₽", "price_rub": 200,
             "location": "Москва", "card_image": "", "listing_position": 2},
        ]
        source = AvitoSource.objects.create(url="https://www.avito.ru/moskva", city="Москва")
        from core.models import JobRun

        job = JobRun.objects.create(kind=JobRun.KIND_PARSE_LISTING, params={"source_id": source.pk})
        self.assertEqual(parse_listing(source, job), 2)
        self.assertEqual(Ad.objects.count(), 2)
        self.assertEqual(job.result["created"], 2)

        # Повторный парсинг той же страницы не должен создавать дубли.
        client.fetch_listing.return_value[0]["title"] = "Авто обновлено"
        self.assertEqual(parse_listing(source, job), 2)
        self.assertEqual(Ad.objects.count(), 2)
        self.assertEqual(Ad.objects.get(avito_id="1234567").title, "Авто обновлено")
        self.assertEqual(Ad.objects.get(avito_id="1234567").detail_status, Ad.DETAIL_CARD)
