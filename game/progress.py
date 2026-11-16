"""Progression 2.0: XP levels, adult classes, daily quests, achievements,
Hall of Fame prestige. Pure functions, no I/O — same contract as engine.py.

The XP axis is independent of evolution stages: care actions, minigames and
quests grant XP, level-ups are computed here. At MAX_LEVEL a grown pet can
retire to the Hall of Fame (prestige): the player starts a new egg in the
next generation with a permanent XP bonus, keeping all collection assets
(coins, gems, pets, inventory, room, fragments, achievements).
"""
import random
import time
from typing import List, Optional, Tuple

from game.balance import (
    BOOST_XP_MULT,
    CLASS_MIN_STAT,
    CLASS_XP_MULT_MAGE,
    CLASSES,
    GEN_XP_BONUS,
    LEVEL_XP_BASE,
    LEVEL_XP_STEP,
    MAX_LEVEL,
    QUEST_ALL_BONUS,
    QUEST_CLAIM_XP,
    QUEST_POOL,
    QUESTS_PER_DAY,
    ROOM,
)
from game.pets import SPECIES
from game.state import PetState


def day_of(now: int) -> str:
    return time.strftime('%Y-%m-%d', time.gmtime(now))


def xp_need(level: int) -> int:
    """XP required to advance FROM `level` to level+1."""
    return LEVEL_XP_BASE + LEVEL_XP_STEP * (level - 1)


def add_xp(st: PetState, amount: int, now: int, bonus_source: bool = False) -> str:
    """Grant XP with all multipliers and handle level-ups. Returns a message
    line ('' when nothing leveled up). bonus_source=True applies the mage
    class bonus (minigames and quests only, as advertised in CLASSES)."""
    if st.stage == 0 or amount <= 0:  # яйцо в уровнях не растёт
        return ''
    mult = 1.0 + GEN_XP_BONUS * (st.gen - 1)
    if bonus_source and st.cls == 'mage':
        mult *= CLASS_XP_MULT_MAGE
    if st.boost_until > now:
        mult *= BOOST_XP_MULT
    st.xp += int(round(amount * mult))
    lines: List[str] = []
    while st.lv < MAX_LEVEL and st.xp >= xp_need(st.lv):
        st.xp -= xp_need(st.lv)
        st.lv += 1
        lines.append('🎉 Уровень %d!' % st.lv)
    if st.lv >= MAX_LEVEL:
        st.xp = min(st.xp, xp_need(MAX_LEVEL) - 1)
    return '\n'.join(lines)


def dominant_class(st: PetState) -> str:
    """Adult class by the dominant hidden stat ('' while none reaches the bar)."""
    best = max(st.p, st.iq, st.ch)
    if best < CLASS_MIN_STAT:
        return ''
    if best == st.p:
        return 'warrior'
    if best == st.iq:
        return 'mage'
    return 'noble'


def ensure_quests(st: PetState, now: int) -> None:
    """Fill today's quest list. Deterministic per (born, day): the same user
    gets the same quests all day, without storing RNG state."""
    day = day_of(now)
    if st.q_day == day and st.quests:
        return
    pool = {q['id']: q for q in QUEST_POOL}
    seed = '%s:%s' % (st.born, day)
    ids = random.Random(seed).sample(sorted(pool), min(QUESTS_PER_DAY, len(pool)))
    st.quests = [[qid, pool[qid]['need'], 0] for qid in ids]
    st.q_day = day
    st.q_claimed = 0


def _quest_by_id(qid: str) -> Optional[dict]:
    for q in QUEST_POOL:
        if q['id'] == qid:
            return q
    return None


def on_action(st: PetState, action: str) -> None:
    """Bump matching daily quests after a successful action (the engine
    wrapper calls this only when `changed`)."""
    for q in st.quests:
        meta = _quest_by_id(q[0])
        if meta is None or meta['act'] != action or q[2] >= q[1]:
            continue
        if action == 'sleep' and not st.sleeping:
            continue  # засчитываем укладывание, а не пробуждение
        q[2] += 1


def claim_quests(st: PetState, now: int) -> Tuple[PetState, str, bool]:
    """Hand in all three daily quests: coins + XP. One shot per day."""
    ensure_quests(st, now)
    if st.q_claimed:
        return st, 'Награда за сегодня уже получена 🙂', False
    if not all(q[2] >= q[1] for q in st.quests):
        return st, 'Не все квесты выполнены — их список в Mini App', False
    reward = sum((_quest_by_id(q[0]) or {}).get('reward', 0)
                 for q in st.quests) + QUEST_ALL_BONUS
    st.coins += reward
    st.q_claimed = 1
    xp_line = add_xp(st, QUEST_CLAIM_XP, now, bonus_source=True)
    msg = '✅ Квесты сданы: +%d🪙' % reward
    if xp_line:
        msg += '\n' + xp_line
    return st, msg, True


# achievement id -> check; `get` returns the current progress value
ACHIEVEMENTS: List[dict] = [
    {'id': 'lvl10', 'title': 'Подрос', 'desc': 'Достичь 10 уровня', 'gems': 20,
     'target': 10, 'get': lambda st: st.lv},
    {'id': 'lvl30', 'title': 'Легенда', 'desc': 'Достичь 30 уровня', 'gems': 60,
     'target': MAX_LEVEL, 'get': lambda st: st.lv, 'player_title': 'Легенда'},
    {'id': 'coins10k', 'title': 'Богач', 'desc': 'Накопить 10 000 монет', 'gems': 30,
     'target': 10000, 'get': lambda st: int(st.coins)},
    {'id': 'pets5', 'title': 'Зоолюбитель', 'desc': 'Собрать 5 видов питомцев',
     'gems': 25, 'target': 5, 'get': lambda st: len(st.pets)},
    {'id': 'pets8', 'title': 'Коллекционер', 'desc': 'Собрать 8 видов питомцев',
     'gems': 60, 'target': 8, 'get': lambda st: len(st.pets),
     'player_title': 'Коллекционер'},
    {'id': 'games50', 'title': 'Геймер', 'desc': 'Сыграть 50 мини-игр', 'gems': 25,
     'target': 50, 'get': lambda st: st.games_total},
    {'id': 'chests25', 'title': 'Кладоискатель', 'desc': 'Открыть 25 сундуков',
     'gems': 25, 'target': 25, 'get': lambda st: st.chests_total},
    {'id': 'streak7', 'title': 'Неделька', 'desc': 'Серия из 7 дней', 'gems': 15,
     'target': 7, 'get': lambda st: st.streak},
    {'id': 'streak30', 'title': 'Верный друг', 'desc': 'Серия из 30 дней', 'gems': 50,
     'target': 30, 'get': lambda st: st.streak, 'player_title': 'Верный друг'},
    {'id': 'hall1', 'title': 'Наставник', 'desc': 'Отправить питомца в Зал Славы',
     'gems': 40, 'target': 1, 'get': lambda st: len(st.hall)},
    {'id': 'care100', 'title': 'Забота', 'desc': '100 очков заботы', 'gems': 20,
     'target': 100, 'get': lambda st: st.care_score},
]


def check_achievements(st: PetState) -> List[str]:
    """Grant every newly reached achievement once; returns message lines."""
    lines: List[str] = []
    for a in ACHIEVEMENTS:
        if a['id'] in st.achv or a['get'](st) < a['target']:
            continue
        st.achv.append(a['id'])
        st.gems += a['gems']
        lines.append('🏅 Ачивка «%s»: +%d💎' % (a['title'], a['gems']))
    return lines


def prestige(st: PetState, now: int) -> Tuple[PetState, str, bool]:
    """Hall of Fame: an adult max-level pet retires, a new egg of the next
    generation starts with a permanent XP bonus. Collection assets are kept."""
    if st.stage < 3:
        return st, 'В Зал Славы попадает только взрослый питомец', False
    if st.lv < MAX_LEVEL:
        return st, 'Сначала дорастите до уровня %d (сейчас %d)' % (MAX_LEVEL, st.lv), False
    st.hall.append([st.species, st.cls, st.gen])
    del st.hall[:-10]
    st.gen += 1
    st.stage = 0
    st.cls = ''
    st.p = st.iq = st.ch = 0.0
    st.lv = 1
    st.xp = 0
    st.satiety = st.mood = st.energy = 60.0
    st.hygiene = 80.0
    st.sleeping = False
    st.sick = False
    st.sick_since = 0
    st.care_score = 0
    st.care_miss = 0
    st.born = now
    st.last_tick = now
    st.last_act = 0
    st.last_act_code = ''
    xp_pct = int(round(GEN_XP_BONUS * 100 * (st.gen - 1)))
    return st, ('🏛 %s отправлен в Зал Славы! Поколение %d: новое яйцо, '
                '+%d%% XP навсегда' % (SPECIES[st.species]['title'], st.gen, xp_pct)), True


def progress_for(st: PetState) -> dict:
    """Achievement progress for UI bars: id -> [current, target]."""
    return {a['id']: [min(int(a['get'](st)), a['target']), a['target']]
            for a in ACHIEVEMENTS}


def achv_meta() -> list:
    """Achievement book for the Mini App (delivered via /api/state meta)."""
    return [{'id': a['id'], 'title': a['title'], 'desc': a['desc'],
             'gems': a['gems'],
             'title_reward': a.get('player_title', '')}
            for a in ACHIEVEMENTS]


def room_meta() -> list:
    """Room upgrades for the shop UI: prices per level."""
    return [{'id': rid, 'title': r['title'], 'desc': r['desc'],
             'prices': list(r['prices'])}
            for rid, r in ROOM.items()]
