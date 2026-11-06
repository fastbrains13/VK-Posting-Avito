#!/usr/bin/env bash
# Установка VK-Posting-Avito на Ubuntu 22.04/24.04 через Docker Compose.
# Запуск из клона репозитория: sudo bash instal.sh
set -Eeuo pipefail

REPO_URL="https://github.com/fastbrains13/VK-Posting-Avito.git"
APP_DIR="/opt/avito"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Запустите скрипт от root: sudo bash instal.sh" >&2
  exit 1
fi

if [[ ! -r /dev/tty ]]; then
  echo "Нужен интерактивный терминал для ввода настроек." >&2
  exit 1
fi

prompt() {
  local var_name="$1" label="$2" default="${3:-}" value
  if [[ -n "$default" ]]; then
    read -r -p "$label [$default]: " value </dev/tty
    value="${value:-$default}"
  else
    read -r -p "$label: " value </dev/tty
  fi
  printf -v "$var_name" '%s' "$value"
}

prompt_secret() {
  local var_name="$1" label="$2" value
  read -r -s -p "$label (пусто — оставить текущее значение): " value </dev/tty
  printf '\n' >/dev/tty
  printf -v "$var_name" '%s' "$value"
}

prompt AVITO_URL "Ссылка на выдачу Авито (пусто — не менять)"
prompt ADMIN_USERNAME "Имя администратора" "admin"
prompt_secret ADMIN_PASSWORD "Новый пароль админки"
prompt_secret VK_ACCESS_TOKEN "VK access token"
prompt VK_GROUP_ID "ID или короткий адрес сообщества VK (пусто — не менять)"
prompt VK_APP_ID "VK App ID (пусто — не менять)"
prompt DOMAIN "Домен админки (например admin.example.com; пусто — SSH-туннель)"
export AVITO_URL ADMIN_USERNAME ADMIN_PASSWORD VK_ACCESS_TOKEN VK_GROUP_ID VK_APP_ID DOMAIN

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y git curl ca-certificates docker.io docker-compose-v2
systemctl enable --now docker

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only
elif [[ ! -e "$APP_DIR" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  echo "Ошибка: $APP_DIR существует, но не является Git-репозиторием. Файлы не изменены." >&2
  exit 1
fi

cd "$APP_DIR"
[[ -f .env ]] || cp .env.example .env
chmod 600 .env

python3 - <<'PY'
import os
import re
import secrets
from pathlib import Path

path = Path(".env")
lines = path.read_text(encoding="utf-8").splitlines()

def current_value(key):
    prefix = key + "="
    for line in lines:
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            return value
    return ""

updates = {
    "ADMIN_USERNAME": os.environ.get("ADMIN_USERNAME", "admin"),
    "ADMIN_SECRET": current_value("ADMIN_SECRET") or secrets.token_hex(32),
}
for key in ("AVITO_URL", "ADMIN_PASSWORD", "VK_ACCESS_TOKEN", "VK_GROUP_ID", "VK_APP_ID"):
    value = os.environ.get(key, "")
    if value:
        env_key = "AVITO_TARGET_URL" if key == "AVITO_URL" else key
        updates[env_key] = value

if not updates.get("ADMIN_PASSWORD") and not current_value("ADMIN_PASSWORD"):
    raise SystemExit("Нужно задать ADMIN_PASSWORD: запустите скрипт и введите пароль.")

# Установить/обновить только заданные значения, оставив остальные параметры .env как есть.
found = set()
result = []
for line in lines:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
    if key in updates:
        result.append(f"{key}={updates[key]}")
        found.add(key)
    else:
        result.append(line)
for key, value in updates.items():
    if key not in found:
        result.append(f"{key}={value}")
path.write_text("\n".join(result) + "\n", encoding="utf-8")

# Caddy сам запросит и обновит TLS-сертификат, когда домен указывает на этот сервер.
domain = os.environ.get("DOMAIN", "").strip().lower().rstrip(".")
if domain:
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(domain) > 253 or not re.fullmatch(rf"{label}(?:\.{label})+", domain):
        raise SystemExit("Некорректный домен. Введите FQDN, например admin.example.com, без https:// и пути.")
    Path("Caddyfile").write_text(
        f"{domain} {{\n    encode gzip\n    reverse_proxy webui:8000\n}}\n",
        encoding="utf-8",
    )
PY

# Не публикуем саму админку на всех интерфейсах; доменный доступ идёт через Caddy.
python3 - <<'PY'
from pathlib import Path

path = Path("docker-compose.yml")
text = path.read_text(encoding="utf-8")
public = '- "8000:8000"'
local = '- "127.0.0.1:8000:8000"'
if public in text:
    text = text.replace(public, local, 1)
elif local not in text:
    raise SystemExit("Не удалось определить публикацию порта 8000 в docker-compose.yml; проверьте файл вручную.")
path.write_text(text, encoding="utf-8")
PY

if [[ -n "${DOMAIN//[[:space:]]/}" ]]; then
  docker compose --profile domain up -d --build
else
  docker compose stop caddy >/dev/null 2>&1 || true
  docker compose up -d --build
fi

echo
docker compose ps
echo
echo "Последние логи:"
docker compose logs --tail=30 webui
echo
if [[ -n "${DOMAIN//[[:space:]]/}" ]]; then
  echo "Установка завершена. Админка: https://${DOMAIN}"
  echo "Проверьте, что DNS-запись A/AAAA домена указывает на сервер и входящие порты 80/443 открыты в firewall и панели провайдера."
else
  echo "Установка завершена. Админка доступна только через SSH-туннель."
  echo "На своём компьютере выполните:"
  echo "ssh -N -L 8000:127.0.0.1:8000 USER@SERVER_IP"
  echo "Затем откройте http://localhost:8000"
fi
echo "Для постинга с фото проверьте токен и переключатель «Только посты с фото» в разделе VK-канал."