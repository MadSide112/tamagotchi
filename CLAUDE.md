# Tamagotchi bot — рабочие правила сессий

## Правило №1: закрытие сессии (ОБЯЗАТЕЛЬНО)

Каждая сессия изменений заканчивается проверкой всей цепочки Mini App:

```
python3 tools/check_tunnel.py
```

Скрипт сам чинит то, что может (перезапускает keeper, обновляет кнопку меню
через setChatMenuButton) и ждёт до 90 с. Задача НЕ считается выполненной,
пока скрипт не напечатал `== ВСЁ ЖИВОЕ ==`. Быстрый вариант без ожидания:
`python3 tools/check_tunnel.py --fast`.

## Почему возникает «no tunnel» (проверенный root cause)

- Туннель — бесплатный localhost.run (`nokey@localhost.run`), каждый
  переподключенный ssh-сеанс получает НОВЫЙ случайный URL. Старый URL
  навсегда отвечает 502 с телом «no tunnel» — именно его видит пользователь.
- Keeper `tools/tunnel_keepalive.py` (живёт отдельно от бота) раз в 10 с
  зондирует `<url>/api/health`; одна ошибка при живом локальном сервере →
  убивает ssh и открывает новый туннель, пишет URL в `data/tunnel_url`.
- Watcher в `main.py` (`refresh_menu_button`, интервал 10 с) читает
  `data/tunnel_url` и обновляет кнопку меню Telegram. Итого окно «мёртвого
  URL» после обрыва — порядка 10–25 с, всё это время открытая мини-аппа
  показывает «no tunnel». Это ограничение бесплатного туннеля, а не баг кода.
- Кнопки «Открыть питомца» внутри СТАРЫХ сообщений бота содержат URL на
  момент отправки и не обновляются — рабочая точка входа всегда кнопка меню.

## Запуск/перезапуск процессов

- Бот + веб-сервер (порт 8321, один процесс):
  `TAMAGOTCHI_DEV_TEST=1 nohup ./venv/bin/python main.py > /tmp/tama_bot.log 2>&1 &`
  (PID искать: `lsof -nP -iTCP:8321 -sTCP:LISTEN -t`)
- Keeper туннеля: `nohup python3 tools/tunnel_keepalive.py >> /tmp/tama_tunnel.log 2>&1 &`
  (после правки keeper.py его обязательно перезапустить; убивать и ssh-сеанс:
  `pkill -f "ssh.*localhost.run"`)

## Разное

- Тесты: `./venv/bin/python -m unittest discover -s tests -q` (pytest в venv нет).
- Dev-маршрут для браузера: `/app_test` при `TAMAGOTCHI_DEV_TEST=1` (stub initData, user id 900000001).
- python-dotenv в venv нет — .env парсить вручную (split по `=`).
- Секреты: токен бота в `.env` (в gitignore), PAT в `~/.config/tamagotchi/gh_token`.
  Пуш: `git push -q "https://x-access-token:$(cat ~/.config/tamagotchi/gh_token)@github.com/MadSide112/tamagotchi.git" main`.
