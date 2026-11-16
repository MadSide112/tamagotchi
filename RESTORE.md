# Восстановление из архива (инструкция для агента)

В архиве уже есть: весь код, git-история (.git), `.env` (токен бота),
`data/tamagotchi.db` (все питомцы). Ничего доустанавливать из внешних
мест не нужно, кроме системного Python 3.9+ и git.

Выполняй по порядку, из папки, куда положил архив:

1. Распаковать (создаст папку `tamagotchi/`):
   `tar -xzf tamagotchi_migration_*.tar.gz && cd tamagotchi`
2. Окружение: `python3 -m venv venv`
3. Зависимости: `./venv/bin/pip install -r requirements.lock`
4. Проверка кода: `./venv/bin/python -m unittest discover -s tests -q`
   — должно быть `Ran 138 tests ... OK`.
5. Запуск: `TAMAGOTCHI_DEV_TEST=1 nohup ./venv/bin/python main.py > /tmp/tama_bot.log 2>&1 &`
6. Гейт готовности (сам поднимет туннель и обновит кнопку в Telegram):
   `./venv/bin/python tools/check_tunnel.py`
   — задача не готова, пока не напечатал `== ВСЁ ЖИВОЕ ==`.

Дальше работай по правилам из `AGENTS.md` (в корне проекта): формат ответов,
архитектура, команды, проверенные уроки. Секреты: токен бота — в `.env`
(в gitignore, наружу не печатать); для `git push` нужен PAT в
`~/.config/tamagotchi/gh_token` (см. MIGRATION.md).

Примечания: `data/tunnel_url` в архиве нет — keeper откроет свежий туннель
сам. Публичный URL меняется при каждом переподключении ssh — это норма
бесплатного localhost.run.
