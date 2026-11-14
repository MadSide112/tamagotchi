"""Tamagotchi bot entrypoint: config, DB, widget template, long polling."""
import asyncio
import logging
import pathlib
import sys

from bot.api import ApiError, TelegramApi
from bot.handlers import App
from bot.polling import run_polling
from config import load_bot_token, load_proxy
from storage.db import Db

BOT_COMMANDS = [
    {'command': 'start', 'description': 'Завести питомца'},
    {'command': 'name', 'description': 'Переименовать питомца'},
    {'command': 'stats', 'description': 'Показать статы'},
    {'command': 'top', 'description': 'Лидерборд'},
    {'command': 'help', 'description': 'Что умеет бот'},
]


async def amain() -> None:
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    token = load_bot_token()
    if not token:
        logging.critical('Нет токена: задай TAMAGOTCHI_BOT_TOKEN в окружении или в .env')
        sys.exit(1)
    proxy = load_proxy()
    if proxy:
        logging.info('использую прокси: %s', proxy)
    root = pathlib.Path(__file__).resolve().parent
    widget_html = (root / 'widget' / 'template.html').read_text(encoding='utf-8')
    db = Db(str(root / 'data' / 'tamagotchi.db'))
    async with TelegramApi(token, proxy) as api:
        delay = 2
        while True:
            try:
                me = await api.get_me()
                break
            except ApiError as err:
                logging.critical('Telegram отклонил токен: %s', err.description)
                sys.exit(1)
            except Exception as err:
                logging.warning('api.telegram.org недоступен (%s), повтор через %dс…', err, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
        logging.info('bot @%s online', me['username'])
        await api.set_my_commands(BOT_COMMANDS)
        app = App(api, db, widget_html, bot_username=me['username'], bot_id=me['id'])
        await run_polling(app)


if __name__ == '__main__':
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
