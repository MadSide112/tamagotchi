"""Экипировка: реестр в balance.GEAR; свод статов, покупка/надевание/апгрейд."""
from game.balance import (
    ELEMENTS,
    GEAR,
    GEAR_DUPE_COINS,
    GEAR_MAX_LEVEL,
    GEAR_SLOTS,
)


# ------------------------- свод статов -------------------------

def gear_bonus(gi, gl, gw) -> dict:
    """Суммарные статы надетых предметов. Множитель уровня предмета:
    стат ×(1 + 0.5×(ур−1)); элемент атаки берётся только у оружия.
    gi не нужен для свода, gw валидируется по GEAR_SLOTS/GEAR."""
    totals = {'atk': 0, 'mag': 0, 'def': 0, 'hp': 0, 'element': ''}
    for slot, gid in gw.items():
        if slot not in GEAR_SLOTS or gid not in GEAR:
            continue
        g = GEAR[gid]
        mult = 1 + 0.5 * (gl.get(gid, 1) - 1)
        for key in ('atk', 'mag', 'def', 'hp'):
            totals[key] += round(g.get(key, 0) * mult)
        if slot == 'weapon':
            totals['element'] = g.get('element', '')
    return totals


# ------------------------- выдача -------------------------

def grant_gear(st, gid) -> str:
    """Кладёт предмет в инвентарь; дубликат превращается в монеты.
    Возвращает строку для юзера ('' — предмет неизвестен)."""
    g = GEAR.get(gid)
    if g is None:
        return ''
    if gid in st.gi:
        st.coins += GEAR_DUPE_COINS
        return '%s — дубликат, +%d🪙' % (g['title'], GEAR_DUPE_COINS)
    st.gi.append(gid)
    st.gl.setdefault(gid, 1)
    return g['title']


# ------------------------- действия движка -------------------------

def gear_buy(st, arg, now):
    gid = str(arg or '')[:16]
    g = GEAR.get(gid)
    if g is None:
        return st, 'Такого предмета нет 🤷', False
    if g.get('drop_only'):
        return st, 'Этот предмет только из походов 🗺', False
    if gid in st.gi:
        return st, 'Этот предмет уже есть', False
    price = g['price']
    if st.coins < price:
        return st, 'Не хватает монет 🪙 (нужно %d)' % price, False
    st.coins -= price
    grant_gear(st, gid)
    return st, 'Куплено: %s (−%d🪙)' % (g['title'], price), True


def gear_equip(st, arg, now):
    gid = str(arg or '')[:16]
    g = GEAR.get(gid)
    if g is None or gid not in st.gi:
        return st, 'Не найдено в инвентаре 🎒', False
    st.gw[g['slot']] = gid
    msg = 'Надето: %s' % g['title']
    if g.get('element'):
        elem = ELEMENTS.get(g['element'], {})
        msg += ', элемент атаки: %s%s' % (elem.get('emoji', ''),
                                          elem.get('title', ''))
    return st, msg, True


def gear_up(st, arg, now):
    gid = str(arg or '')[:16]
    g = GEAR.get(gid)
    if g is None or gid not in st.gi:
        return st, 'Не найдено в инвентаре 🎒', False
    lvl = st.gl.get(gid, 1)
    if lvl >= GEAR_MAX_LEVEL:
        return st, 'Максимальный уровень 🔝', False
    cost = g['up_cost'][lvl - 1]
    if st.coins < cost:
        return st, 'Не хватает монет 🪙 (нужно %d)' % cost, False
    st.coins -= cost
    st.gl[gid] = lvl + 1
    return st, 'Апгрейд: %s → ур.%d (−%d🪙)' % (g['title'], lvl + 1, cost), True


# ------------------------- мета для Mini App -------------------------

def gear_meta() -> list:
    """Реестр экипировки для витрины (уходит через /api/state meta)."""
    return [{'id': gid, 'slot': g['slot'], 'title': g['title'],
             'price': g.get('price', 0), 'drop_only': bool(g.get('drop_only')),
             'atk': g.get('atk', 0), 'def': g.get('def', 0),
             'hp': g.get('hp', 0), 'mag': g.get('mag', 0),
             'element': g.get('element', ''),
             'up_cost': list(g.get('up_cost', []))}
            for gid, g in GEAR.items()]
