"""Standalone tunnel keeper: keeps a localhost.run SSH tunnel alive and
writes the current public URL into data/tunnel_url for the bot to pick up.

Run it once and leave it running:  python3 tools/tunnel_keepalive.py
The bot (main.py) reads data/tunnel_url and refreshes the menu button.
"""
import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL_FILE = ROOT / 'data' / 'tunnel_url'
WEB_PORT = 8321

SSH_ARGS = [
    'ssh', '-o', 'StrictHostKeyChecking=accept-new',
    '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
    '-o', 'ExitOnForwardFailure=yes',
    '-R', '80:127.0.0.1:%d' % WEB_PORT, 'nokey@localhost.run',
]


def save_url(url: str) -> None:
    tmp = URL_FILE.with_suffix('.tmp')
    tmp.write_text(url, encoding='utf-8')
    tmp.replace(URL_FILE)


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
            for token in text_tokens(line):
                if token.startswith('https://') and '.lhr.life' in token:
                    holder['url'] = token.rstrip('.,')
                    save_url(holder['url'])
                    print('tunnel url: %s' % holder['url'], flush=True)
                    break

    def text_tokens(line) -> list:
        return line.decode(errors='ignore').split()

    async def wait_url() -> str:
        while not holder['url']:
            await asyncio.sleep(0.5)
        return holder['url']

    drain_task = asyncio.create_task(drain())
    try:
        url = await asyncio.wait_for(wait_url(), timeout=45)
    except asyncio.TimeoutError:
        if proc.returncode is None:
            proc.terminate()
        return ''
    if url:
        # session is live: wait here until ssh actually exits
        await proc.wait()
    drain_task.cancel()
    save_url('')  # dead session must not be served
    return url


async def main() -> None:
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        attempt += 1
        print('starting tunnel (attempt %d)…' % attempt, flush=True)
        url = ''
        try:
            url = await run_tunnel_once()
        except Exception as exc:
            print('tunnel error: %r' % exc, flush=True)
        print('tunnel session ended (url=%r), retrying in 5s' % url, flush=True)
        await asyncio.sleep(5)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
