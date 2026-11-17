"""HTTP server for the Telegram Mini App (WebApp).

GET  /app       — the Mini App page (HTML, gzip, ETag/304 revalidation)
GET  /assets/   — static sprites for the Mini App UI
GET  /app_test  — dev-only harness (env TAMAGOTCHI_DEV_TEST=1): the same page
                  with a stubbed Telegram.WebApp and server-signed initData,
                  so the UI can be exercised in a plain browser on localhost.
GET  /api/health— liveness probe (tunnel keeper uses it)
GET  /api/state — authenticated full pet state (+ bot username for links)
GET  /api/top   — authenticated leaderboard rows
GET  /api/arena_top — authenticated arena leaderboard (by rating)
POST /api/pet   — authenticated care API: body {initData, action, arg}

Every /api request is authenticated by validating Telegram initData
(HMAC-SHA256 with the bot token) — the same server-authoritative pipeline
as chat commands.
"""
import gzip
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
from game import progress
from game.arena import pick_opponents
from game.balance import (
    ARENA_CANDIDATES,
    ARENA_DAILY_CAP,
    ARENA_ENERGY_COST,
    ARENA_MIN_LEVEL,
    ARENA_WIN_COINS,
    ARENA_WIN_XP,
    BT_DAILY_COIN_CAP,
    BT_ENERGY_COST,
    BT_POTIONS_PER_BATTLE,
    BT_SKILLS,
    CLASSES,
    DAILY_REWARDS,
    ELEMENTS,
    FRIEND_ACC,
    MAX_LEVEL,
    MG_ENERGY_COST,
    QUEST_POOL,
    SPECIES_ELEMENT,
)
from game.cases import ui_meta as cases_ui_meta
from game.expeditions import expeditions_meta
from game.gear import gear_meta
from game.minigames import games_meta
from game.pets import SPECIES
from game.state import PetState

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


def _wants_gzip(accept: str) -> bool:
    """True if Accept-Encoding lists gzip with a non-zero q-value."""
    try:
        for part in accept.split(','):
            pieces = part.strip().lower().split(';')
            if pieces[0] != 'gzip':
                continue
            q = 1.0
            for param in pieces[1:]:
                key, _, val = param.strip().partition('=')
                if key == 'q':
                    q = float(val)
            if q > 0:
                return True
    except ValueError:
        return 'gzip' in accept.lower()
    return False


def build_web_app(app, bot_token: str, webapp_html: str,
                  assets_dir: Optional[Path] = None) -> web.Application:
    routes = web.RouteTableDef()

    # Страница фиксирована на время жизни сервера: считаем ETag и gzip один раз.
    # no-cache заставляет вебвью переспрашивать (304 без тела) — критично
    # при медленном туннеле, где передача 40 КБ занимает до десятков секунд.
    page_raw = webapp_html.encode('utf-8')
    page_etag = '"%s"' % hashlib.sha1(page_raw).hexdigest()
    page_gzip = gzip.compress(page_raw, compresslevel=9)
    page_headers = {'Cache-Control': 'no-cache', 'Vary': 'Accept-Encoding'}

    @routes.get('/app')
    async def serve_app(request: web.Request) -> web.Response:
        if request.headers.get('If-None-Match') == page_etag:
            return web.Response(status=304, headers={**page_headers,
                                                     'ETag': page_etag})
        headers = {**page_headers, 'ETag': page_etag}
        if _wants_gzip(request.headers.get('Accept-Encoding', '')):
            headers['Content-Encoding'] = 'gzip'
            return web.Response(body=page_gzip, headers=headers,
                                content_type='text/html', charset='utf-8')
        return web.Response(body=page_raw, headers=headers,
                            content_type='text/html', charset='utf-8')

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

    def _tz_hours(raw) -> float:
        """Client timezone offset in hours east of UTC (e.g. MSK = 3)."""
        try:
            tz = float(raw)
        except (TypeError, ValueError):
            return 0.0
        return max(-14.0, min(14.0, tz))

    @routes.get('/api/state')
    async def api_state(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if user_id is None:
            return web.json_response({'error': 'unauthorized'}, status=401)
        tz = _tz_hours(request.query.get('tz'))
        state, _, daily = await app.web_action(user_id, 'sync', tz_offset=tz)
        if state is None:
            return web.json_response({'error': 'no pet',
                                      'hint': 'Отправь боту /start'}, status=404)
        # meta: справочники для UI (виды питомцев + дропы сундуков).
        # Промокоды здесь НЕ публикуются — активация только на сервере.
        species_meta = [{'id': sid, 'title': sp['title'], 'img': sp['img'],
                         'sleep': sp['sleep'], 'faces': sp['faces'],
                         'where': sp.get('where', '')}
                        for sid, sp in SPECIES.items()]
        # прогресс ачивок (только чтение — метрики для UI)
        row = await app.db.get_pet(user_id)
        achv_progress = (progress.progress_for(PetState.from_json(row['state']))
                         if row else {})
        # справочник боевой системы + соперники арены (по уровню бойца)
        arena_rows = await app.db.arena_rows(user_id)
        battle_meta = {
            'elements': dict(ELEMENTS),
            'species_element': dict(SPECIES_ELEMENT),
            'expeditions': expeditions_meta(),
            'gear': gear_meta(),
            'skills': dict(BT_SKILLS),
            'arena': {'min_level': ARENA_MIN_LEVEL,
                      'daily_cap': ARENA_DAILY_CAP,
                      'energy_cost': int(ARENA_ENERGY_COST),
                      'win_coins': ARENA_WIN_COINS,
                      'win_xp': ARENA_WIN_XP,
                      'candidates': pick_opponents(arena_rows, user_id,
                                                   state['level'],
                                                   ARENA_CANDIDATES)},
            'bt_energy_cost': int(BT_ENERGY_COST),
            'potions_max': BT_POTIONS_PER_BATTLE,
            'daily_coin_cap': BT_DAILY_COIN_CAP,
        }
        return web.json_response({'pet': state, 'bot': app.bot_username,
                                  'achv_progress': achv_progress,
                                  'daily': daily,
                                  'meta': {'battle': battle_meta,
                                           'species': species_meta,
                                           'cases': cases_ui_meta(),
                                           'games': games_meta(),
                                           'energy_cost': int(MG_ENERGY_COST),
                                           'room': progress.room_meta(),
                                           'classes': [
                                               {'id': cid, 'title': c['title'],
                                                'stat': c['stat'], 'desc': c['desc']}
                                               for cid, c in CLASSES.items()],
                                           'quests_pool': [
                                               {'id': q['id'], 'title': q['title'],
                                                'reward': q['reward']}
                                               for q in QUEST_POOL],
                                           'achv': progress.achv_meta(),
                                           'friend': [
                                               {'id': fid, 'title': f['title'],
                                                'need': f['need']}
                                               for fid, f in FRIEND_ACC.items()],
                                           'max_level': MAX_LEVEL,
                                           'daily_rewards': DAILY_REWARDS}})

    @routes.get('/api/top')
    async def api_top(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if user_id is None:
            return web.json_response({'error': 'unauthorized'}, status=401)
        rows = await app.db.list_pets(10)
        return web.json_response({'rows': rows})

    @routes.get('/api/arena_top')
    async def api_arena_top(request: web.Request) -> web.Response:
        user_id = _auth(request)
        if user_id is None:
            return web.json_response({'error': 'unauthorized'}, status=401)
        rows = await app.db.arena_top(10)
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
        tz = _tz_hours(body.get('tz'))
        state, message, daily = await app.web_action(user_id, action, arg, tz_offset=tz)
        if state is None:
            return web.json_response({'error': 'no pet',
                                      'hint': 'Отправь боту /start'}, status=404)
        return web.json_response({'state': state, 'message': message, 'daily': daily})

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
