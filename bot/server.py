"""HTTP server for the Telegram Mini App (WebApp).

GET  /app       — the Mini App page (HTML)
GET  /assets/   — static sprites for the Mini App UI
GET  /app_test  — dev-only harness (env TAMAGOTCHI_DEV_TEST=1): the same page
                  with a stubbed Telegram.WebApp and server-signed initData,
                  so the UI can be exercised in a plain browser on localhost.
GET  /api/health— liveness probe (tunnel keeper uses it)
GET  /api/state — authenticated full pet state (+ bot username for links)
GET  /api/top   — authenticated leaderboard rows
POST /api/pet   — authenticated care API: body {initData, action, arg}

Every /api request is authenticated by validating Telegram initData
(HMAC-SHA256 with the bot token) — the same server-authoritative pipeline
as chat commands.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from aiohttp import web

from bot.security import validate_init_data
from game import engine
from game.cases import ui_meta as cases_ui_meta
from game.pets import SPECIES

log = logging.getLogger('tg.server')

DEV_TEST_ENV = 'TAMAGOTCHI_DEV_TEST'
DEV_TEST_USER_ID = 900000001


def _sign_dev_init_data(bot_token: str, now: int, user_id: int = DEV_TEST_USER_ID) -> str:
    """Build a valid initData payload for the dev harness (same algorithm
    the Telegram client uses; the server cannot tell it apart)."""
    user = json.dumps({'id': user_id, 'first_name': 'Тест', 'username': 'dev_tester',
                       'language_code': 'ru'}, ensure_ascii=False, separators=(',', ':'))
    pairs = {'auth_date': str(now), 'user': user}
    check = '\n'.join('%s=%s' % kv for kv in sorted(pairs.items()))
    secret = hmac.new(b'WebAppData', bot_token.encode('utf-8'), hashlib.sha256).digest()
    pairs['hash'] = hmac.new(secret, check.encode('utf-8'), hashlib.sha256).hexdigest()
    return urlencode(pairs)


_TG_JS_TAG = '<script src="https://telegram.org/js/telegram-web-app.js"></script>'

_DEV_STUB_JS = (
    'window.Telegram={WebApp:{'
    'initData:__INIT_DATA__,'
    'initDataUnsafe:__USER__,'
    'version:"7.10",platform:"unknown",colorScheme:"light",isExpanded:true,'
    'viewportStableHeight:640,'
    'expand:function(){},ready:function(){},close:function(){},'
    'setHeaderColor:function(){},setBackgroundColor:function(){},'
    'onEvent:function(){},offEvent:function(){},'
    'HapticFeedback:{impactOccurred:function(){},notificationOccurred:function(){},'
    'selectionChanged:function(){}}}};'
)


def build_web_app(app, bot_token: str, webapp_html: str,
                  assets_dir: Optional[Path] = None) -> web.Application:
    routes = web.RouteTableDef()

    @routes.get('/app')
    async def serve_app(request: web.Request) -> web.Response:
        return web.Response(text=webapp_html, content_type='text/html', charset='utf-8')

    @routes.get('/app_test')
    async def serve_app_test(request: web.Request) -> web.Response:
        if os.environ.get(DEV_TEST_ENV) != '1':
            return web.json_response({'error': 'disabled'}, status=404)
        init_data = _sign_dev_init_data(bot_token, int(time.time()))
        # initDataUnsafe в реальном клиенте — объект с ключом user, а не сам пользователь
        user = json.dumps({'user': {'id': DEV_TEST_USER_ID, 'first_name': 'Тест',
                                    'username': 'dev_tester', 'language_code': 'ru'}},
                          ensure_ascii=False)
        stub = _DEV_STUB_JS.replace('__INIT_DATA__', json.dumps(init_data)) \
                           .replace('__USER__', user)
        # replace the official CDN script tag so it cannot overwrite the stub
        if _TG_JS_TAG in webapp_html:
            html = webapp_html.replace(_TG_JS_TAG, '<script>' + stub + '</script>', 1)
        else:
            html = webapp_html.replace('<head>', '<head><script>' + stub + '</script>', 1)
        return web.Response(text=html, content_type='text/html', charset='utf-8')

    @routes.get('/api/health')
    async def health(request: web.Request) -> web.Response:
        return web.json_response({'ok': True})

    def _auth(request: web.Request) -> Optional[int]:
        return validate_init_data(request.query.get('initData', ''), bot_token)

    @routes.get('/api/state')
    async def api_state(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if user_id is None:
            return web.json_response({'error': 'unauthorized'}, status=401)
        state, _ = await app.web_action(user_id, 'sync')
        if state is None:
            return web.json_response({'error': 'no pet',
                                      'hint': 'Отправь боту /start'}, status=404)
        # meta: справочники для UI (виды питомцев + дропы сундуков).
        # Промокоды здесь НЕ публикуются — активация только на сервере.
        species_meta = [{'id': sid, 'title': sp['title'],
                         'img': sp['img'], 'faces': sp['faces']}
                        for sid, sp in SPECIES.items()]
        return web.json_response({'pet': state, 'bot': app.bot_username,
                                  'meta': {'species': species_meta,
                                           'cases': cases_ui_meta()}})

    @routes.get('/api/top')
    async def api_top(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if user_id is None:
            return web.json_response({'error': 'unauthorized'}, status=401)
        rows = await app.db.list_pets(10)
        return web.json_response({'rows': rows})

    @routes.post('/api/pet')
    async def api_pet(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'bad json'}, status=400)
        user_id = validate_init_data(str(body.get('initData', '')), bot_token)
        if user_id is None:
            log.warning('initData rejected (len=%d)', len(str(body.get('initData', ''))))
            return web.json_response({'error': 'unauthorized',
                                      'hint': 'Открой приложение через бота в Telegram'},
                                     status=401)
        action = str(body.get('action') or 'sync')
        if action not in engine.ACTIONS:
            return web.json_response({'error': 'unknown action'}, status=400)
        arg = str(body.get('arg') or '')[:32]
        state, message = await app.web_action(user_id, action, arg)
        if state is None:
            return web.json_response({'error': 'no pet',
                                      'hint': 'Отправь боту /start'}, status=404)
        return web.json_response({'state': state, 'message': message})

    application = web.Application()
    application.add_routes(routes)
    if assets_dir is not None:
        application.router.add_static('/assets/', str(assets_dir))

    @web.middleware
    async def assets_cache(request: web.Request, handler):
        response = await handler(request)
        if request.path.startswith('/assets/'):
            # ассеты неизменяемы: имена файлов фиксированы
            response.headers['Cache-Control'] = 'public, max-age=604800, immutable'
        return response

    application.middlewares.append(assets_cache)
    return application


async def run_web_server(app, bot_token: str, webapp_html: str, port: int,
                         assets_dir: Optional[Path] = None) -> web.AppRunner:
    runner = web.AppRunner(build_web_app(app, bot_token, webapp_html, assets_dir))
    await runner.setup()
    site = web.TCPSite(runner, host='127.0.0.1', port=port)
    await site.start()
    log.info('web server on http://127.0.0.1:%d/app', port)
    return runner
