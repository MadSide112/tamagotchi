# Tamagotchi-бот (Telegram Mini App) — правила для агента

## Формат ответов

- Русский язык, кратко, по делу.
- Строго три пункта в конце КАЖДОГО ответа:
  1. **Что я сделал** — конкретное действие.
  2. **Что нужно сделать тебе** — следующий шаг пользователя.
  3. **Какой исход ожидаем** — что должно получиться.
- Длинные технические объяснения — только по явной просьбе.

## Правило закрытия сессии (ОБЯЗАТЕЛЬНО)

Каждая сессия изменений заканчивается:

```
./venv/bin/python tools/check_tunnel.py
```

Задача не считается выполненной без вывода `== ВСЁ ЖИВОЕ ==`. Быстрый вариант
без ожидания: `--fast`.

## Что за проект

Python-бот Telegram: тамагочи с Mini App. Один процесс = long polling + aiohttp
веб-сервер на `127.0.0.1:8321`. SQLite в `data/tamagotchi.db`. Веб-морда —
один файл `webapp/index.html` (vanilla JS). Публичный HTTPS — бесплатный туннель
localhost.run через ssh, keeper `tools/tunnel_keepalive.py` пишет URL в
`data/tunnel_url`, watcher в `main.py` обновляет кнопку меню Telegram.

## Структура

- `bot/` — Telegram API (`api.py`), long polling (`polling.py`), обработчики (`handlers.py`), веб-сервер (`server.py`)
- `game/` — чистая логика: `engine.py` (диспетчер `ACTIONS`/`apply`), `balance.py` (все константы и лимиты), `progress.py` (квесты/ачивки/престиж), `minigames.py`, `cases.py`, `promo.py`, `pets.py`, `state.py`
- `storage/db.py` — sqlite3: sync + `to_thread` + lock на пользователя
- `webapp/index.html` — вся мини-аппа; ассеты в `webapp/assets/`
- `tools/` — `check_tunnel.py` (гейт сессии), `tunnel_keepalive.py`
- `tests/` — unittest, запуск: `./venv/bin/python -m unittest discover -s tests -q`

## Команды

- Рестарт бота: `lsof -ti :8321 | xargs kill -9; cd <корень> && TAMAGOTCHI_DEV_TEST=1 nohup ./venv/bin/python main.py > /tmp/tama_bot.log 2>&1 &`
- Dev-браузер (эмуляция Telegram): `http://127.0.0.1:8321/app_test` при `TAMAGOTCHI_DEV_TEST=1` (user 900000001, initData подписан сервером)
- Keeper туннеля: `nohup python3 tools/tunnel_keepalive.py >> /tmp/tama_tunnel.log 2>&1 &`

### Windows-машина (с 2026-11-16)

- venv: `venv/Scripts/python.exe` (не `venv/bin`).
- Рестарт бота: `netstat -ano | grep :8321` (узнать PID) → `taskkill //F //PID <pid>`
  (двойной слэш — Git Bash съедает одинарный), потом запуск как выше, но
  `./venv/Scripts/python.exe`.
- Лог keeper: `%TEMP%\tama_tunnel.log` — путь печатает check_tunnel при рестарте.

## Архитектурные правила

- Серверная валидация всего: клиент только просит (`action` + `arg`), лимиты — из `game/balance.py` (единый источник истины, например `NAME_MAX_LEN`).
- Новое действие: добавить в `engine.ACTIONS`, ветку в `_apply_core`, функцию `_apply_<action>`; веб-вызов идёт через `doAction` в `webapp/index.html`.
- Ответ `POST /api/pet` — `{state, message}`; флага success нет, клиент валидирует ввод предварительно.
- Ассеты `/assets/` кэшируются с `immutable` — после правки ассета нужен жёсткий рефреш (Cmd+Shift+R).

## Уроки (не наступать повторно)

- python-dotenv в venv НЕТ — `.env` парсить вручную (split по `=`).
- `window.prompt` в мобильных Telegram WebApp заблокирован — только кастомные модалки.
- rAF замирает в фоновых табах — серверные окна времени должны это покрывать.
- Туннель localhost.run выдаёт новый URL при каждом ронятии; старый отвечает 502 «no tunnel». Рабочая точка входа — всегда кнопка меню (её обновляет watcher).
- venv пересоздаётся на месте (`python3 -m venv venv && venv/bin/pip install -r requirements.lock`), не переносится.
- Если в workspace выше лежит Unity-ориентированный AGENTS.md — к этому проекту он не относится.
- После холодного старта первый прогон check_tunnel всегда даёт ЕСТЬ ПРОБЛЕМЫ
  (keeper не запущен → FAIL зафиксирован, потом гейт сам его поднял) — просто
  прогнать гейт второй раз.
