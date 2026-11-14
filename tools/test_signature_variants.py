"""Offline brute-force of initData check-string variants against a real payload.

Usage: python3 tools/test_signature_variants.py /tmp/initdata_sample.txt
Reads BOT token from .env. Prints which variant (if any) reproduces the
received hash — that variant is the correct validation algorithm.
"""
import hashlib
import hmac
import json
import pathlib
import sys
from urllib.parse import parse_qsl

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOKEN = ''
for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
    if line.startswith('TAMAGOTCHI_BOT_TOKEN='):
        TOKEN = line.split('=', 1)[1].strip()
        break

raw = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').strip()
pairs = dict(parse_qsl(raw, keep_blank_values=True))
received = pairs.get('hash', '')
print('received hash: %s' % received)
print('fields: %s' % sorted(pairs.keys()))
print('has signature field: %s' % ('signature' in pairs))

secret_wad = hmac.new(b'WebAppData', TOKEN.encode(), hashlib.sha256).digest()
secret_sha = hashlib.sha256(TOKEN.encode()).digest()

def pairs_decoded():
    return [(k, v) for k, v in sorted(pairs.items()) if k not in ('hash', 'signature')]

def pairs_raw():
    raw_pairs = []
    for chunk in raw.split('&'):
        if '=' in chunk:
            k, _, v = chunk.partition('=')
            if k not in ('hash', 'signature'):
                raw_pairs.append((k, v))
    return sorted(raw_pairs)

def pairs_decoded_with_sig():
    return [(k, v) for k, v in sorted(pairs.items()) if k != 'hash']

def pairs_raw_with_sig():
    out = []
    for chunk in raw.split('&'):
        if '=' in chunk:
            k, _, v = chunk.partition('=')
            if k != 'hash':
                out.append((k, v))
    return sorted(out)

VARIANTS = {
    'decoded, exclude hash+signature (official)': (pairs_decoded, secret_wad),
    'raw-encoded, exclude hash+signature': (pairs_raw, secret_wad),
    'decoded, include signature': (pairs_decoded_with_sig, secret_wad),
    'raw-encoded, include signature': (pairs_raw_with_sig, secret_wad),
    'decoded, exclude hash+signature, secret=sha256(token)': (pairs_decoded, secret_sha),
    'raw-encoded, exclude hash+signature, secret=sha256(token)': (pairs_raw, secret_sha),
}

for name, (maker, secret) in VARIANTS.items():
    check = '\n'.join('%s=%s' % (k, v) for k, v in maker())
    calc = hmac.new(secret, check.encode('utf-8'), hashlib.sha256).hexdigest()
    match = 'MATCH!' if hmac.compare_digest(calc, received) else 'no'
    print('%-58s -> %s %s' % (name, calc[:12], match))
