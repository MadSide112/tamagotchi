"""Promo codes: the dedicated single place to add or edit codes.

A code grants any subset of: coins, gems, a pet species, an accessory,
a temporary XP boost. Redemption is single-use per user: the "already
used" flag lives in the promo_used table (storage/db.py), and the
per-user lock in bot/handlers.web_action makes the check-and-mark
atomic. Timed codes add 'active_until' ('YYYY-MM-DD', UTC — the last
day the code works) and 'max_uses' (global activation limit, enforced
by handlers via db.promo_inc after a successful redemption).

To add a code, add one line to PROMO_CODES — nothing else changes.
"""
from typing import List, Tuple

from game.balance import SHOP
from game.cases import CHEST_ACC_TITLES
from game.pets import SPECIES
from game.state import PetState

PROMO_CODES = {
    'COINS200': {'coins': 200, 'title': '+200🪙'},
    'SNOWPET':  {'pet': 'snow_leopard', 'title': 'питомец 🐆 Снежный барс',
                 'dupe_coins': 150},
    'ELIXIR':   {'boost_hours': 24, 'title': '⚗️ ×2 XP на 24 часа'},
    'VIP':      {'acc': 'crown', 'title': 'наряд 👑 Корона'},
}

# When a promo pet is already owned and the code defines no dupe_coins.
DUPE_FALLBACK_COINS = 100

CODE_MAX_LEN = 24


def normalize(code: str) -> str:
    """Codes are case-insensitive and whitespace-tolerant."""
    return (code or '').strip().upper()[:CODE_MAX_LEN]


def redeem(st: PetState, code: str, now: int) -> Tuple[PetState, str, bool]:
    """Apply a promo code to the state (pure; the single-use, timed-limit
    and max_uses db checks are done by the caller before this runs).
    Returns (state, message, changed)."""
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

    acc = data.get('acc', '')
    if acc:
        title = _acc_title(acc)
        if acc in st.acc:
            st.coins += DUPE_FALLBACK_COINS
            grants.append('%s уже был — компенсация +%d🪙'
                          % (title, DUPE_FALLBACK_COINS))
        else:
            st.acc.append(acc)
            grants.append('наряд %s' % title)

    hours = float(data.get('boost_hours', 0.0))
    if hours > 0:
        st.boost_until = max(st.boost_until, now) + int(hours * 3600)
        grants.append('⚗️ ×2 XP на %d ч' % int(hours))

    return st, '🎁 Промокод активирован: %s!' % ', '.join(grants), True


def _acc_title(acc_id: str) -> str:
    item = SHOP.get(acc_id)
    if item:
        return item['title']
    return CHEST_ACC_TITLES.get(acc_id, acc_id)
