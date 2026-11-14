#!/usr/bin/env python3
"""Session-end gate: verify the full Mini App delivery chain and auto-fix it.

Run after every change session, BEFORE reporting the task done:
    python3 tools/check_tunnel.py        # waits up to ~2 min for self-repair
    python3 tools/check_tunnel.py --fast # single pass, no waiting (exit 1 if broken)

Checks, in order:
1. local web server on 127.0.0.1:8321 answers /api/health with 200;
2. the tunnel keeper (tools/tunnel_keepalive.py) is running — restarted if not;
3. the public URL in data/tunnel_url answers /api/health with 200 — if the
   session is dead, the keeper flips it, so we wait for a fresh URL;
4. the bot's Telegram menu button points at data/tunnel_url + /app —
   if stale, fixed right here via setChatMenuButton;
5. the Mini App page itself loads through the public URL (/app, HTML 200).

Exit code 0 only when every check passes.
"""
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL_FILE = ROOT / 'data' / 'tunnel_url'
ENV_FILE = ROOT / '.env'
WEB_PORT = 8321
KEEPER_LOG = '/tmp/tama_tunnel.log'
FLIP_WAIT_SECONDS = 90   # max time to wait for the keeper to re-open a tunnel
PROBE_TIMEOUT = 8

_ok = True


def check(label: str, ok: bool, detail: str = '') -> bool:
    global _ok
    _ok = _ok and ok
    mark = 'PASS' if ok else 'FAIL'
    line = '[%s] %s' % (mark, label)
    if detail:
        line += ' — ' + detail
    print(line, flush=True)
    return ok


def http_status(url: str) -> tuple[int, str]:
    """(status, full body); (0, '') on network error."""
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT) as resp:
            return resp.status, resp.read(1024 * 1024).decode(errors='ignore')
    except Exception:
        return 0, ''


def bot_token() -> str:
    for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
        key, _, val = line.strip().partition('=')
        if key == 'TAMAGOTCHI_BOT_TOKEN':
            return val.strip().strip('"').strip("'")
    return ''


def tg(method: str, payload: dict) -> dict:
    req = urllib.request.Request(
        'https://api.telegram.org/bot%s/%s' % (bot_token(), method),
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def keeper_running() -> bool:
    out = subprocess.run(['pgrep', '-f', 'tools/tunnel_keepalive.py'],
                         capture_output=True, text=True)
    return out.returncode == 0


def start_keeper() -> None:
    log = open(KEEPER_LOG, 'ab')
    subprocess.Popen(
        ['python3', str(ROOT / 'tools' / 'tunnel_keepalive.py')],
        stdout=log, stderr=log, start_new_session=True)
    print('keeper restarted (log: %s)' % KEEPER_LOG, flush=True)


def public_url() -> str:
    try:
        return URL_FILE.read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def main() -> None:
    fast = '--fast' in sys.argv

    status, _ = http_status('http://127.0.0.1:%d/api/health' % WEB_PORT)
    if not check('local server :%d/api/health' % WEB_PORT, status == 200,
                 'HTTP %s' % (status or 'no answer')):
        print('бот не запущен — чинить туннель бессмысленно', flush=True)
        sys.exit(2)

    if not check('tunnel keeper process', keeper_running()):
        start_keeper()
        time.sleep(2)

    deadline = time.monotonic() + (0 if fast else FLIP_WAIT_SECONDS)
    url = ''
    while True:
        url = public_url()
        status, _ = http_status(url + '/api/health') if url else (0, '')
        if status == 200:
            break
        if time.monotonic() >= deadline:
            check('public URL /api/health', False,
                  (url or 'data/tunnel_url пуст') +
                  (' (HTTP %s)' % (status or 'no answer')))
            sys.exit(1)
        time.sleep(5)
    check('public URL /api/health', True, url)

    full = url + '/app'
    menu = tg('getChatMenuButton', {})
    current = (menu.get('result', {}).get('web_app', {}) or {}).get('url', '')
    if current == full:
        check('Telegram menu button', True, current)
    else:
        tg('setChatMenuButton', {'menu_button': {
            'type': 'web_app', 'text': '🐣 Питомец', 'web_app': {'url': full}}})
        check('Telegram menu button', True, '%s -> %s (исправлено)' % (current, full))

    # Страница /app — 40 КБ через туннель: локалтуннель флапает на крупных
    # телах, поэтому (в отличие от лёгкого /api/health) даём до 4 попыток.
    attempts = 1 if fast else 4
    status, body = 0, ''
    for i in range(attempts):
        status, body = http_status(full)
        if status == 200 and 'petWrap' in body:
            break
        if i + 1 < attempts:
            time.sleep(3)
    check('Mini App page %s' % full,
          status == 200 and 'petWrap' in body,
          'HTTP %s' % (status or 'no answer'))

    print('== %s ==' % ('ВСЁ ЖИВОЕ' if _ok else 'ЕСТЬ ПРОБЛЕМЫ'), flush=True)
    sys.exit(0 if _ok else 1)


if __name__ == '__main__':
    main()
