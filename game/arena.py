"""PvP-арена: асинхронные бои по снапшотам соперников; рейтинг меняется
только у бойца."""
import random
import time

from game.balance import (
    ARENA_CANDIDATES,
    ARENA_DAILY_CAP,
    ARENA_ENERGY_COST,
    ARENA_K,
    ARENA_LEVEL_WINDOW,
    ARENA_MIN_LEVEL,
    ARENA_RATING_FLOOR,
    ARENA_RATING_START,
    ARENA_WIN_COINS,
    ARENA_WIN_XP,
    BT_LOSE_MOOD,
    BT_WIN_MOOD,
)
from game.battle import fighter, my_fighter, resolve_auto
from game.gear import gear_bonus
from game.progress import add_xp


# ------------------------- подбор соперников -------------------------

def pick_opponents(rows, my_uid, my_lv, limit=ARENA_CANDIDATES) -> list:
    """Кандидаты из сырых строк БД ([{'user_id', 'state'}]): не сам,
    вылупившийся, уровень в окне ARENA_LEVEL_WINDOW. До limit случайных."""
    lo = my_lv + ARENA_LEVEL_WINDOW[0]
    hi = my_lv + ARENA_LEVEL_WINDOW[1]
    matches = []
    for row in rows:
        uid = row.get('user_id')
        if uid == my_uid:
            continue
        cand = row.get('state')
        if not isinstance(cand, dict) or cand.get('s', 0) < 1:
            continue
        try:
            lv = int(cand.get('lv', 1))
        except (TypeError, ValueError):
            lv = 1
        if lv < lo or lv > hi:
            continue
        matches.append({'user_id': uid,
                        'name': str(cand.get('n', 'Пуся')),
                        'species': str(cand.get('sp', 'cat')),
                        'lv': lv,
                        'rating': cand.get('ar', ARENA_RATING_START)})
    return random.sample(matches, min(limit, len(matches)))


def snapshot_of(pet_state) -> dict:
    """Снапшот питомца для арены: всё, что нужно сопернику для боя."""
    return {
        'name': getattr(pet_state, 'name', 'Соперник'),
        'species': getattr(pet_state, 'species', 'cat'),
        'lv': getattr(pet_state, 'lv', 1),
        'cls': getattr(pet_state, 'cls', ''),
        'p': getattr(pet_state, 'p', 0.0),
        'iq': getattr(pet_state, 'iq', 0.0),
        'ch': getattr(pet_state, 'ch', 0.0),
        'mood': getattr(pet_state, 'mood', 60.0),
        'satiety': getattr(pet_state, 'satiety', 60.0),
        'gi': getattr(pet_state, 'gi', []),
        'gl': getattr(pet_state, 'gl', {}),
        'gw': getattr(pet_state, 'gw', {}),
        'rating': getattr(pet_state, 'ar', ARENA_RATING_START),
    }


# ------------------------- бой -------------------------

def _clamped_stat(snap, key) -> float:
    try:
        v = float(snap.get(key, 0.0))
    except (TypeError, ValueError):
        v = 0.0
    return max(0.0, min(100.0, v))


def fight(st, opp_uid, snapshot, now):
    if st.lv < ARENA_MIN_LEVEL:
        return st, 'Арена откроется на %d уровне 🏟' % ARENA_MIN_LEVEL, False
    if st.sleeping:
        return st, 'Ты спишь 😴', False
    if st.sick:
        return st, 'Ты болеешь — сначала полечись 💊', False
    if st.bt:
        return st, 'Бой уже идёт! ⚔️', False
    if st.ex:
        return st, 'Питомец в экспедиции 🎒', False
    if st.energy < ARENA_ENERGY_COST:
        return st, 'Мало энергии ⚡ (нужно %d)' % int(ARENA_ENERGY_COST), False
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    if st.ad != day:
        st.ad = day
        st.an = 0
    if st.an >= ARENA_DAILY_CAP:
        return st, ('Дневной лимит арены исчерпан (%d боёв) 🏟'
                    % ARENA_DAILY_CAP), False

    # санитарная обработка снапшота: данные соперника могут быть битыми
    snap = snapshot if isinstance(snapshot, dict) else {}
    name = str(snap.get('name') or 'Соперник')[:32]
    species = str(snap.get('species') or 'cat')[:16]
    try:
        lv = int(snap.get('lv', 1))
    except (TypeError, ValueError):
        lv = 1
    lv = max(1, min(99, lv))
    cls = str(snap.get('cls') or '')[:16]
    gi_raw = snap.get('gi') if isinstance(snap.get('gi'), list) else []
    gi = [str(g)[:16] for g in gi_raw][:16]
    gl = snap.get('gl') if isinstance(snap.get('gl'), dict) else {}
    gw = snap.get('gw') if isinstance(snap.get('gw'), dict) else {}

    st.energy = max(0.0, st.energy - ARENA_ENERGY_COST)
    me = my_fighter(st)
    me['name'] = st.name
    opp = fighter(species=species, lv=lv, cls=cls,
                  p=_clamped_stat(snap, 'p'), iq=_clamped_stat(snap, 'iq'),
                  ch=_clamped_stat(snap, 'ch'), mood=_clamped_stat(snap, 'mood'),
                  satiety=_clamped_stat(snap, 'satiety'),
                  gear=gear_bonus(gi, gl, gw))
    opp['name'] = name

    seed = '%s:%s:%s' % (st.born, opp_uid, now)
    winner, _log = resolve_auto(me, opp, seed)

    try:
        opp_rating = int(snap.get('rating', ARENA_RATING_START))
    except (TypeError, ValueError):
        opp_rating = ARENA_RATING_START
    opp_rating = max(ARENA_RATING_FLOOR, min(4000, opp_rating))

    old = st.ar
    expected = 1.0 / (1.0 + 10 ** ((opp_rating - st.ar) / 400.0))
    if winner == 'a':
        delta = round(ARENA_K * (1 - expected))
        st.ar = max(ARENA_RATING_FLOOR, st.ar + delta)
        st.aw += 1
        st.mood = max(0.0, min(100.0, st.mood + BT_WIN_MOOD))
        st.coins += ARENA_WIN_COINS
        add_xp(st, ARENA_WIN_XP, now, bonus_source=False)
        msg = '🏆 Победа над %s!\n🪙 +%d 💬 +%d XP\n🏟 Рейтинг %d → %d (+%d)' % (
            name, ARENA_WIN_COINS, ARENA_WIN_XP, old, st.ar, delta)
    else:
        delta = -round(ARENA_K * expected)
        st.ar = max(ARENA_RATING_FLOOR, st.ar + delta)
        st.al += 1
        st.mood = max(0.0, min(100.0, st.mood + BT_LOSE_MOOD))
        msg = '😵 Поражение от %s…\n🏟 Рейтинг %d → %d (%d)' % (
            name, old, st.ar, delta)
    st.an += 1
    return st, msg, True
