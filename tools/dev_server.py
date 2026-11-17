"""Dev web server: serves the Mini App locally WITHOUT Telegram polling.

Run:  python tools/dev_server.py [--port 8321]
Open: http://127.0.0.1:8321/app_test

Unlike main.py this never contacts api.telegram.org, so it can run next
to the production bot without stealing getUpdates (409 Conflict).
It forces TAMAGOTCHI_DEV_TEST=1, which enables the /app_test harness
(bot/server.py): Telegram.WebApp is stubbed with a server-signed dev
user (id 900000001), so the whole UI works in a plain browser.
"""
import argparse
import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.handlers import App  # noqa: E402
from bot.server import DEV_TEST_ENV, run_web_server  # noqa: E402
from config import load_bot_token  # noqa: E402
from storage.db import Db  # noqa: E402


async def _serve(app: App, token: str, webapp_html: str, port: int) -> None:
    await run_web_server(app, token, webapp_html, port,
                         assets_dir=ROOT / 'webapp' / 'assets')
    print('dev Mini App:  http://127.0.0.1:%d/app_test' % port)
    print('Ctrl+C — остановить')
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    parser = argparse.ArgumentParser(description='Mini App dev server (no polling)')
    parser.add_argument('--port', type=int, default=8321)
    args = parser.parse_args()

    token = load_bot_token()
    if not token:
        sys.exit('Нет токена: задай TAMAGOTCHI_BOT_TOKEN в окружении или в .env')
    os.environ[DEV_TEST_ENV] = '1'

    webapp_html = (ROOT / 'webapp' / 'index.html').read_text(encoding='utf-8')
    app = App(None, Db(str(ROOT / 'data' / 'tamagotchi.db')), '',
              bot_username='dev_local', bot_id=0)
    try:
        asyncio.run(_serve(app, token, webapp_html, args.port))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
