# AmneziaWG Admin MVP

Админ-панель для управления клиентами существующего AmneziaWG сервера.

Проект можно разрабатывать локально без установленного AmneziaWG: backend работает в `MOCK_AWG=true`, создает тестовый конфиг в `data/awg0.conf` и генерирует mock-ключи. Для VPS есть Docker-схема: backend и frontend живут в compose, а AmneziaWG поднимается отдельным сервисом `awg` в profile `server`.

## Возможности

- список peers из конфига
- создание клиента
- скачивание client `.conf`
- импорт готового AmneziaWG `.conf` с сохранением и выдачей public key
- удаление клиента
- отдельный список клиентов, которые не продлили подписку
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

## Docker-схема с AmneziaWG на сервере

Если хочешь держать серверный AmneziaWG в Docker Compose, включи profile `server` и укажи образ контейнера в `AWG_IMAGE`:

```bash
cp .env.vps.example .env
nano .env
docker compose --profile server up -d --build
```

Что важно:

- `backend` получает доступ к Docker socket и управляет контейнером `awg`;
- `AWG_DOCKER_CONTAINER` должен совпадать с `AWG_CONTAINER_NAME`;
- `AWG_CONTAINER_CONFIG_PATH` указывает путь к `awg0.conf` внутри контейнера;
- `AWG_CONTAINER_CLIENTS_TABLE_PATH` указывает путь к `clientsTable` внутри контейнера, обычно `/opt/amnezia/awg/clientsTable`;
- `AWG_HOST_CONFIG_DIR` хранит конфиг на хосте и монтируется в контейнер `awg`.

## Быстрая установка панели на VPS

Скрипт `scripts/install-vps.sh` ставит только Docker-контейнеры панели и не меняет системный nginx, сайты, конфиги в `/etc/nginx`, порты `80/443` и контейнер AmneziaWG. По умолчанию панель публикуется на отдельном порту `8080`, backend доступен только локально на `127.0.0.1:8090`.

Что нужно на VPS:

- Linux с root-доступом;
- Docker. Если Docker не установлен, скрипт попробует поставить `docker.io` через `apt-get`;
- уже работающий контейнер AmneziaWG. Если имя не определяется автоматически, передай `AWG_DOCKER_CONTAINER`;
- открытый порт панели, по умолчанию `8080`.

Запуск из каталога проекта на VPS:

```bash
sudo bash scripts/install-vps.sh
```

Пример для существующего контейнера AmneziaWG и нестандартного порта панели:

```bash
sudo AWG_DOCKER_CONTAINER=amnezia-awg2 \
  SERVER_IP=45.15.152.113 \
  AWG_PORT=46996 \
  PANEL_HTTP_PORT=8081 \
  bash scripts/install-vps.sh
```

Для добавления этого VPS в центральную панель нужны:

- `Panel URL`, например `http://45.15.152.113:8081`;
- `ADMIN_TOKEN`, который installer выводит после установки.

В центральной панели новый сервер добавляется во вкладке `Серверы`:

1. Нажми `Добавить сервер`.
2. Введи `Panel URL` удаленной панели, например `http://45.15.152.113:8081`.
3. Введи `ADMIN_TOKEN` этой панели.
4. Сохрани запись и нажми `Выбрать`, чтобы работать с этим VPS.

Скрипт:

- копирует проект в `/opt/awg-panel`;
- сохраняет backup старой установки в `/opt/awg-panel-backups`;
- сохраняет существующий `/opt/awg-panel/.env`, если он уже есть;
- создает `.env` с новым логином/паролем, если файла еще нет;
- запускает `awg-admin-frontend` и `awg-admin-backend` в отдельной Docker-сети;
- не перезаписывает и не перезапускает системный nginx.
- после установки печатает `Panel URL` и `ADMIN_TOKEN`; это данные, которые нужны для добавления VPS как нового сервера в существующую панель.

Если порт `8080` занят существующим сайтом или сервисом, скрипт остановится. Выбери другой порт:

```bash
sudo PANEL_HTTP_PORT=8081 bash scripts/install-vps.sh
```

### Установка дополнительного VPS без frontend-панели

Для дополнительного сервера можно поднять только API-агент: `backend`. Frontend в этом режиме не собирается, порт `8080` не нужен, а центральная панель подключается напрямую к backend.

```bash
sudo INSTALL_MODE=agent \
SERVER_IP=45.15.152.113 \
BACKEND_BIND=0.0.0.0 \
BACKEND_PORT=8090 \
bash scripts/install-vps.sh
```

Если контейнер AmneziaWG не определяется автоматически, передай его имя:

```bash
sudo INSTALL_MODE=agent \
AWG_DOCKER_CONTAINER=amnezia-awg2 \
SERVER_IP=45.15.152.113 \
AWG_PORT=46996 \
BACKEND_BIND=0.0.0.0 \
BACKEND_PORT=8090 \
bash scripts/install-vps.sh
```

После установки installer напечатает:

- `Panel URL`, например `http://45.15.152.113:8090`;
- `Panel token (ADMIN_TOKEN)`.

Эти два значения добавляются в центральной панели во вкладке `Серверы`. Для agent-режима должен быть открыт `BACKEND_PORT`, по умолчанию `8090`. Так как backend доступен по сети, закрывай порт firewall-ом по IP центральной панели или ставь reverse proxy с HTTPS.

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
- `AWG_IMAGE` - образ серверного контейнера AmneziaWG
- `AWG_CONTAINER_NAME` и `AWG_DOCKER_CONTAINER` - имя контейнера AmneziaWG
- `AWG_CONTAINER_CONFIG_PATH` - путь к конфигу внутри контейнера
- `AWG_CONTAINER_CLIENTS_TABLE_PATH` - путь к `clientsTable` внутри контейнера для хранения имен и дат создания клиентов
- `AWG_HOST_CONFIG_DIR` - каталог на хосте, куда монтируется конфиг
- `SERVER_ENDPOINT` - публичный IP или домен сервера с портом WireGuard
- `RELOAD_COMMAND` - команда перезапуска интерфейса

4. Перед первым запуском сделать backup реального конфига:

```bash
mkdir -p /opt/amnezia/awg
cp /opt/amnezia/awg/awg0.conf /opt/amnezia/awg/awg0.conf.bak
```

5. Запустить стек:

```bash
docker compose --profile server up -d --build
```

Frontend будет на `http://localhost:8080`, backend на `http://localhost:8090`.

## Важно

- Docker Compose теперь поддерживает две схемы: локальный mock-режим и серверный profile `server`.
- Для backend без Docker используй Python 3.12 или 3.13. Python 3.14 пока может не подойти для закрепленной версии `pydantic-core`.
- Backend в контейнере использует Docker socket, чтобы перезапускать и читать контейнер AmneziaWG.
- При каждом изменении конфига backend создает backup рядом с `AWG_CONFIG_PATH`.
- VPS не может восстановить полный клиентский конфиг только из `[Peer]` в `awg0.conf`: там нет приватного ключа клиента. Для выдачи готового `.conf` клиент должен быть создан панелью или импортирован через кнопку `Импорт .conf`.
- Клиенты с истекшим сроком автоматически удаляются из активного `awg0.conf` и сохраняются в списке непродленных подписок: `${CLIENTS_DIR}/expired-clients.json`. В Docker-схеме по умолчанию это `./data/clients/expired-clients.json` на хосте. API списка: `GET /api/expired-clients`.

## Безопасность

Панель использует Bearer token из `ADMIN_TOKEN`. Не оставляй `change-me` на сервере, закрывай порт панели и используй HTTPS.
