"""Standalone tunnel keeper: keeps a localhost.run SSH tunnel alive and
writes the current public URL into data/tunnel_url for the bot to pick up.

Run it once and leave it running:  python3 tools/tunnel_keepalive.py
The bot (main.py) reads data/tunnel_url and refreshes the menu button.

localhost.run sometimes drops the port forwarding server-side while the
SSH transport stays connected (ssh never exits, tunnel returns 502
"no tunnel"). Client keepalives can't see that, so this keeper actively
probes the public URL: two consecutive failures while the local web
server is healthy => the ssh session is killed and a fresh tunnel is
opened (new URL gets picked up by main.py's menu-button watcher).
"""
import asyncio
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL_FILE = ROOT / 'data' / 'tunnel_url'
WEB_PORT = 8321
PROBE_INTERVAL = 10      # seconds between public-URL probes
PROBE_FAILS_ALLOWED = 1  # consecutive failures before killing the session
URL_TIMEOUT = 45         # seconds to wait for localhost.run to issue a URL

SSH_ARGS = [
    'ssh', '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
    '-o', 'ExitOnForwardFailure=yes',
    '-R', '80:127.0.0.1:%d' % WEB_PORT, 'nokey@localhost.run',
]


def log(msg: str) -> None:
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def save_url(url: str) -> None:
    tmp = URL_FILE.with_suffix('.tmp')
    tmp.write_text(url, encoding='utf-8')
    tmp.replace(URL_FILE)


async def http_ok(url: str) -> bool:
    """True if url/api/health answers HTTP 200 (502 'no tunnel' fails this)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            'curl', '-s', '-m', '8', '-o', os.devnull, '-w', '%{http_code}',
            url.rstrip('/') + '/api/health',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=12)
        return out.decode().strip() == '200'
    except Exception:
        return False


async def probe_cycle(url: str, proc: asyncio.subprocess.Process) -> None:
    """Kill the ssh session once the public URL is dead but local is fine."""
    fails = 0
    while proc.returncode is None:
        await asyncio.sleep(PROBE_INTERVAL)
        if proc.returncode is not None:
            return
        if await http_ok(url):
            fails = 0
            continue
        if not await http_ok('http://127.0.0.1:%d' % WEB_PORT):
            # local web server down: tunnel may be innocent, don't churn URLs
            log('probe: local server down, keeping tunnel')
            continue
        fails += 1
        log('probe: public URL dead (%d/%d)' % (fails, PROBE_FAILS_ALLOWED))
        if fails >= PROBE_FAILS_ALLOWED:
            log('probe: killing dead session to force reconnect')
            proc.terminate()
            return


async def run_tunnel_once() -> str:
    """One ssh session. Returns only when the session DIES; '' if no URL was issued.

    The URL is saved as soon as it appears; this coroutine then keeps draining
    stdout (a full pipe would freeze ssh) until the session actually ends.
    """
    proc = await asyncio.create_subprocess_exec(
        *SSH_ARGS, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    holder = {'url': ''}

    async def drain() -> None:
        while True:
            line = await proc.stdout.readline()
            if not line:
                return  # ssh exited
            if holder['url']:
                continue
            for token in line.decode(errors='ignore').split():
                if token.startswith('https://') and '.lhr.life' in token:
                    holder['url'] = token.rstrip('.,')
                    save_url(holder['url'])
                    log('tunnel url: %s' % holder['url'])
                    break

    drain_task = asyncio.create_task(drain())
    try:
        await asyncio.wait_for(_wait_url(holder), timeout=URL_TIMEOUT)
    except asyncio.TimeoutError:
        if proc.returncode is None:
            proc.terminate()
        drain_task.cancel()
        return ''
    url = holder['url']
    probe_task = asyncio.create_task(probe_cycle(url, proc))
    await proc.wait()
    probe_task.cancel()
    drain_task.cancel()
    save_url('')  # dead session must not be served
    return url


async def _wait_url(holder: dict) -> str:
    while not holder['url']:
        await asyncio.sleep(0.5)
    return holder['url']


async def main() -> None:
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        attempt += 1
        log('starting tunnel (attempt %d)…' % attempt)
        url = ''
        try:
            url = await run_tunnel_once()
        except Exception as exc:
            log('tunnel error: %r' % exc)
        log('tunnel session ended (url=%r), retrying in 5s' % url)
        await asyncio.sleep(5)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
