"""Проверка реестра настроек: приоритеты, типы, возврат к .env, форма админки.

Запуск: python tests/settings_test.py

Здесь нет ни браузера, ни сети — только Config (значения из окружения), база
настроек во временном файле и функции наложения из avito_parser/settings.py.
"""
import os
import sys
import tempfile
from pathlib import Path

# запуск из любого места: корень проекта в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# своё окружение, чтобы тест не зависел от .env разработчика
os.environ["VK_ACCESS_TOKEN"] = "group-token-from-env"
os.environ["ADMIN_PASSWORD"] = "password-from-env"
os.environ["HEADLESS_MODE"] = "True"
os.environ["DELAY_MIN"] = "2"
os.environ["MAX_RETRIES"] = "2"
os.environ["PROXY_STRING"] = ""

from avito_parser.browser import ProxySettings
from avito_parser.config import Config
from avito_parser.database import Database
from avito_parser.settings import (
    SETTING_KEYS,
    SPECS,
    apply_db_settings,
    browser_signature,
    coerce,
    current_value,
    effective_settings,
    overridden_keys,
    sanitize_for_storage,
    spec_for,
)

TMP = Path(tempfile.mkdtemp(prefix="avito_settings_"))
db = Database(db_path=TMP / "avito.db")


def fresh() -> Config:
    """Конфигурация «как после старта процесса»: только окружение."""
    return Config.load()


def save(**pairs: str) -> dict[str, str]:
    """Запись так же, как её делает POST /api/settings: нормализация и проверка чисел."""
    stored: dict[str, str] = {}
    for key, raw in pairs.items():
        spec = spec_for(key)
        text = sanitize_for_storage(spec, raw)
        if spec.kind in ("int", "float") and text and coerce(spec, text) is None:
            continue                      # не-число в базу не уходит: UI получит 400
        stored[key] = text
    db.settings_bulk(stored)
    return stored


# 1. без строк в базе настройки не трогают значения из окружения
cfg = apply_db_settings(fresh(), db)
assert cfg.browser.headless is True, cfg.browser.headless
assert cfg.parser.target_url == "", "ссылка для парсинга больше не читается из окружения"
assert cfg.parser.sources() == [], "без источников парсить нечего"

# 2. сохранённое значение перекрывает .env
save(**{
    "headless": "0",
    "delay_min": "0.5",
    "max_retries": "7",
    "proxy_list": "login:pass@185.10.20.30:8080\nsocks5://37.18.90.1:1080",
    "vk_post_template": "{title}\\n{price}",
    "log_level": "debug",
})
cfg = apply_db_settings(fresh(), db)
assert cfg.browser.headless is False, cfg.browser.headless
assert cfg.browser.delay_min == 0.5, cfg.browser.delay_min
assert cfg.parser.max_retries == 7, cfg.parser.max_retries
assert cfg.browser.proxy_string == "login:pass@185.10.20.30:8080, socks5://37.18.90.1:1080", \
    cfg.browser.proxy_string
assert cfg.vk.template == "{title}\n{price}", repr(cfg.vk.template)
assert cfg.parser.log_level == "DEBUG", cfg.parser.log_level

# 3. список прокси разбирается пулом (по одному адресу на строку), пароль не светится
pool = ProxySettings.parse_pool(cfg.browser.proxy_string)
assert len(pool) == 2 and pool[0].login == "login" and pool[1].scheme == "socks5", pool
assert "login:***@" in str(pool[0]), "пароль прокси не должен светиться в описании"

# 4. границы значений режутся при сохранении, переключатель «выкл» хранится как "0"
save(vk_max_photos_per_post="99", details_on="0")
cfg = apply_db_settings(fresh(), db)
assert cfg.vk.max_photos_per_post == 10, cfg.vk.max_photos_per_post      # потолок реестра
assert db.setting_get("vk_max_photos_per_post") == "10", "значение урезано на записи"
assert cfg.parser.fetch_details is False, cfg.parser.fetch_details

# 5. очистка поля возвращает параметр к окружению (наложение идемпотентно)
base = fresh()
apply_db_settings(base, db)
base.parser.max_retries = 99                      # имитируем «уже применённую» настройку
save(max_retries="")
cfg = apply_db_settings(base, db)
assert cfg.parser.max_retries == 2, cfg.parser.max_retries

# 6. форма получает эффективные значения: база → окружение → дефолт кода
view = effective_settings(fresh(), db)
assert view["headless"] == "0" and view["delay_min"] == "0.5", view
assert view["browser_timeout"] == "30", view["browser_timeout"]   # из окружения/дефолта
assert view["parse_interval_min"] == "15", view["parse_interval_min"]   # только БД
assert view["photos_dir"] == "data/photos", view["photos_dir"]
assert set(view) == set(SETTING_KEYS), "в форме должны быть все настройки реестра"

# 7. секреты наружу не отдаются: ни сохранённые, ни взятые из окружения
cfg = fresh()
save(vk_access_token="vk1.a.secretsecretsecret")
cfg = apply_db_settings(cfg, db)
assert cfg.vk.access_token == "vk1.a.secretsecretsecret", "ключ применяется к конфигу"
form = effective_settings(cfg, db)
assert form["vk_access_token"] == "" and form["admin_password"] == "", form
assert current_value(cfg, spec_for("vk_access_token")).startswith("vk1.a."), "живое значение на месте"

# 8. нормализация перед записью: bool → "1"/"0", список → построчно, путь → строка
assert sanitize_for_storage(spec_for("details_on"), True) == "1"
assert sanitize_for_storage(spec_for("details_on"), "false") == "0"
assert sanitize_for_storage(spec_for("proxy_list"), "a:1\r\nb:2\r\n") == "a:1\nb:2"
assert sanitize_for_storage(spec_for("photos_dir"), " data/photos ") == "data/photos"

# 9. подпись браузера меняется только от параметров, требующих нового профиля
sig_a = browser_signature(fresh())
sig_b = browser_signature(apply_db_settings(fresh(), {"headless": "0"}))
sig_c = browser_signature(apply_db_settings(fresh(), {"delay_min": "9"}))
assert sig_a != sig_b and sig_a == sig_c, "headless/прокси ломают профиль, задержки — нет"

# 10. реестр самосогласован: ключи уникальны, поля существуют, форма рисует всё
from webui_page import SETTINGS_PAGE, SETTINGS_SCRIPT, _row_sizes

keys = [spec.key for spec in SPECS]
assert len(keys) == len(set(keys)), "дубли настроек в реестре"
blank = Config()
for spec in SPECS:
    if spec.section in ("browser", "parser", "vk"):
        assert hasattr(getattr(blank, spec.section), spec.attr), f"{spec.key}: нет поля {spec.attr}"
    elif spec.section == "root":
        assert hasattr(blank, spec.attr), f"{spec.key}: нет поля {spec.attr}"
    assert f'data-setting="{spec.key}"' in SETTINGS_PAGE, f"{spec.key}: поле не отрисовано"
assert "headless" in overridden_keys(db)
assert SETTINGS_SCRIPT.count("settingsSave") >= 2, "кнопки сохранения подключены"

# 11. ряды полей: без одинокого хвоста и без колонок шире трёх
for n, expected in {1: [1], 2: [2], 3: [3], 4: [2, 2], 5: [3, 2], 7: [3, 2, 2]}.items():
    assert _row_sizes(n) == expected, f"{n} полей → {_row_sizes(n)}, ожидалось {expected}"
assert "repeat(4" not in SETTINGS_PAGE, "полей в ряду больше трёх"
assert 'class="setrow"' in SETTINGS_PAGE, "поля настроек не в сетке"

db.close()
print("\nOK: реестр настроек, наложение на .env и форма админки работают")
