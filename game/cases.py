"""Loot chests (сундуки/кейсы): the dedicated single place to define them.

Every roll happens on the server inside engine.apply('open_case'); the
Mini App only displays the drop tables delivered in /api/state meta, so
there is nothing to spoof client-side. Weighted drop tables, coins use a
uniform range, pets grant the species itself (auto-equipped), a repeated
pet or accessory converts into coin compensation (dupe_coins).

To add a chest or a drop, add one dict entry — nothing else changes.
"""
import random
from typing import Dict

from game.balance import FRAG_DUPE_COINS, FRAG_NEED, SHOP
from game.pets import SPECIES
from game.state import PetState

CASES: Dict[str, dict] = {
    'simple': {
        'title': '🪵 Деревянный сундук',
        'price': 50,
        'desc': 'Монеты, еда и первые питомцы',
        'drops': [
            {'kind': 'coins', 'min': 10, 'max': 45, 'weight': 30, 'label': '🪙 10–45 монет'},
            {'kind': 'item', 'id': 'apple', 'qty': 2, 'weight': 14, 'label': '🍎 2 яблока'},
            {'kind': 'item', 'id': 'fish', 'qty': 1, 'weight': 12, 'label': '🐟 Рыбка'},
            {'kind': 'item', 'id': 'cake', 'qty': 1, 'weight': 8, 'label': '🍰 Торт'},
            {'kind': 'item', 'id': 'med', 'qty': 1, 'weight': 6, 'label': '💊 Лекарство'},
            {'kind': 'acc', 'id': 'bow', 'weight': 4, 'label': '🎀 Бантик'},
            {'kind': 'pet', 'id': 'dog', 'weight': 8, 'dupe_coins': 60, 'label': '🐶 Щенок'},
            {'kind': 'pet', 'id': 'bunny', 'weight': 8, 'dupe_coins': 60, 'label': '🐰 Кролик'},
            {'kind': 'pet', 'id': 'hamster', 'weight': 6, 'dupe_coins': 80, 'label': '🐹 Хомяк'},
            {'kind': 'pet', 'id': 'fox', 'weight': 2, 'dupe_coins': 150, 'label': '🦊 Лисёнок'},
            {'kind': 'pet', 'id': 'duck', 'weight': 2, 'dupe_coins': 150, 'label': '🦆 Утёнок'},
            {'kind': 'pet', 'id': 'panda', 'weight': 1, 'dupe_coins': 250, 'label': '🐼 Панда'},
        ],
    },
    'golden': {
        'title': '🧰 Золотой сундук',
        'price': 150,
        'desc': 'Крупные призы, наряды и редкие питомцы',
        'drops': [
            {'kind': 'coins', 'min': 60, 'max': 200, 'weight': 26, 'label': '🪙 60–200 монет'},
            {'kind': 'item', 'id': 'cake', 'qty': 2, 'weight': 14, 'label': '🍰 2 торта'},
            {'kind': 'item', 'id': 'med', 'qty': 2, 'weight': 10, 'label': '💊 2 лекарства'},
            {'kind': 'acc', 'id': 'scarf', 'weight': 8, 'label': '🧣 Шарф'},
            {'kind': 'acc', 'id': 'hat', 'weight': 6, 'label': '🎩 Шляпа'},
            {'kind': 'acc', 'id': 'crown', 'weight': 2, 'dupe_coins': 100, 'label': '👑 Корона'},
            {'kind': 'pet', 'id': 'hamster', 'weight': 8, 'dupe_coins': 80, 'label': '🐹 Хомяк'},
            {'kind': 'pet', 'id': 'fox', 'weight': 10, 'dupe_coins': 150, 'label': '🦊 Лисёнок'},
            {'kind': 'pet', 'id': 'duck', 'weight': 10, 'dupe_coins': 150, 'label': '🦆 Утёнок'},
            {'kind': 'pet', 'id': 'panda', 'weight': 6, 'dupe_coins': 250, 'label': '🐼 Панда'},
        ],
    },
    'mythic': {
        'title': '💎 Мифический сундук',
        'price': 45,
        'currency': 'gems',
        'desc': 'Осколки редких питомцев, кристаллы и корона',
        'drops': [
            {'kind': 'frag', 'id': 'fox', 'weight': 22,
             'label': '🧩 Осколок: 🦊 Лисёнок (1/5)'},
            {'kind': 'frag', 'id': 'panda', 'weight': 18,
             'label': '🧩 Осколок: 🐼 Панда (1/8)'},
            {'kind': 'frag', 'id': 'snow_leopard', 'weight': 10,
             'label': '🧩 Осколок: 🐆 Снежный барс (1/12)'},
            {'kind': 'coins', 'min': 80, 'max': 220, 'weight': 16, 'label': '🪙 80–220 монет'},
            {'kind': 'gems', 'min': 5, 'max': 12, 'weight': 14, 'label': '💎 5–12 кристаллов'},
            {'kind': 'acc', 'id': 'crown', 'weight': 6, 'dupe_coins': 300, 'label': '👑 Корона'},
            {'kind': 'item', 'id': 'cake', 'qty': 3, 'weight': 8, 'label': '🍰 3 торта'},
        ],
    },
}


# Chest-exclusive accessories (not sold in the shop); engine._apply_wear
# falls back here for titles.
CHEST_ACC_TITLES = {'crown': '👑 Корона', 'ring': '💍 Кольцо дружбы'}


def roll(case: dict) -> dict:
    """Server-side weighted roll. Returns a copy of the drop dict; for a
    'coins'/'gems' drop adds the rolled 'amount'."""
    drops = case['drops']
    drop = random.choices(drops, weights=[d['weight'] for d in drops], k=1)[0]
    result = dict(drop)
    if result['kind'] in ('coins', 'gems'):
        result['amount'] = random.randint(result['min'], result['max'])
    return result


def _coins_word(n: int) -> str:
    """Russian plural: 1 монета / 2–4 монеты / 5–20 монет."""
    n %= 100
    if 11 <= n <= 14:
        return 'монет'
    n %= 10
    if n == 1:
        return 'монета'
    return 'монеты' if 2 <= n <= 4 else 'монет'


def apply_drop(st: PetState, drop: dict) -> str:
    """Mutate the state with a rolled drop; returns the reward line for the user."""
    kind = drop['kind']

    if kind == 'coins':
        st.coins += drop['amount']
        return '🪙 +%d %s!' % (drop['amount'], _coins_word(drop['amount']))

    if kind == 'gems':
        st.gems += drop['amount']
        return '💎 +%d кристаллов!' % drop['amount']

    if kind == 'item':
        st.inv[drop['id']] = st.inv.get(drop['id'], 0) + int(drop.get('qty', 1))
        qty = int(drop.get('qty', 1))
        return '%s ×%d в инвентаре' % (SHOP[drop['id']]['title'], qty)

    if kind == 'acc':
        item = SHOP.get(drop['id'])
        title = item['title'] if item else CHEST_ACC_TITLES.get(drop['id'], drop['id'])
        if drop['id'] in st.acc:
            dupe = int(drop.get('dupe_coins', (item['price'] if item else 60) // 2))
            st.coins += dupe
            return '%s уже был — компенсация +%d🪙' % (title, dupe)
        st.acc.append(drop['id'])
        return 'Наряд: %s' % title

    if kind == 'pet':
        title = SPECIES[drop['id']]['title']
        if drop['id'] in st.pets:
            dupe = int(drop.get('dupe_coins', 100))
            st.coins += dupe
            return '%s уже был — компенсация +%d🪙' % (title, dupe)
        st.pets.append(drop['id'])
        st.species = drop['id']  # the new pet is auto-equipped
        return 'Новый питомец: %s!' % title

    if kind == 'frag':
        need = FRAG_NEED[drop['id']]
        st.frags[drop['id']] = st.frags.get(drop['id'], 0) + 1
        if st.frags[drop['id']] < need:
            return '🧩 Осколок: %s (%d/%d)' % (SPECIES[drop['id']]['title'],
                                              st.frags[drop['id']], need)
        st.frags[drop['id']] = 0
        title = SPECIES[drop['id']]['title']
        if drop['id'] in st.pets:
            st.coins += FRAG_DUPE_COINS
            return '%s уже был — компенсация +%d🪙' % (title, FRAG_DUPE_COINS)
        st.pets.append(drop['id'])
        st.species = drop['id']
        return '🥚 Новый питомец из осколков: %s!' % title

    return ''


def ui_meta() -> list:
    """Drop tables for the Mini App display (delivered via /api/state meta)."""
    return [{'id': cid, 'title': c['title'], 'price': c['price'],
             'currency': c.get('currency', 'coins'), 'desc': c['desc'],
             'drops': [d['label'] for d in c['drops']]}
            for cid, c in CASES.items()]
