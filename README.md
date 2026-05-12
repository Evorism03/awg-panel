# AmneziaWG Admin MVP

Админ-панель для управления клиентами существующего AmneziaWG сервера.

Проект можно разрабатывать локально без установленного AmneziaWG: backend работает в `MOCK_AWG=true`, создает тестовый конфиг в `data/awg0.conf` и генерирует mock-ключи. На VPS mock-режим отключается, backend читает реальный конфиг AmneziaWG и вызывает команду `awg`.

## Возможности

- список peers из конфига
- создание клиента
- скачивание client `.conf`
- QR-код
- удаление клиента
- статистика через `awg show dump`
- reload через команду из `.env`

## Локальный запуск через Docker

```bash
cp .env.example .env
mkdir -p data
docker compose up -d --build
```

Открыть: `http://localhost:8080`

Токен берется из `ADMIN_TOKEN` в `.env`.

## Локальный запуск без Docker

Backend:

```bash
cp .env.example .env
cd backend
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8090
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Открыть: `http://localhost:5173`

## Перенос на VPS

1. Скопировать проект на сервер, например в `/opt/awg-panel`.
2. Создать production env:

```bash
cp .env.vps.example .env
nano .env
```

3. Проверить значения:

- `ADMIN_TOKEN` - длинный случайный токен
- `MOCK_AWG=false`
- `AWG_CONFIG_PATH` - реальный путь к конфигу AmneziaWG
- `AWG_DOCKER_CONTAINER` и `AWG_CONTAINER_CONFIG_PATH` - заполнить, если AmneziaWG работает в Docker-контейнере приложения Amnezia
- `SERVER_ENDPOINT` - публичный IP или домен сервера с портом WireGuard
- `RELOAD_COMMAND` - команда перезапуска интерфейса

4. Перед первым запуском сделать backup реального конфига:

```bash
cp /etc/amnezia/amneziawg/awg0.conf /etc/amnezia/amneziawg/awg0.conf.bak
```

Если AmneziaWG стоит в контейнере приложения Amnezia:

```bash
docker exec amnezia-awg2 cp /opt/amnezia/awg/awg0.conf /opt/amnezia/awg/awg0.conf.bak
```

5. Запустить backend на хосте VPS, если ему нужен доступ к `awg` и `systemctl`.

Пример ручного запуска:

```bash
cd /opt/awg-panel/backend
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
set -a
. /opt/awg-panel/.env
set +a
uvicorn app.main:app --host 127.0.0.1 --port 8090
```

Frontend можно собрать и отдать через nginx/reverse proxy. Важно закрыть панель firewall или reverse proxy с HTTPS.

## Важно

- Docker Compose в этом репозитории настроен в первую очередь для локального mock-режима.
- Для backend без Docker используй Python 3.12 или 3.13. Python 3.14 пока может не подойти для закрепленной версии `pydantic-core`.
- На VPS backend лучше запускать на хосте, потому что контейнер обычно не имеет нормального доступа к `awg`, `systemctl` и сетевому интерфейсу AmneziaWG.
- При каждом изменении конфига backend создает backup рядом с `AWG_CONFIG_PATH`.

## Безопасность

Панель использует Bearer token из `ADMIN_TOKEN`. Не оставляй `change-me` на сервере, закрывай порт панели и используй HTTPS.
