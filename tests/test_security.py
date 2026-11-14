"""Tests for Telegram WebApp initData validation (official HMAC algorithm)."""
import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from bot.security import validate_init_data

BOT_TOKEN = '720001:TEST_TOKEN'
USER = {'id': 754216474, 'first_name': 'Mad'}


def make_init_data(user=USER, token=BOT_TOKEN, auth_age=0, tamper=None):
    params = {
        'auth_date': str(int(time.time()) - auth_age),
        'query_id': 'AAF123',
        'user': json.dumps(user),
    }
    check_string = '\n'.join('%s=%s' % (k, v) for k, v in sorted(params.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    params['hash'] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if tamper:
        params[tamper[0]] = tamper[1]
    return urlencode(params, safe=':{}"')


class TestValidateInitData(unittest.TestCase):
    def test_valid_payload_returns_user_id(self):
        self.assertEqual(validate_init_data(make_init_data(), BOT_TOKEN), USER['id'])

    def test_wrong_token_rejected(self):
        self.assertIsNone(validate_init_data(make_init_data(), '999:OTHER'))

    def test_tampered_field_rejected(self):
        self.assertIsNone(validate_init_data(
            make_init_data(tamper=('user', json.dumps({'id': 1}))), BOT_TOKEN))

    def test_stale_auth_date_rejected(self):
        self.assertIsNone(validate_init_data(
            make_init_data(auth_age=25 * 3600), BOT_TOKEN))

    def test_garbage_rejected(self):
        self.assertIsNone(validate_init_data('', BOT_TOKEN))
        self.assertIsNone(validate_init_data('not a query string', BOT_TOKEN))

    def test_bot_token_required(self):
        self.assertIsNone(validate_init_data(make_init_data(), ''))


if __name__ == '__main__':
    unittest.main()
