"""Tamagotchi bot entrypoint: config, DB, widget, long polling, Mini App server.

Also starts a cloudflared quick tunnel so Telegram clients can reach the
Mini App over public HTTPS, and sets the bot's default menu button to open it.
"""
import asyncio
import logging
import pathlib
import sys

from bot.api import ApiError, TelegramApi
from bot.handlers import App
from bot.polling import run_polling
from bot.server import run_web_server
from config import load_bot_token, load_proxy
from storage.db import Db

BOT_COMMANDS = [
    {'command': 'start', 'description': 'Завести питомца'},
    {'command': 'name', 'description': 'Переименовать питомца'},
    {'command': 'stats', 'description': 'Показать статы'},
    {'command': 'top', 'description': 'Лидерборд'},
    {'command': 'help', 'description': 'Что умеет бот'},
]

WEB_PORT = 8321
MENU_BUTTON_TEXT = '🐣 Питомец'


def read_tunnel_url(root: pathlib.Path) -> str:
    try:
        return (root / 'data' / 'tunnel_url').read_text(encoding='utf-8').strip()
    except OSError:
        return ''


async def refresh_menu_button(api: TelegramApi, root: pathlib.Path,
                              app: App, interval: int = 10) -> None:
    """Watch data/tunnel_url (maintained by tools/tunnel_keepalive.py) and
    keep the bot's default menu button pointing at the live Mini App URL."""
    last = ''
    while True:
        url = read_tunnel_url(root)
        if url:
            full = url + '/app'
            if full != last:
                try:
                    await api.set_chat_menu_button({
                        'type': 'web_app', 'text': MENU_BUTTON_TEXT,
                        'web_app': {'url': full},
                    })
                    app.web_app_url = full
                    last = full
                    logging.info('menu button -> %s', full)
                except ApiError as err:
                    logging.warning('setChatMenuButton failed: %s', err.description)
        await asyncio.sleep(interval)


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
    webapp_html = (root / 'webapp' / 'index.html').read_text(encoding='utf-8')
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
                logging.warning('api.telegram.org недоступен (%s), повтор через %dс…',
                                err, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
        logging.info('bot @%s online', me['username'])
        await api.set_my_commands(BOT_COMMANDS)
        app = App(api, db, widget_html, bot_username=me['username'], bot_id=me['id'],
                  web_app_url='')
        runner = await run_web_server(app, token, webapp_html, WEB_PORT)
        logging.info('web server ready on port %d (waiting for tunnel url)', WEB_PORT)
        refresher = asyncio.create_task(refresh_menu_button(api, root, app))
        try:
            await run_polling(app)
        finally:
            refresher.cancel()
            await runner.cleanup()


if __name__ == '__main__':
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
