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


def validate_init_data_verbose(init_data: str, bot_token: str,
                               now: Optional[int] = None):
    """Return (user_id, reason). user_id is None when rejected; reason explains why."""
    if not init_data:
        return None, 'empty initData'
    if not bot_token:
        return None, 'no bot token on server'
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None, 'initData is not a query string'
    received_hash = pairs.get('hash', '')
    auth_date = pairs.get('auth_date', '')
    user_raw = pairs.get('user', '')
    if not received_hash:
        return None, 'no hash field (client did not send initData?)'
    if not auth_date or not user_raw:
        return None, 'missing auth_date or user'

    data_check_string = '\n'.join(
        f'{key}={value}'
        for key, value in sorted(pairs.items())
        if key != 'hash'
        # NB: the 'signature' field IS included in the check string —
        # verified empirically against a real payload from Telegram clients
        # (tools/test_signature_variants.py); the old docs excluded it, but
        # current clients sign the string with signature included.
    )
    secret_key = hmac.new(b'WebAppData', bot_token.encode('utf-8'), hashlib.sha256).digest()
    calculated = hmac.new(secret_key, data_check_string.encode('utf-8'),
                          hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None, ('hash mismatch: got %s, computed %s, fields=%s'
                      % (received_hash[:10], calculated[:10], sorted(pairs.keys())))

    try:
        if now is None:
            now = int(time.time())
        age = now - int(auth_date)
        if age > MAX_INIT_DATA_AGE_SECONDS:
            return None, 'stale auth_date (%ds old)' % age
        import json
        user = json.loads(user_raw)
        user_id = int(user['id'])
        if user_id <= 0:
            return None, 'bad user id'
        return user_id, 'ok'
    except (ValueError, KeyError, TypeError) as exc:
        return None, 'bad user payload: %r' % exc


def validate_init_data(init_data: str, bot_token: str,
                       now: Optional[int] = None) -> Optional[int]:
    """Return the authenticated user_id, or None if the payload is invalid/stale."""
    user_id, _ = validate_init_data_verbose(init_data, bot_token, now)
    return user_id
