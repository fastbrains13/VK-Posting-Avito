# Avito → VK · MVP

Парсер Авито и ручная публикация объявлений в сообщество ВКонтакте с фотографиями.

Репозиторий: https://github.com/fastbrains13/VK-Posting-Avito

Сейчас это осознанно узкий MVP:

- один пользовательский токен VK;
- одно сообщество;
- одна ссылка на выдачу Авито;
- парсится только указанная страница, без пагинации;
- объявления открываются по одному, детали и фото загружаются по требованию;
- публикация только ручная;
- один пост на пару «объявление + сообщество», без повторов;
- фото до 10 штук, как в VK.

## Возможности

- вход в админку под Django-auth;
- добавление пользовательского токена VK и выбор сообщества, где пользователь администратор;
- проверка права на постинг и загрузку фото;
- источник Авито: ссылка на выдачу и город;
- парсинг карточек выдачи;
- загрузка описания, цены, локации и фотографий объявления;
- предпросмотр поста: заголовок, цена, описание, ссылка;
- публикация с фото и ссылкой;
- защита от повторной публикации;
- соблюдение интервала между постами;
- очередь ручных задач, журнал и логи;
- единый пул HTTP/SOCKS4/SOCKS5-прокси с проверкой и ротацией;
- настройки сообщества и прокси из веб-интерфейса;
- PostgreSQL в Docker, SQLite для локальной разработки.

## Стек

- Python 3.12
- Django 5.1
- PostgreSQL 16 (Docker) / SQLite (локально)
- Selenium + Chromium
- requests + PySocks
- Gunicorn + WhiteNoise
- Docker Compose
- Caddy — опционально, для HTTPS и домена

## Структура

```text
.
├── manage.py
├── config/                 # settings, urls, wsgi
├── core/                   # VKAccount, VKCommunity, ProxyEndpoint, JobRun
│   ├── models.py
│   ├── proxies.py          # разбор, проверка, ротация прокси
│   ├── crypto.py           # шифрование токенов
│   └── management/commands/import_proxies.py
├── avito/                  # AvitoSource, Ad, AdPhoto, Selenium-клиент
├── publishing/             # Publication, VK-клиент, рендер, публикация
├── jobs/                   # воркер и обработчики задач
├── web/                    # страницы, формы, шаблоны, static
├── data/                   # media/, chrome-profile/ (volume, не в git)
├── docker-compose.yml
├── Dockerfile
├── Caddyfile.example
├── .env.example
├── AGENTS.md
└── README.md
```

## Быстрый старт локально (SQLite)

Нужны Python 3.12+ и Chrome/Chromium для Selenium.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

В отдельном терминале:

```bash
source .venv/bin/activate
python manage.py worker
```

Если `.env` отсутствует, используется SQLite `data/db.sqlite3`. Откройте http://127.0.0.1:8000.

Локальный запуск в фоне:

```bash
./run_local.sh
./stop_local.sh
```

Логи: `run/server.log`, `run/worker.log`.

## Требования к серверу

| Параметр | Минимум | Рекомендуется |
|---|---|---|
| ОС | Ubuntu 22.04/24.04, Debian 12 | Ubuntu 24.04 LTS |
| CPU | 1 vCPU | 2 vCPU |
| RAM | **2 ГБ** | **4 ГБ** |
| Swap | 1–2 ГБ | 2 ГБ |
| Диск | 20 ГБ SSD | 40 ГБ SSD |
| Docker | Docker Engine + Compose v2 | актуальные |
| Сеть | исходящий HTTPS | + домен для HTTPS |
| Порты | 22 (SSH) | 80/443 при домене |

Chromium в пике потребляет 600–900 МБ. На сервере с 1 ГБ RAM без swap контейнеры будут падать по OOM. Если RAM меньше 4 ГБ, swap обязателен.

Входящий порт 8000 не открывается наружу: веб слушает `127.0.0.1:8000`. Доступ — через SSH-туннель или Caddy.

Нужен исходящий HTTPS к:

- `www.avito.ru`, `*.avito.st` — парсинг и фото;
- `api.vk.com`, `pu.vk.com`, `oauth.vk.com` — VK API и загрузка фото.

## Развёртывание на сервере (пошагово)

Ниже — Ubuntu 22.04/24.04, каталог `/opt/avito`, доступ по SSH.

### Шаг 1. Подготовка сервера

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl git ufw
sudo timedatectl set-timezone Europe/Moscow
```

Если RAM меньше 4 ГБ, добавьте swap:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Проверка:

```bash
free -h
swapon --show
df -h /
```

### Шаг 2. Установка Docker

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
| sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
docker compose version
```

### Шаг 3. Код проекта

```bash
sudo mkdir -p /opt/avito
sudo chown "$USER":"$USER" /opt/avito
git clone https://github.com/fastbrains13/VK-Posting-Avito.git /opt/avito
cd /opt/avito
```

Если репозиторий уже скопирован — просто перейдите в каталог.

### Шаг 4. Настройки `.env`

```bash
cp .env.example .env
chmod 600 .env
```

Сгенерируйте секреты:

```bash
openssl rand -base64 48     # DJANGO_SECRET_KEY
openssl rand -base64 24     # POSTGRES_PASSWORD
openssl rand -base64 32 | tr '+/' '-_'   # TOKEN_ENCRYPTION_KEY
```

Заполните `.env`:

```dotenv
DEBUG=0
DJANGO_SECRET_KEY=<длинная случайная строка>
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=
HTTPS=0
DOMAIN=

POSTGRES_DB=avito_mvp
POSTGRES_USER=avito
POSTGRES_PASSWORD=<случайный пароль>
POSTGRES_HOST=db
POSTGRES_PORT=5432

TOKEN_ENCRYPTION_KEY=<fernet-ключ>
```

`TOKEN_ENCRYPTION_KEY` нельзя менять после первой публикации: сохранённые токены VK перестанут расшифровываться. Сохраните его в менеджере секретов.

### Шаг 5. Права на данные

Контейнер работает от UID 1000. Создайте каталог и отдайте его этому пользователю:

```bash
mkdir -p data
sudo chown -R 1000:1000 data
```

### Шаг 6. Запуск

Вариант A — доступ через SSH-туннель, без домена:

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 web
```

Вариант B — домен и HTTPS через Caddy:

1. Направьте A/AAAA-запись домена на IP сервера.
2. В `.env` укажите:

```dotenv
DOMAIN=admin.example.com
ALLOWED_HOSTS=admin.example.com,localhost
CSRF_TRUSTED_ORIGINS=https://admin.example.com
HTTPS=1
```

3. Скопируйте Caddyfile и запустите профиль `domain`:

```bash
cp Caddyfile.example Caddyfile
docker compose --profile domain up -d --build
docker compose ps
```

Caddy сам получит TLS-сертификат. Откройте `https://admin.example.com`.

### Шаг 7. Администратор

```bash
docker compose exec web python manage.py createsuperuser
```

### Шаг 8. Доступ

Через SSH-туннель:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@SERVER_IP
```

Откройте http://127.0.0.1:8000.

Или домен: `https://admin.example.com`.

### Шаг 9. Первичная настройка в интерфейсе

1. «Подключение VK» → пользовательский токен VK.
2. «Обновить список сообществ» → выбрать сообщество, где вы администратор.
3. Если VK возвращает код 15 при публикации — добавить ключ сообщества:
   сообщество → Управление → Работа с API → Создать ключ (права на стену).
4. «Источник Авито» → ссылка на выдачу и город → «Загрузить объявления».
5. Открыть объявление → «Загрузить описание и фото» → проверить предпросмотр.
6. «Опубликовать».
7. «Настройки» → при необходимости добавить прокси.

### Шаг 10. Проверка воркера

```bash
docker compose logs -f worker
```

Воркер должен быть запущен всегда: без него парсинг и публикация останутся в очереди.

### Шаг 11. Firewall

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

Порт 8000 наружу не открывайте.

## Обновление проекта

```bash
cd /opt/avito
mkdir -p backups
docker compose exec -T db pg_dump -U avito avito_mvp > "backups/db-$(date +%F-%H%M).sql"
tar --exclude='data/chrome-profile' -czf "backups/data-$(date +%F-%H%M).tar.gz" data

git pull
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 web worker
```

Миграции выполняются автоматически при старте `web`. Не используйте `docker compose down -v` — это удалит базу и media.

## Бэкапы

База:

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U avito avito_mvp > "backups/db-$(date +%F).sql"
```

Фото и данные:

```bash
tar --exclude='data/chrome-profile' -czf "backups/data-$(date +%F).tar.gz" data
```

Сохраняйте `.env`, `TOKEN_ENCRYPTION_KEY` и `DJANGO_SECRET_KEY` отдельно от сервера. Без ключа шифрования токены VK не восстановятся.

Пример cron:

```cron
0 4 * * * cd /opt/avito && docker compose exec -T db pg_dump -U avito avito_mvp > backups/db-$(date +\%F).sql
```

## Прокси

Прокси — единый пул для Авито и VK. Проверка идёт по обоим сервисам: рабочим считается только прокси, через который доступны и Авито, и VK API.

В веб-интерфейсе:

```text
http://user:pass@1.2.3.4:8080
socks5://user:pass@5.6.7.8:1080
socks4://user:pass@9.10.11.12:4145
1.2.3.4:1080
```

Для больших файлов:

Локально:

```bash
python manage.py import_proxies ~/Downloads/data.txt --workers 100 --timeout 4
python manage.py import_proxies ~/Downloads/data.txt --dry-run
```

На сервере в Docker:

```bash
docker compose cp ~/Downloads/data.txt web:/tmp/data.txt
docker compose exec web python manage.py import_proxies /tmp/data.txt --workers 100 --timeout 4
```

Нерабочие новые прокси не добавляются. Кнопки «Проверить все» и «Удалить нерабочие» — в настройках.

## Ограничения и известные проблемы

- **Код 15 VK** — `wall.post` недоступен non-standalone приложению. Решение: ключ сообщества в настройках или standalone user token.
- **Код 27 VK** — токен сообщества не умеет загружать фото. Фото загружаются только пользовательским токеном.
- **Пустой `photo` / HTTP 405** — временное ограничение VK на загрузку фото. Смена прокси не помогает; нужно подождать, не спамить повторными публикациями.
- **Авито-челлендж** — страница может требовать проверку безопасности; повторите позже. Постоянный профиль Chrome сохраняет куки.
- **SOCKS5 с паролем** используется только в `requests`, не в Chrome. Для Chrome подходят HTTP и SOCKS без пароля.
- **Один пост на пару «объявление + сообщество»** — намеренное ограничение MVP.
- Публикация только ручная; планировщика и автопостинга пока нет.

## Тесты и линтер

```bash
python manage.py test
ruff check .
```

Внешние VK/Авито в тестах подменяются заглушками; реальные запросы не выполняются.

## Документация для агентов

Правила разработки и частые операции — в [AGENTS.md](AGENTS.md).
