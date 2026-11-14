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


async def start_tunnel(port: int):
    """Open an SSH reverse tunnel via localhost.run; return (proc, public_url).

    localhost.run terminates TLS and gives a valid public HTTPS URL without
    an account; cloudflared is unusable here (edge TLS handshake is cut).
    """
    args = [
        'ssh', '-o', 'StrictHostKeyChecking=accept-new',
        '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
        '-o', 'ExitOnForwardFailure=yes',
        '-R', '80:127.0.0.1:%d' % port, 'nokey@localhost.run',
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    holder = {'url': ''}

    async def drain() -> None:
        # must keep reading forever: if the pipe fills, ssh freezes
        while True:
            line = await proc.stdout.readline()
            if not line:
                return
            text = line.decode(errors='ignore')
            if not holder['url']:
                for token in text.split():
                    if token.startswith('https://') and '.lhr.life' in token:
                        holder['url'] = token.rstrip('.,')
                        return

    async def wait_url() -> str:
        while not holder['url']:
            await asyncio.sleep(0.5)
        return holder['url']

    drain_task = asyncio.create_task(drain())
    try:
        url = await asyncio.wait_for(wait_url(), timeout=45)
    except asyncio.TimeoutError:
        url = ''
    if not url:
        logging.warning('туннель не поднялся (localhost.run недоступен?)')
        return proc, ''
    logging.info('туннель: %s', url)
    return proc, url


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

    tunnel_proc, public_url = await start_tunnel(WEB_PORT)
    web_app_url = (public_url + '/app') if public_url else ''

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
                  web_app_url=web_app_url)
        runner = None
        if public_url:
            runner = await run_web_server(app, token, webapp_html, WEB_PORT)
            await api.set_chat_menu_button({
                'type': 'web_app', 'text': MENU_BUTTON_TEXT,
                'web_app': {'url': web_app_url},
            })
            logging.info('Mini App: %s (кнопка меню «%s»)', web_app_url, MENU_BUTTON_TEXT)
        try:
            await run_polling(app)
        finally:
            if runner:
                await runner.cleanup()
            if tunnel_proc and tunnel_proc.returncode is None:
                tunnel_proc.terminate()


if __name__ == '__main__':
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass
