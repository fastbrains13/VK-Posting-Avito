# Развёртывание на сервере

Инструкция для боевого запуска **Avito Parser + VK Publisher** на Linux-сервере
(Ubuntu/Debian). Основной путь — Docker Compose (образ содержит Chromium, поэтому
парсер работает «из коробки»). В конце — альтернатива без Docker (venv + systemd).

Реальные адреса, порты SSH и пароли в этот файл не вносятся — везде плейсхолдеры:

```bash
export SRV_HOST='xxx.xxx.xxx.xxx'     # IP сервера
export SRV_PORT='22'                  # порт SSH
export SRV_USER='root'
export APP_DIR='/opt/avito'           # каталог проекта на сервере
```

---

## 1. Требования к серверу

| Параметр | Минимум | Комментарий |
|---|---|---|
| ОС | Ubuntu 22.04 / 24.04, Debian 12 | ядро x86_64 или arm64 |
| CPU | 1 ядро | сборка образа и рендер Chromium медленные, это норма |
| RAM | 1 ГБ + **swap обязателен** | Chromium в пике съедает 600–800 МБ; без swap процесс убивается OOM-киллером |
| Диск | 5 ГБ свободно | образ ~700 МБ + скачанные фото |
| Сеть | исходящий HTTPS на avito.ru и api.vk.com | входящие порты не нужны — доступ через SSH-туннель |
| Python на сервере | не требуется | нужен только Docker (или Python 3.11+ для варианта без Docker) |

Проверка ресурсов перед стартом:

```bash
nproc; free -m; swapon --show; df -h / ; curl -s -o /dev/null -w '%{http_code}\n' https://www.avito.ru
```

Если `swapon --show` пустой — сразу добавьте swap:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## 2. Установка Docker

Официальный репозиторий Docker (нужен **compose v2**, т.к. далее используется `docker compose`):

```bash
apt-get update && apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker compose version        # должно быть v2.x
```

Быстрая альтернатива из репозитория Ubuntu (тоже рабочий вариант):

```bash
apt-get install -y docker.io docker-compose-v2
```

---

## 3. Код на сервере

```bash
mkdir -p /opt/avito && cd /opt/avito
```

### Вариант A — git (рекомендуемый для регулярных обновлений)

Предварительно **локально** убедитесь, что проект закоммичен и запушен в репозиторий
(в текущей рабочей копии файлы не закоммичены — тогда этот путь недоступен и используйте B):

```bash
git add -A && git commit -m "Avito parser + VK publisher" && git push
```

На сервере:

```bash
git clone <URL_РЕПОЗИТОРИЯ> /opt/avito && cd /opt/avito
```

Для приватного репозитория — deploy-ключ с доступом только на чтение:

```bash
ssh-keygen -t ed25519 -f /root/.ssh/avito_deploy -N ''
cat /root/.ssh/avito_deploy.pub      # добавить в Deploy keys на GitHub
git config --global core.sshCommand 'ssh -i /root/.ssh/avito_deploy -o IdentitiesOnly=yes'
```

### Вариант B — rsync без git

Ключевой момент — **не перетирать `.env`, `data/` и `logs/`**:

```bash
rsync -avz -e "ssh -p $SRV_PORT" \
  --exclude '.env' --exclude '.env.local' --exclude 'data/' --exclude 'logs/' \
  --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
  --exclude 'out/' --exclude 'avito.db*' --exclude '.taste-skill' \
  ./ "$SRV_USER@$SRV_HOST:/opt/avito/"
```

### Вариант C — SFTP из Python (если `ssh`/`rsync` требуют интерактивного ввода)

```python
# deploy.py — залить код, НЕ трогая .env.  python deploy.py
import io, os, posixpath, time, paramiko

HOST, PORT, USER = os.environ["SRV_HOST"], int(os.environ["SRV_PORT"]), os.environ.get("SRV_USER", "root")
FILES = [
    "webui.py", "webui_page.py", "main.py", "publisher.py",
    "Dockerfile", "docker-compose.yml", ".dockerignore", "requirements.txt",
    ".env.example", "README.md", "AGENTS.md", "DEPLOY.md",
    "avito_parser/__init__.py", "avito_parser/browser.py", "avito_parser/config.py",
    "avito_parser/database.py", "avito_parser/export.py", "avito_parser/human.py",
    "avito_parser/logger.py", "avito_parser/photos.py", "avito_parser/scraper.py",
    "avito_parser/vk_publisher.py",
    "tests/vk_flow_test.py", "tests/ui_smoke.mjs",
]

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
# доступ по ключу:
cli.connect(HOST, port=PORT, username=USER, key_filename=os.path.expanduser("~/.ssh/id_ed25519"), timeout=30)
# или доступ по паролю (пароль не хранится в файле — запрашиваем из tty/окружения):
# cli.connect(HOST, port=PORT, username=USER, password=os.environ["SRV_PASS"], timeout=30)
sftp = cli.open_sftp()

# 1. бэкап конфигурации — до любых изменений
_, out, _ = cli.exec_command("cp -a /opt/avito/.env /opt/avito/.env.bak.$(date +%F-%H%M%S) 2>/dev/null; ls /opt/avito/.env*")
print(out.read().decode())

# 2. заливка (каталоги создаём по мере необходимости)
def ensure_dirs(remote_path):
    cur = ""
    for part in [p for p in posixpath.dirname(remote_path).split("/") if p]:
        cur += "/" + part
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


for rel in FILES:
    if not os.path.exists(rel):
        print("пропущен (нет локально):", rel)
        continue
    remote = "/opt/avito/" + rel
    ensure_dirs(remote)
    sftp.putfo(io.BytesIO(open(rel, "rb").read()), remote)
    print("zalito:", rel)

# 3. пересборка в фоне (небокирующий запуск, чтобы SSH-сессия не висела)
cli.exec_command("cd /opt/avito && setsid nohup docker compose up -d --build "
                 "> /tmp/build.log 2>&1 < /dev/null &")
time.sleep(2)

# 4. ожидание healthy
for _ in range(60):
    _, out, _ = cli.exec_command("docker inspect --format '{{.State.Health.Status}}' avito_webui 2>/dev/null")
    st = out.read().decode().strip()
    if st in ("healthy", "unhealthy"):
        print("состояние контейнера:", st); break
    time.sleep(10)
print(cli.exec_command("tail -5 /tmp/build.log")[1].read().decode())
sftp.close(); cli.close()
```

---

## 4. Настройка `.env`

`.env` **не попадает в образ** (исключён в `.dockerignore`) и передаётся контейнеру через
`env_file: .env`. Поэтому он обязан лежать рядом с `docker-compose.yml` в `/opt/avito`.

```bash
cd /opt/avito
cp .env.example .env
chmod 600 .env                       # в файле лежат ключи VK и админки
```

Заполните как минимум:

```bash
# --- админка ---
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<придумайте длинный пароль>
ADMIN_SECRET=$(openssl rand -hex 32)   # впишите результат командой ниже

# --- VK ---
VK_ACCESS_TOKEN=vk1.a.…
VK_GROUP_ID=public123456789            # или числовой id со знаком минус: -123456789
VK_APP_ID=<id standalone-приложения>   # нужен для ссылки получения user-ключа (фото)

# --- источники парсинга ---
AVITO_TARGET_URL=https://www.avito.ru/...
```

Подставить сгенерированный секрет без ручного редактирования:

```bash
sed -i "s|^ADMIN_SECRET=.*|ADMIN_SECRET=$(openssl rand -hex 32)|" /opt/avito/.env
```

### Важно про приоритеты настрое

1. **Настройки из веб-админки (таблица `settings` в SQLite) перекрывают `.env`.**
   Ключ VK и сообщество, заданные в разделе «VK-канал», имеют приоритет над
   `VK_ACCESS_TOKEN`/`VK_GROUP_ID` из `.env`.
2. **Секция `environment:` в `docker-compose.yml` перекрывает `env_file`.**
   Пути внутри контейнера зафиксированы там:

   ```yaml
   environment:
     - HEADLESS_MODE=true
     - DB_PATH=data/avito.db
     - PHOTOS_DIR=data/photos
     - LOG_FILE=logs/avito_parser.log
   ```

   Менять их нужно в compose-файле, а не в `.env`, иначе изменение проигнорируется.
   Пути относительные — они указывают в смонтированные тома `./data` и `./logs`,
   поэтому база и фото переживают пересборку образа.

### Если ключ VK ещё не получен

Парсер и админка работают без VK-токена: при старте печатается
«VK: VK_ACCESS_TOKEN не задан — постинг недоступен, парсинг работает».
Постинг включится после добавления ключа и `docker compose up -d --force-recreate`.

---

## 5. Первый запуск

```bash
cd /opt/avito
docker compose up -d --build --wait
```

Первая сборка на 1 CPU занимает несколько минут (ставится Chromium со шрифтами).
Шрифты `fonts-noto-core`/`fonts-dejavu-core` обязательны: без них Selenium падает на
русских названиях объявлений.

Что посмотреть после старта:

```bash
docker compose ps                       # State=running, Status=(healthy)
docker compose logs --tail=40 webui     # адрес, логин, статус VK, интервалы крона
docker inspect --format '{{.State.Health.Status}}' avito_webui
```

Нормальный вывод содержит строки вида:

```
Админка: http://0.0.0.0:8000
Логин: admin / пароль: задан в .env
VK: сообщество «...» (id ...), в очереди 0, опубликовано 0
Крон: парсинг каждые 15 мин, публикация каждые 30 мин
```

Если вместо «задан в .env» показан сгенерированный пароль — значит `ADMIN_PASSWORD`
в `.env` пустой: задайте и пересоздайте контейнер.

---

## 6. Доступ к панели

По умолчанию compose публикует `8000:8000` на всех интерфейсах. Если сервер стоит
в публичной сети и доступ нужен только вам, закрепите порт на loopback — правкой
`docker-compose.yml` или отдельным override-файлом, чтобы не трогать основной:

```bash
# /opt/avito/docker-compose.override.yml
services:
  webui:
    ports: !override
      - "127.0.0.1:8000:8000"
```

`!override` требует Docker Compose ≥ v2.24 — без него списки `ports` из base и override
складываются, и порт окажется занят. На более старой версии проще отредактировать base:

```bash
sed -i 's|^\( *\)- "8000:8000"|\1- "127.0.0.1:8000:8000"|' /opt/avito/docker-compose.yml
```

```bash
cd /opt/avito && docker compose up -d          # применит base + override
ss -tlnp | grep 8000                           # должно быть 127.0.0.1:8000, а не 0.0.0.0
```

Рабочий доступ тогда — SSH-туннель с вашей машины:

```bash
ssh -p $SRV_PORT -N -L 8000:127.0.0.1:8000 $SRV_USER@$SRV_HOST
```

Второй терминал (или браузер): **http://localhost:8000** → вход `admin` / `ADMIN_PASSWORD`.

Полезные флаги туннеля для нестабильной сети:

```bash
ssh -p $SRV_PORT -N -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=4 \
    -L 8000:127.0.0.1:8000 $SRV_USER@$SRV_HOST
```

> Почему не открыть 80/443 напрямую. На части азиатских провайдеров (например,
> Tencent Cloud) входящий HTTP на 80/443 блокируется без ICP-регистрации, поэтому наружный
> веб-интерфейс может быть недоступен в принципе. Туннель работает поверх SSH и
> не требует открытых портов, шифрует трафик и прячет админку от сканеров.
> Если публичный доступ всё же нужен — ставьте reverse-proxy с HTTPS (Caddy/Nginx)
> и обязательную сессионную защиту: в админке уже есть вход по паролю и HMAC-cookie.

---

## 7. Проверка развёртывания

```bash
# без авторизации все API должны отдавать 401, а не 200 — это проверка, что вход работает
curl -s -o /dev/null -w 'без входа: %{http_code}\n' http://127.0.0.1:8000/api/state

# вход и опрос состояния (выполнять на сервере или через туннель)
J=/tmp/ck.txt
curl -s -c $J -X POST http://127.0.0.1:8000/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<ADMIN_PASSWORD>"}'
curl -s -b $J http://127.0.0.1:8000/api/state | python3 -m json.tool | head -30
```

Ожидаемое состояние: `vk.token_set: true`, `vk.group_name` — название сообщества,
`vk.app_id` — id приложения, `settings.vk_access_token_mask` — маска вида
`vk1.a.XXXXXX…YYYY` (полный ключ наружу не отдаётся), `scheduler.paused: false`.

Полный прогон интерфейса в headless Chrome (локально, через туннель; только чтение):

```bash
node tests/ui_smoke.mjs http://127.0.0.1:8000/ admin '<ADMIN_PASSWORD>'
# итог должен быть: RESULT: 0 FAIL
```

Тест VK-флоу на сервере (ничего боевого не отправляет). Каталог `tests/` исключён из
образа через `.dockerignore`, поэтому его нужно скопировать в контейнер:

```bash
docker cp /opt/avito/tests avito_webui:/app/tests
docker compose exec webui python tests/vk_flow_test.py    # → ВСЕ ПРОВЕРКИ ПРОШЛИ
```

Тест берёт реальные jpg из `data/photos/*/*.jpg` (нужно минимум 3 файла — они в смонтированном
томе) и пишет служебную базу в `/tmp/vk_test.db` внутри контейнера.

Проверка ключа VK и прав сообщества:

```bash
docker compose exec webui python publisher.py --check
```

---

## 8. Обновление кода

Порядок действий — строго такой, иначе можно потерять конфигурацию:

```bash
cd /opt/avito
cp -a .env .env.bak.$(date +%F-%H%M%S)     # 1. бэкап .env ОБЯЗАТЕЛЬНО до любых операций
# 2. залить новые файлы (git pull / rsync / SFTP из шага 3)
docker compose up -d --build               # 3. пересобрать и пересоздать контейнер
docker compose logs --tail=30 webui        # 4. убедиться, что крон поднялся и VK виден
```

Замечания:

- Меняются только `.py`-файлы — пересборка образа всё равно нужна: код копируется в образ
  (`COPY . .`), а не монтируется томом.
- Правка `.env` не требует `--build`, но требует пересоздания контейнера:
  `docker compose up -d --force-recreate`.
- **Никогда не делайте `git clean -xfd` / `git checkout .` в `/opt/avito`** — это сотрёт
  `.env`, `data/` и `logs/`.
- Команда `docker compose down` **не** удаляет тома: база и фото остаются на хосте.

### Если `.env` всё-таки потерян

```bash
ls -la /opt/avito/.env.bak.*          # найти свежий бэкап
cp /opt/avito/.env.bak.<метка> /opt/avito/.env
cd /opt/avito && docker compose up -d --force-recreate
```

После восстановления с другим `ADMIN_SECRET` старые cookie-сессии перестают приниматься —
это ожидаемо, нужно просто заново войти.

---

## 9. Данные: резервные копии и перенос

Всё состояние живёт в двух каталогах на хосте:

```
/opt/avito/data/avito.db      # объявления, источники, настройки админки
/opt/avito/data/photos/<id>/  # скачанные фото для постов
/opt/avito/logs/avito_parser.log
```

База открыта в режиме WAL, поэтому простое копирование `.db` может отдать непоследовательный
снимок. Правильный бэкап — через SQLite backup API из контейнера:

```bash
docker compose exec webui python - <<'EOF'
import sqlite3
src = sqlite3.connect("data/avito.db")
dst = sqlite3.connect("/app/data/avito.backup.db")
src.backup(dst)
print("backup ok")
EOF
mv /opt/avito/data/avito.backup.db /backup/avito_$(date +%F).db
```

Регулярно — через скрипт и cron. Скрипт держит ротацию на 14 дней:

```bash
cat > /opt/avito/backup.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
DEST=/backup
mkdir -p "$DEST"
cd /opt/avito
docker compose exec -T webui python -c \
  'import sqlite3; s=sqlite3.connect("data/avito.db"); d=sqlite3.connect("/app/data/bak.tmp"); s.backup(d)'
mv data/bak.tmp "$DEST/avito_$(date +%F).db"
find "$DEST" -name 'avito_*.db' -mtime +14 -delete
SH
chmod +x /opt/avito/backup.sh
/opt/avito/backup.sh                       # разовая проверка
```

```bash
crontab -l -u root 2>/dev/null | { cat; echo '0 4 * * * /opt/avito/backup.sh >> /var/log/avito-backup.log 2>&1'; } | crontab -u root -
```

В crontab символ `%` означает перенос строки, поэтому в вызове внутри самой crontab-строки
его экранируют (`\%`). Когда команда вынесена в скрипт, экранирование не нужно.

Перенос на другой сервер: скопировать `data/` и `logs/` целиком, затем `docker compose up -d --build`.
Схемы БД мигрируются автоматически при старте (`Database._migrate()`).

---

## 10. Вариант без Docker (venv + systemd)

Имеет смысл, если Docker недоступен. Нужны Python 3.11+, Chromium и его driver.

> В Ubuntu 20.04+ пакет `chromium` пересажен на snap, что плохо сочетается с headless-сервером
> и Selenium. Надёжнее взять Debian-сборку: на Debian 12 команда ниже работает как есть;
> на Ubuntu добавьте репозиторий Debian-пакета или используйте вариант с Docker
> (в образе Chromium стоит из `apt` и проверен).

```bash
apt-get install -y python3-venv python3-pip chromium chromium-driver fonts-noto-core
useradd -m -s /bin/bash avito
mkdir -p /opt/avito && chown avito:avito /opt/avito
su - avito
cd /opt/avito                      # код отсюда (шаг 3)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env && chmod 600 .env && nano .env
CHROME_BIN=/usr/bin/chromium CHROMEDRIVER_PATH=/usr/bin/chromedriver .venv/bin/python webui.py --host 127.0.0.1 --port 8000
```

systemd-юнит. `.env` читает сам `webui.py` через python-dotenv, поэтому `EnvironmentFile`
не нужен — два источника одних и тех же переменных только запутают:

```ini
# /etc/systemd/system/avito.service
[Unit]
Description=Avito Parser + VK Publisher admin
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=avito
WorkingDirectory=/opt/avito
Environment=CHROME_BIN=/usr/bin/chromium
Environment=CHROMEDRIVER_PATH=/usr/bin/chromedriver
ExecStart=/opt/avito/.venv/bin/python webui.py --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now avito
journalctl -u avito -f
```

Флаги `webui.py` для отладки: `--no-auth` (без входа, **только локально**),
`--no-cron` (без фонового планировщика), `--no-headless` (показывать браузер).

---

## 11. Частые проблемы

| Симптом | Причина и решение |
|---|---|
| `401` на все API сразу после входа | `ADMIN_SECRET` изменился — старые cookie невалидны. Выйдите через `/logout` и войдите заново |
| В логах `ADMIN_PASSWORD не задан — сгенерирован временный: ...` | `ADMIN_PASSWORD` пуст в `.env`; временный пароль меняется при каждом старте. Задайте постоянный |
| `VK запрещает загрузку фото ключам сообщества (код 27)` | Не исправимо community-ключом: нужен user-ключ standalone-приложения. См. README → «Постинг с фото» |
| `Похоже на блокировку (ip_block)`, `повторная попытка напрямую` | Прокси забанены Авито и ушли в карантин, прямой IP тоже банится. Нужны свежие резидентные прокси в `PROXY_STRING` |
| Контейнер в `unhealthy`, `OOMKilled` в `docker inspect` | Не хватило памяти: проверьте `free -m`, `dmesg \| grep -i kill`, добавьте swap (шаг 1) |
| `database is locked` | Два процесса пишут в одну базу (например, запущены и `webui.py`, и `main.py --watch`). Оставьте один планировщик; WAL и `busy_timeout=30s` уже включены |
| Туннель «висячит», но браузер не отдаёт страницу | SSH-транспорт умер. Убейте процесс и поднимите туннель заново |
| Порт 8000 занят на сервере | Поменяйте левую часть в `ports: - "127.0.0.1:8000:8000"` |
| Долгая сборка / обрыв сети на `apt-get` | `docker compose build --no-cache --progress=plain` и повтор; на 1 CPU образ собирается 5–10 минут |
| Очередь растёт, посты не уходят | Проверьте `scheduler.paused` в `/api/state`, интервал `publish_interval_min`, права ключа (`publisher.py --check`) |

Логи для диагностики:

```bash
docker compose logs --tail=200 webui          # stdout админки и крона
tail -f /opt/avito/logs/avito_parser.log      # файл лога (неймспейсы avito.*)
docker stats avito_webui --no-stream          # потребление CPU/RAM
```

---

## 12. Чек-лист развёртывания

- [ ] Docker + `docker compose version` = v2
- [ ] swap ≥ 2 ГБ включён (`swapon --show`)
- [ ] код в `/opt/avito`, `.env` создан из `.env.example`, `chmod 600`
- [ ] `ADMIN_PASSWORD` задан, `ADMIN_SECRET` = `openssl rand -hex 32`
- [ ] `VK_ACCESS_TOKEN` / `VK_GROUP_ID` заполнены (или осознанно пусто)
- [ ] `docker compose up -d --build --wait` → `healthy`
- [ ] `/api/state` без cookie отдаёт `401`
- [ ] вход работает, в топе виден статус сообщества VK
- [ ] `node tests/ui_smoke.mjs ...` → `RESULT: 0 FAIL`
- [ ] крон сделал цикл: в `Объявлениях` появились новые записи, в `Задачах` — задачи
- [ ] бэкап `.env` и `data/avito.db` настроен (шаг 9)
