"""Bot configuration: loads the Telegram bot token from env or .env file."""
import os

_ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN_ENV_VAR = 'TAMAGOTCHI_BOT_TOKEN'
PROXY_ENV_VAR = 'TAMAGOTCHI_PROXY'


def _read_env_file(key: str) -> str:
    env_path = os.path.join(_ROOT, '.env')
    if not os.path.exists(env_path):
        return ''
    with open(env_path, 'r', encoding='utf-8') as fh:
        for raw in fh:
            line = raw.strip()
            if line.startswith(key + '='):
                return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''


def load_bot_token() -> str:
    token = os.environ.get(TOKEN_ENV_VAR, '').strip()
    if token:
        return token
    return _read_env_file(TOKEN_ENV_VAR)


def load_proxy() -> str:
    """HTTP(S) or SOCKS proxy for reaching api.telegram.org, e.g. socks5://127.0.0.1:1080."""
    proxy = os.environ.get(PROXY_ENV_VAR, '').strip()
    if proxy:
        return proxy
    return _read_env_file(PROXY_ENV_VAR)
