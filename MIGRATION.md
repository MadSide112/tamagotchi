# Миграция проекта на другое устройство

## Что переносится git'ом (после `git push` — всё на GitHub)

Код, тесты, вебаппа, tools, README, AGENTS.md, CLAUDE.md,
`requirements.txt` / `requirements.lock`. История коммитов полная.

## Что НЕ в git (перенести вручную)

| Файл | Что это |
|---|---|
| `.env` | токен бота `TAMAGOTCHI_BOT_TOKEN` (+ опц. `TAMAGOTCHI_PROXY`) |
| `data/tamagotchi.db` | живые данные: все питомцы |
| `~/.config/tamagotchi/gh_token` | PAT для `git push` (лежит ВНЕ папки проекта) |

Не переносятся: `venv/` (пересоздаётся), `bin/` (легаси-cloudflared — туннель
работает через ssh на localhost.run), `data/tunnel_url` (машино-зависимый URL,
keeper откроет новый).

## Способ 1 — git clone + перенос секретов

1. `git clone https://github.com/MadSide112/tamagotchi.git && cd tamagotchi`
2. `python3 -m venv venv` (нужен Python 3.9+; на старой машине — 3.9.6)
3. `./venv/bin/pip install -r requirements.lock`
4. `cp .env.example .env` и вписать тот же токен от @BotFather
5. Положить `tamagotchi.db` в `data/` (взять из бандла или scp со старой машины)
6. Запуск: `TAMAGOTCHI_DEV_TEST=1 nohup ./venv/bin/python main.py > /tmp/tama_bot.log 2>&1 &`
7. Проверка: `./venv/bin/python -m unittest discover -s tests -q`,
   затем `./venv/bin/python tools/check_tunnel.py` → `== ВСЁ ЖИВОЕ ==`

Системные зависимости: `git`, `ssh` (туннель), Python 3.9+. Больше ничего.

## Способ 2 — одним архивом (GitHub не нужен)

На старой машине:

```
./tools/make_migration_bundle.sh
```

Получишь `dist/tamagotchi_migration_<дата>.tar.gz` — код + git-история + `.env` +
БД. Перебросить (AirDrop / scp / флешка), распаковать, выполнить шаги 2, 3, 6, 7
из способа 1 (venv и .env уже внутри, клонировать не нужно).

## ZCode на новом устройстве

- Открой папку проекта как workspace — `AGENTS.md` подхватится автоматически
  (правила сессий, команды, архитектура).
- Для push на GitHub положи PAT в `~/.config/tamagotchi/gh_token` (создать на
  github.com → Settings → Developer settings → Fine-grained token с правом
  push в этот репозиторий) и пуш так:
  `git push -q "https://x-access-token:$(cat ~/.config/tamagotchi/gh_token)@github.com/MadSide112/tamagotchi.git" main`
