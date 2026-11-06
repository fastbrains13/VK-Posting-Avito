"""Проверка VK-флоу на заглушке api.vk.com: загрузка фото, пост, ошибки.

Запуск: python tests/vk_flow_test.py

Реального ключа пока нет, поэтому подменяем requests.Session фиктивным клиентом,
который отвечает ровно теми формами, что отдаёт VK (включая старые варианты ответа).
"""
import sys
from pathlib import Path

# запуск из любого места: корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from avito_parser.config import Config
from avito_parser.database import Database
from avito_parser.vk_publisher import VKPublisher, VkCaptchaRequired, VkPublishLimit, VkError

CALLS = []


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeSession:
    """Эмулирует VK API; scenario задаёт поведение posts.add / загрузки фото."""

    def __init__(self, scenario="ok"):
        self.headers = {"User-Agent": "fake"}
        self.proxies = {}
        self.scenario = scenario
        self.upload_hits = 0

    def close(self) -> None:
        pass

    def post(self, url, data=None, files=None, timeout=None):
        method = url.rsplit("/", 1)[-1]
        CALLS.append((method, sorted(data or {}), bool(files)))
        if "upload.php" in url:
            self.upload_hits += 1
            if self.scenario == "dup_photo":
                return FakeResponse({"error_code": 107, "error_msg": "Duplicate image"})
            return FakeResponse({"photo": "12345abcdef", "server": 2152, "hash": "deadbeef"})
        if method == "groups.getById":
            group = {"id": 1900123456, "name": "Авто из Авито",
                     "screen_name": "avito_auto", "is_admin": 1}
            if self.scenario == "user_token":
                # ключ standalone-приложения: response в форме {count, items}
                return FakeResponse({"response": {"count": 1, "items": [group]}})
            return FakeResponse({"response": {"groups": [group]}})
        if method == "photos.getWallUploadServer":
            return FakeResponse({"response": {"upload_url": "https://pu.vk.com/upload.php?act=do_add",
                                              "user_id": 1900123456, "album_id": -1900123456}})
        if method == "photos.saveWallPhoto":
            if self.scenario == "user_token":
                # так отвечает VK на user-ключ: массив готовых объектов фото
                return FakeResponse({"response": [{"id": 100200, "owner_id": -1900123456,
                                                   "album_id": -1900123456, "photo_807": "https://pp"}]})
            if self.scenario == "legacy":
                # старый плоский формат без owner_id
                return FakeResponse({"response": [{"aid": -1900123456, "pid": 100200,
                                                   "photo": "https://pp/x.jpg", "hash": "deadbeef"}]})
            return FakeResponse({"response": {"count": 1,
                                              "items": [{"id": 100200, "owner_id": -1900123456}]}})
        if method == "wall.post":
            if self.scenario == "captcha":
                return FakeResponse({"error": {"error_code": 14, "error_msg": "Captcha needed",
                                               "error_data": {"captcha_sid": "999",
                                                              "captcha_img": "https://vk.com/cap"}}})
            if self.scenario == "spam":
                return FakeResponse({"error": {"error_code": 902, "error_msg": "Spam restricted"}})
            if self.scenario == "flood":
                if len([c for c in CALLS if c[0] == "wall.post"]) < 2:
                    return FakeResponse({"error": {"error_code": 6, "error_msg": "Too many requests"}})
            return FakeResponse({"response": {"post_id": 77}})
        raise AssertionError("неожиданный вызов " + method)


def fresh(scenario):
    cfg = Config.load()
    cfg.vk.access_token = "t" * 20
    cfg.vk.group_id = "avito_auto"
    cfg.vk.min_interval_sec = 0
    cfg.vk.require_photos = True
    db = Database(cfg.parser, db_path=Path("/tmp/vk_test.db"))
    pub = VKPublisher(cfg, db)
    pub.session = FakeSession(scenario)
    return cfg, db, pub


def make_ad(photo_files, ad_id="8309226157"):
    return {
        "avito_id": ad_id, "title": "Mercedes-Benz SL-класс AMG 4.0 AT, 2026",
        "price": "25900000", "price_rub": 25900000,
        "url": "https://www.avito.ru/moskva/avtomobili/mercedes_8309226157",
        "location": "м. Динамо", "description": "Описание " * 400,
        "photo_files": photo_files, "images": [], "status": "complete",
    }


real_photos = sorted(str(p) for p in Path("data/photos").glob("*/*.jpg"))[:3]
print("тестовые фото:", len(real_photos))

# 1. успешный пост
CALLS.clear()
cfg, db, pub = fresh("ok")
db.save_ad(make_ad(real_photos))
res = pub.post_ad(make_ad(real_photos))
print("\n[ok]", res.as_dict())
assert res.ok and res.post_id == "77", res
assert res.post_url == "https://vk.com/wall-1900123456_77", res.post_url
assert len(res.attachments) == 3 and res.attachments[0] == "photo-1900123456_100200"
row = db.get_ad("8309226157")
assert row["posted_to_vk"] == 1 and row["vk_post_url"] == res.post_url, row
assert CALLS[0][0] == "groups.getById" and "access_token" in CALLS[0][1]
upload_call = [c for c in CALLS if c[2]][0]
assert not upload_call[1], "в загрузку фото не должен попадать access_token"
print("отметка в БД:", row["posted_to_vk"], row["vk_post_id"], "| текст поста:", len(res.message), "знаков")
pub.close(); db.close()

# 2. дубликат фото не роняет пост: снимок пропускается, пост уходит без вложений
CALLS.clear()
cfg, db, pub = fresh("dup_photo")
cfg.vk.require_photos = False
out = pub.post_ad(make_ad(real_photos))
print("\n[dup_photo]", {k: v for k, v in out.as_dict().items() if k != "message"})
assert out.ok and out.attachments == [], out
assert len([c for c in CALLS if c[0] == "wall.post"]) == 1, "повтор загрузки после дубля не нужен"
pub.close(); db.close()

# 2b. тот же случай, но с VK_REQUIRE_PHOTOS=True — пост осознанно пропускается
CALLS.clear()
cfg, db, pub = fresh("dup_photo")
out = pub.post_ad(make_ad(real_photos))
print("[dup_photo + require_photos]", out.skipped)
assert not out.ok and "фотограф" in out.skipped and not [c for c in CALLS if c[0] == "wall.post"]
pub.close(); db.close()

# 3. капча: падаем с понятной ошибкой
cfg, db, pub = fresh("captcha")
try:
    pub.post_ad(make_ad(real_photos))
    raise AssertionError("ожидался VkCaptchaRequired")
except VkCaptchaRequired as exc:
    print("\n[captcha]", exc, "| sid", exc.captcha_sid, "| img", exc.captcha_img)
pub.close(); db.close()

# 4. спам-ограничение: publish_pending останавливает пачку
CALLS.clear()
cfg, db, pub = fresh("spam")
db.save_ad(make_ad(real_photos, ad_id="9000000001"), update=True)
pub.db = db
results = pub.publish_pending(limit=5)
print("\n[spam]", [r.as_dict() for r in results])
assert results and not results[0].ok and "Spam" in results[0].error, results
assert db.get_ad("9000000001")["posted_to_vk"] == 0, "неудачный пост не должен отмечаться опубликованным"
pub.close(); db.close()

# 5. флуд-контроль: повтор внутри _call
CALLS.clear()
cfg, db, pub = fresh("flood")
pub._group_id = 1
res = pub.post_ad(make_ad(real_photos))
print("\n[flood]", res.as_dict(), "| вызовов wall.post:", len([c for c in CALLS if c[0] == "wall.post"]))
assert res.ok and len([c for c in CALLS if c[0] == "wall.post"]) == 2
pub.close(); db.close()

# 6. dry-run не дергает сеть вообще
CALLS.clear()
cfg, db, pub = fresh("ok")
res = pub.post_ad(make_ad(real_photos), dry_run=True)
print("\n[dry-run]", res.as_dict())
assert CALLS == [] and res.ok, CALLS
pub.close(); db.close()

# 7. нет токена — понятная ошибка, а не Traceback
cfg, db, pub = fresh("ok")
cfg.vk.access_token = ""
try:
    pub.resolve_group()
    raise AssertionError("ожидался VkError")
except VkError as exc:
    print("\n[без токена]", exc)
pub.close(); db.close()

# 8. user-ключ standalone-приложения: groups.getById через items, saveWallPhoto массивом
CALLS.clear()
cfg, db, pub = fresh("user_token")
res = pub.post_ad(make_ad(real_photos))
print("\n[user_token]", {k: v for k, v in res.as_dict().items() if k != "message"})
assert res.ok and res.attachments[0] == "photo-1900123456_100200", res
assert res.post_url == "https://vk.com/wall-1900123456_77", res.post_url
pub.close(); db.close()

# 9. старый плоский ответ saveWallPhoto без owner_id — берём id сообщества
CALLS.clear()
cfg, db, pub = fresh("legacy")
res = pub.post_ad(make_ad(real_photos))
print("[legacy]", res.attachments[:1], res.post_url)
assert res.ok and res.attachments[0] == "photo-1900123456_100200", res
pub.close(); db.close()

print("\nВСЕ ПРОВЕРКИ ПРОШЛИ")
