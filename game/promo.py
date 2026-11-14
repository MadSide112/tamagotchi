"""Promo codes: the dedicated single place to add or edit codes.

A code grants coins and/or a pet species. Redemption is single-use per
user: the "already used" flag lives in the promo_used table
(storage/db.py), and the per-user lock in bot/handlers.web_action makes
the check-and-mark atomic. To add a code, add one line to PROMO_CODES —
nothing else changes.
"""
from typing import List, Tuple

from game.pets import SPECIES
from game.state import PetState

PROMO_CODES = {
    'COINS200': {'coins': 200, 'title': '+200🪙'},
    'SNOWPET':  {'pet': 'snow_leopard', 'title': 'питомец 🐆 Снежный барс',
                 'dupe_coins': 150},
}

# When a promo pet is already owned and the code defines no dupe_coins.
DUPE_FALLBACK_COINS = 100

CODE_MAX_LEN = 24


def normalize(code: str) -> str:
    """Codes are case-insensitive and whitespace-tolerant."""
    return (code or '').strip().upper()[:CODE_MAX_LEN]


def redeem(st: PetState, code: str) -> Tuple[PetState, str, bool]:
    """Apply a promo code to the state (pure; the single-use db check is
    done by the caller before this runs). Returns (state, message, changed)."""
    data = PROMO_CODES.get(normalize(code))
    if data is None:
        return st, 'Такого промокода нет 🤔', False

    grants: List[str] = []
    coins = int(data.get('coins', 0))
    if coins:
        st.coins += coins
        grants.append('+%d🪙' % coins)

    pet = data.get('pet', '')
    if pet:
        title = SPECIES[pet]['title']
        if pet in st.pets:
            dupe = int(data.get('dupe_coins', DUPE_FALLBACK_COINS))
            st.coins += dupe
            grants.append('%s уже был — компенсация +%d🪙' % (title, dupe))
        else:
            st.pets.append(pet)
            st.species = pet  # a new pet is auto-equipped for the delight
            grants.append('новый питомец %s' % title)

    return st, '🎁 Промокод активирован: %s!' % ', '.join(grants), True
