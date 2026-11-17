"""Экспедиции (idle): питомец уходит по таблице EXPEDITIONS и возвращается
с наградой; масштаб награды зависит от заботы (сытость+настроение)."""
import random

from game.balance import (
    EXPEDITION_CARE_MULT_MAX,
    EXPEDITION_CARE_MULT_MIN,
    EXPEDITION_MOOD_BONUS,
    EXPEDITIONS,
)
from game.cases import apply_drop
from game.gear import grant_gear
from game.progress import add_xp


def expedition_start(st, arg, now):
    if st.stage < 1:
        return st, 'Сначала вылупись из яйца 🥚', False
    if st.sleeping:
        return st, 'Ты спишь 😴', False
    if st.sick:
        return st, 'Ты болеешь — сначала полечись 💊', False
    if st.bt:
        return st, 'Бой уже идёт! ⚔️', False
    if st.ex:
        return st, 'Экспедиция уже идёт 🎒', False
    ex_id = str(arg or '')[:16]
    exp = EXPEDITIONS.get(ex_id)
    if exp is None:
        return st, 'Такой экспедиции нет 🤷', False
    st.ex = {'i': ex_id, 's': now}
    return st, '🚶 Отправился: %s' % exp['title'], True


def _roll_drop(rng, drops) -> dict:
    """Взвешенный выбор из таблицы дропа (детерминированный по seed)."""
    total = sum(d['w'] for d in drops)
    r = rng.uniform(0, total)
    acc = 0.0
    for d in drops:
        acc += d['w']
        if r < acc:
            return d
    return drops[-1]


def expedition_collect(st, arg, now):
    if not st.ex:
        return st, 'Экспедиция не начата 🎒', False
    exp = EXPEDITIONS.get(st.ex.get('i', ''))
    if exp is None:
        st.ex = None
        return st, 'Экспедиция отменена', True
    elapsed = now - st.ex['s']
    if elapsed < exp['sec']:
        return st, ('⏳ Экспедиция вернётся через %d мин'
                    % max(1, (exp['sec'] - elapsed + 59) // 60)), False

    # забота масштабирует базовую награду: 0.5 при нуле, 1.5 при сытости и
    # настроении 100
    care = max(EXPEDITION_CARE_MULT_MIN,
               min(EXPEDITION_CARE_MULT_MAX,
                   0.5 + st.satiety / 200 + st.mood / 200))
    coins = round(exp['coins'] * care)
    st.coins += coins
    xp = round(exp['xp'] * care)
    add_xp(st, xp, now, bonus_source=False)

    # дроп детерминирован (born:старт): тот же поход — тот же подарок
    rng = random.Random('%s:%s' % (st.born, st.ex['s']))
    drop = _roll_drop(rng, exp['drops'])
    kind = drop['kind']
    if kind == 'coins':
        n = rng.randint(*drop['n'])
        st.coins += n
        drop_msg = '🪙 +%d' % n
    elif kind == 'gem':
        n = rng.randint(*drop['n'])
        st.gems += n
        drop_msg = '💎 +%d' % n
    elif kind == 'frag':
        drop_msg = apply_drop(st, {'kind': 'frag', 'id': drop['id']})
    elif kind == 'gear':
        drop_msg = grant_gear(st, drop['id'])
    else:  # 'none'
        drop_msg = drop['label']

    st.ec += 1
    st.mood = max(0.0, min(100.0, st.mood + EXPEDITION_MOOD_BONUS))
    st.ex = None
    msg = '🎒 %s: возвращение!\n🪙 +%d  💬 +%d XP\n🎁 %s' % (
        exp['title'], coins, xp, drop_msg)
    return st, msg, True


def expeditions_meta() -> list:
    """Список экспедиций для витрины (уходит через /api/state meta)."""
    return [{'id': ex_id, 'title': e['title'], 'sec': e['sec'],
             'coins': e['coins'], 'xp': e['xp'], 'desc': e['desc'],
             'drops': [d['label'] for d in e['drops']]}
            for ex_id, e in EXPEDITIONS.items()]
