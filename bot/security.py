"""Telegram WebApp initData validation (official algorithm).

initData is a URL-encoded query string signed by the bot: the server must
recompute HMAC-SHA256 with a key derived from the bot token and compare it
with the `hash` field. Stale payloads (old auth_date) are rejected too —
initData is only fresh while the WebApp session is alive.
"""
import hashlib
import hmac
import time
from typing import Optional
from urllib.parse import parse_qsl

MAX_INIT_DATA_AGE_SECONDS = 24 * 3600


def validate_init_data(init_data: str, bot_token: str,
                       now: Optional[int] = None) -> Optional[int]:
    """Return the authenticated user_id, or None if the payload is invalid/stale."""
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None
    received_hash = pairs.get('hash', '')
    auth_date = pairs.get('auth_date', '')
    user_raw = pairs.get('user', '')
    if not received_hash or not auth_date or not user_raw:
        return None

    data_check_string = '\n'.join(
        f'{key}={value}'
        for key, value in sorted(pairs.items())
        if key not in ('hash', 'signature')
    )
    secret_key = hmac.new(b'WebAppData', bot_token.encode('utf-8'), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode('utf-8'),
                          hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None

    try:
        if now is None:
            now = int(time.time())
        if now - int(auth_date) > MAX_INIT_DATA_AGE_SECONDS:
            return None
        import json
        user = json.loads(user_raw)
        user_id = int(user['id'])
        return user_id if user_id > 0 else None
    except (ValueError, KeyError, TypeError):
        return None
