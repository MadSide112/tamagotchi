"""HTTP server for the Telegram Mini App (WebApp).

GET  /app     — the Mini App page (HTML)
POST /api/pet — authenticated care API: body {initData, action, arg};

Every request is authenticated by validating Telegram initData (HMAC-SHA256
with the bot token) — the same server-authoritative pipeline as chat commands.
"""
import logging
from aiohttp import web

from bot.security import validate_init_data, validate_init_data_verbose
from game import engine

log = logging.getLogger('tg.server')


def build_web_app(app, bot_token: str, webapp_html: str) -> web.Application:
    routes = web.RouteTableDef()

    @routes.get('/app')
    async def serve_app(request: web.Request) -> web.Response:
        return web.Response(text=webapp_html, content_type='text/html', charset='utf-8')

    @routes.get('/api/health')
    async def health(request: web.Request) -> web.Response:
        return web.json_response({'ok': True})

    @routes.post('/api/pet')
    async def api_pet(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'bad json'}, status=400)
        user_id, reason = validate_init_data_verbose(str(body.get('initData', '')), bot_token)
        if user_id is None:
            log.warning('initData rejected: %s (len=%d)',
                        reason, len(str(body.get('initData', ''))))
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
    return application


async def run_web_server(app, bot_token: str, webapp_html: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_web_app(app, bot_token, webapp_html))
    await runner.setup()
    site = web.TCPSite(runner, host='127.0.0.1', port=port)
    await site.start()
    log.info('web server on http://127.0.0.1:%d/app', port)
    return runner
