import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .vk import VKClient, VKError


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, data=None, files=None, timeout=None):
        self.calls.append((url, data, files))
        method = url.rsplit("/", 1)[-1]
        if method == "users.get":
            return FakeResponse({"response": [{"id": 1, "first_name": "Иван", "last_name": "Иванов"}]})
        if method == "groups.get":
            return FakeResponse({"response": {"count": 1, "items": [
                {"id": 123, "name": "Сообщество", "screen_name": "club123", "is_admin": 1}
            ]}})
        if method == "groups.getById":
            return FakeResponse({"response": {"groups": [
                {"id": 123, "name": "Сообщество", "screen_name": "club123", "is_admin": 1}
            ]}})
        if method == "photos.getWallUploadServer":
            return FakeResponse({"response": {"upload_url": "https://upload.example/upload.php"}})
        if "upload.example" in url:
            return FakeResponse({"photo": "photo-token", "server": 1, "hash": "hash"})
        if method == "photos.saveWallPhoto":
            return FakeResponse({"response": [{"id": 55, "owner_id": -123}]})
        if method == "wall.post":
            return FakeResponse({"response": {"post_id": 77}})
        if method == "wall.get":
            return FakeResponse({"response": {"count": 0, "items": []}})
        raise AssertionError(f"неожиданный вызов {url}")


class VKClientTests(SimpleTestCase):
    def setUp(self):
        self.client = VKClient("user-token")
        self.client.session = FakeSession()

    def test_validate_and_admin_communities(self):
        user = self.client.validate()
        self.assertEqual(user["id"], 1)
        self.assertEqual(user["name"], "Иван Иванов")
        groups = self.client.list_admin_communities()
        self.assertEqual(groups[0]["group_id"], 123)

    def test_post_uses_guid_and_group(self):
        result = self.client.post(123, "текст", ["photo-123_55"], "guid-1")
        self.assertEqual(result["post_id"], "77")
        self.assertEqual(result["post_url"], "https://vk.com/wall-123_77")
        call = [c for c in self.client.session.calls if c[0].endswith("wall.post")][0]
        self.assertEqual(call[1]["owner_id"], -123)
        self.assertEqual(call[1]["from_group"], 1)
        self.assertEqual(call[1]["guid"], "guid-1")

    def test_upload_photo_returns_attachment(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as handle:
            handle.write(b"jpeg")
            handle.flush()
            attachment = self.client.upload_photo(123, Path(handle.name))
        self.assertEqual(attachment, "photo-123_55")

    def test_photo_error_is_explained(self):
        class ErrorSession(FakeSession):
            def post(self, url, data=None, files=None, timeout=None):
                if url.endswith("photos.getWallUploadServer"):
                    return FakeResponse({"error": {"error_code": 27, "error_msg": "Group authorization failed"}})
                return super().post(url, data, files, timeout)

        self.client.session = ErrorSession()
        with tempfile.NamedTemporaryFile(suffix=".jpg") as handle:
            handle.write(b"jpeg")
            handle.flush()
            with self.assertRaises(VKError) as ctx:
                self.client.upload_photo(123, Path(handle.name))
        self.assertEqual(ctx.exception.code, 27)
        self.assertIn("27", str(ctx.exception))
