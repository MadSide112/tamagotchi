"""Боевое ядро: чистая логика без I/O.

Контракт модулей game/: (st, arg, now) -> (st, message, changed).
Сессия боя живёт в st.bt (строгая валидация в state.from_dict), каждый ход
пересчитывается детерминированно из seed 'sd:et:tn' — состояние RNG не
хранится, повтор при том же номере хода даёт тот же результат.
NO DEATH: поражение, побег или истечение сессии = отступление, смерти нет.
"""
import random
import time

from game.balance import (
    BT_CRIT_BASE,
    BT_CRIT_DAMAGE,
    BT_CRIT_MOOD_MULT,
    BT_DEF_MULT,
    BT_DEF_REGEN_MULT,
    BT_DAILY_COIN_CAP,
    BT_ENERGY_COST,
    BT_FLEE_MOOD,
    BT_LOSE_MOOD,
    BT_MAX_TURNS,
    BT_POTION_HEAL,
    BT_POTIONS_PER_BATTLE,
    BT_SESSION_SECONDS,
    BT_SKILLS,
    BT_WIN_MOOD,
    DUNGEON_BOSS_HEAVY_CHANCE,
    DUNGEON_BOSS_MULT,
    DUNGEON_COINS,
    DUNGEON_ENEMIES,
    DUNGEON_ENEMY_ATK,
    DUNGEON_ENEMY_DEF,
    DUNGEON_ENEMY_HP,
    DUNGEON_ENEMY_HEAVY,
    DUNGEON_GEAR_DROP_CHANCE,
    DUNGEON_GEM_CHANCE,
    DUNGEON_XP,
    ELEMENTS,
    ELEMENT_STRONG_MULT,
    ELEMENT_WEAK_MULT,
    GEAR,
    SPECIES_ELEMENT,
)
from game.gear import gear_bonus, grant_gear
from game.progress import add_xp


# ------------------------- сборка бойцов -------------------------

def fighter(st=None, *, species, lv, cls='', p=0.0, iq=0.0, ch=0.0,
            mood=60.0, satiety=60.0, gear=None) -> dict:
    """Собирает бойца из статов. gear — сумма статов экипировки
    (game.gear.gear_bonus); 'element' из gear переопределяет видовой."""
    gear = gear or {}
    max_hp = round(40 + 8 * lv + 0.6 * satiety + gear.get('hp', 0))
    return {
        'hp': max_hp,
        'max': max_hp,
        'atk': round(5 + 0.5 * p + gear.get('atk', 0)),
        'mag': round(5 + 0.5 * iq + gear.get('mag', 0)),
        'dfn': round(3 + 0.3 * ch + gear.get('def', 0)),
        'crit': min(0.35, BT_CRIT_BASE + BT_CRIT_MOOD_MULT * mood),
        'element': gear.get('element') or SPECIES_ELEMENT.get(species, 'fire'),
        'cls': cls,
        'lv': lv,
        'regen': round(1 + 0.03 * satiety, 1),
    }


def my_fighter(st) -> dict:
    """Боец из живого состояния питомца (со сводкой экипировки)."""
    return fighter(species=st.species, lv=st.lv, cls=st.cls, p=st.p, iq=st.iq,
                   ch=st.ch, mood=st.mood, satiety=st.satiety,
                   gear=gear_bonus(st.gi, st.gl, st.gw))


def enemy_for_floor(floor: int) -> dict:
    """Враг этажа: детерминированный цикл по реестру; каждый 5-й — босс."""
    floor = max(1, int(floor))
    eid = sorted(DUNGEON_ENEMIES)[(floor - 1) % len(DUNGEON_ENEMIES)]
    base = DUNGEON_ENEMIES[eid]
    hp = DUNGEON_ENEMY_HP[0] + DUNGEON_ENEMY_HP[1] * floor
    atk = DUNGEON_ENEMY_ATK[0] + DUNGEON_ENEMY_ATK[1] * floor
    dfn = DUNGEON_ENEMY_DEF[0] + DUNGEON_ENEMY_DEF[1] * floor
    boss = floor % 5 == 0
    if boss:
        hp *= DUNGEON_BOSS_MULT
        atk *= DUNGEON_BOSS_MULT
        dfn *= DUNGEON_BOSS_MULT
    return {'id': eid, 'title': base['title'], 'element': base['element'],
            'hp': int(round(hp)), 'atk': int(round(atk)), 'dfn': int(round(dfn)),
            'boss': boss}


# ------------------------- формула урона -------------------------

def element_mult(atk_elem: str, def_elem: str) -> float:
    """Колесо 🔥 > 💨 > 🪨 > 💧 > 🔥: сильный ×1.5, слабый ×0.75."""
    if ELEMENTS.get(atk_elem, {}).get('strong') == def_elem:
        return ELEMENT_STRONG_MULT
    if ELEMENTS.get(def_elem, {}).get('strong') == atk_elem:
        return ELEMENT_WEAK_MULT
    return 1.0


def _roll_damage(rng, power: float, atk_elem: str, dfn: float,
                 def_elem: str, crit_chance: float = 0.0):
    """Урон = power × U(0.85..1.15) × элемент − 0.5×def, минимум 1.
    Крит (если chance > 0) — ×BT_CRIT_DAMAGE. Порядок бросков фиксирован."""
    dmg = power * rng.uniform(0.85, 1.15) * element_mult(atk_elem, def_elem) - 0.5 * dfn
    crit = crit_chance > 0 and rng.random() < crit_chance
    if crit:
        dmg *= BT_CRIT_DAMAGE
    return max(1, round(dmg)), crit


def _turn_rng(bt: dict) -> random.Random:
    """RNG хода: seed зависит от сессии и номера хода, состояние не хранится."""
    return random.Random('%s:%s:%s' % (bt['sd'], bt['et'], bt['tn']))


def _clamp_mood(st, delta: float) -> None:
    st.mood = max(0.0, min(100.0, st.mood + delta))


# ------------------------- PvE: подземелье -------------------------

def battle_start(st, arg, now):
    if st.stage < 1:
        return st, 'Сначала вылупись из яйца 🥚', False
    if st.sleeping:
        return st, 'Ты спишь 😴', False
    if st.sick:
        return st, 'Ты болеешь — сначала полечись 💊', False
    if st.bt:
        return st, 'Бой уже идёт! ⚔️', False
    if st.ex:
        return st, 'Питомец в экспедиции — сначала собери её 🎒', False
    if st.energy < BT_ENERGY_COST:
        return st, 'Мало энергии ⚡ (нужно %d)' % int(BT_ENERGY_COST), False
    raw = str(arg).strip().lower()
    if raw.startswith('f'):
        raw = raw[1:]
    floor = st.df + 1
    if raw.isdigit():
        floor = int(raw)
    floor = max(1, min(floor, st.df + 1))
    st.energy = max(0.0, st.energy - BT_ENERGY_COST)
    enemy = enemy_for_floor(floor)
    me = my_fighter(st)
    st.bt = {
        'm': 'dungeon', 'ef': floor, 'et': enemy['id'],
        'eh': enemy['hp'], 'ehm': enemy['hp'],
        'ph': me['max'], 'phm': me['max'],
        'tn': 0, 'pu': 0, 'sc': 0, 'es': 0,
        'sd': '%d' % now, 'ts': now,
    }
    elem = ELEMENTS[enemy['element']]
    if enemy['boss']:
        msg = '👑 Этаж %d — БОСС: %s %s. Твой ход!' % (
            floor, enemy['title'], elem['emoji'])
    else:
        msg = '⚔️ Этаж %d: %s %s. Твой ход!' % (
            floor, enemy['title'], elem['emoji'])
    return st, msg, True


def _forfeit(st, msg):
    st.bt = None
    _clamp_mood(st, BT_FLEE_MOOD)
    return st, msg, True


def _victory(st, bt, now, log, enemy):
    floor = bt['ef']
    # мягкий дневной кап монет из боёв (UTC) — по образцу minigames
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    if st.bd != day:
        st.bd = day
        st.bc = 0
    coins = DUNGEON_COINS[0] + DUNGEON_COINS[1] * floor
    granted = min(coins, max(0, BT_DAILY_COIN_CAP - st.bc))
    st.bc += granted
    st.coins += granted
    xp = DUNGEON_XP[0] + DUNGEON_XP[1] * floor
    add_xp(st, xp, now, bonus_source=False)
    st.df = max(st.df, floor)
    st.bw += 1
    _clamp_mood(st, BT_WIN_MOOD)
    log.append('🏆 Победа! +%d🪙 +%d XP' % (granted, xp))
    if granted < coins:
        log.append('(дневной кап монет — только XP)')
    if enemy['boss']:
        rng = _turn_rng(bt)
        if rng.random() < DUNGEON_GEAR_DROP_CHANCE:
            note = grant_gear(st, rng.choice(sorted(GEAR)))
            if note:
                log.append('🎁 %s' % note)
        if rng.random() < DUNGEON_GEM_CHANCE:
            gems = rng.randint(1, 2)
            st.gems += gems
            log.append('💎 +%d' % gems)
    st.bt = None
    return st, '\n'.join(log), True


def battle_move(st, arg, now):
    bt = st.bt
    if not bt:
        return st, 'Бой не начат ⚔️', False
    if now - bt.get('ts', 0) > BT_SESSION_SECONDS:
        return _forfeit(st, '⌛ Бой заброшен — отступление (−2 настроения)')
    if st.sleeping or st.sick:
        return _forfeit(st, '😴 Бой прерван — питомцу не до боя (−2 настроения)')
    act = str(arg).strip().lower()
    if act not in ('atk', 'skill', 'def', 'potion'):
        return st, 'Хм, не понял действие 🤔', False

    enemy = enemy_for_floor(bt['ef'])
    me = my_fighter(st)
    bt['phm'] = me['max']
    bt['ph'] = min(bt['ph'], bt['phm'])
    rng = _turn_rng(bt)
    log = []

    # --- ход игрока ---
    if act == 'potion':
        if bt['pu'] >= BT_POTIONS_PER_BATTLE:
            return st, 'Зелья на этот бой закончились 🧪', False
        if st.inv.get('med', 0) < 1:
            return st, 'Нет зелий в сумке 🧪 (купи в магазине)', False
        st.inv['med'] -= 1
        bt['pu'] += 1
        heal = int(round(me['max'] * BT_POTION_HEAL))
        bt['ph'] = min(bt['phm'], bt['ph'] + heal)
        log.append('🧪 Зелье: +%d HP' % heal)
    elif act == 'skill':
        skill = BT_SKILLS.get(st.cls)
        if skill is None:
            return st, 'У питомца пока нет боевого скилла 🎓', False
        if bt['sc'] > 0:
            return st, '✨ Скилл ещё не готов (%d ход.)' % bt['sc'], False
        bt['sc'] = skill['cd']
        log.append('✨ Скилл «%s» %s' % (skill['title'], skill['emoji']))
        power = skill['mult'] * (me['mag'] if skill.get('element') else me['atk'])
        elem = skill.get('element', me['element'])
        dfn = enemy['dfn'] * (1.0 - skill.get('def_ignore', 0.0))
        dmg, crit = _roll_damage(rng, power, elem, dfn, enemy['element'], me['crit'])
        bt['eh'] = max(0, bt['eh'] - dmg)
        log.append('%s Урон %d%s' % (skill['emoji'], dmg, ' КРИТ!' if crit else ''))
        if skill.get('stun'):
            bt['es'] = 1
            log.append('😵 %s пропустит ход' % enemy['title'])
    elif act == 'atk':
        dmg, crit = _roll_damage(rng, me['atk'], me['element'], enemy['dfn'],
                                 enemy['element'], me['crit'])
        bt['eh'] = max(0, bt['eh'] - dmg)
        log.append('💥 Ты бьёшь на %d%s' % (dmg, ' КРИТ!' if crit else ''))
    else:  # def
        log.append('🛡 Защита: урон снижен')

    # --- победа? ---
    if bt['eh'] <= 0:
        return _victory(st, bt, now, log, enemy)

    # --- ход врага ---
    if bt['es'] == 1:
        bt['es'] = 0
        log.append('😵 %s пропустил ход' % enemy['title'])
    else:
        e_atk = enemy['atk']
        if enemy['boss'] and rng.random() < DUNGEON_BOSS_HEAVY_CHANCE:
            e_atk *= DUNGEON_ENEMY_HEAVY
            log.append('👹 %s бьёт со всей силы!' % enemy['title'])
        e_dmg, _ = _roll_damage(rng, e_atk, enemy['element'], me['dfn'],
                                me['element'])
        if act == 'def':
            e_dmg = max(1, int(round(e_dmg * BT_DEF_MULT)))
        bt['ph'] = max(0, bt['ph'] - e_dmg)
        log.append('💢 %s отвечает на %d' % (enemy['title'], e_dmg))

    # --- поражение = отступление ---
    if bt['ph'] <= 0:
        st.bt = None
        _clamp_mood(st, BT_LOSE_MOOD)
        log.append('😵 Отступление… (−%d настроения)' % abs(int(BT_LOSE_MOOD)))
        return st, '\n'.join(log), True

    # --- конец хода: реген (в защите ×2) и счётчики ---
    regen = me['regen'] * (BT_DEF_REGEN_MULT if act == 'def' else 1.0)
    bt['ph'] = min(bt['phm'], bt['ph'] + int(round(regen)))
    bt['tn'] += 1
    bt['sc'] = max(0, bt['sc'] - 1)
    bt['ts'] = now
    return st, '\n'.join(log), True


def battle_flee(st, arg, now):
    if not st.bt:
        return st, 'Бой не начат ⚔️', False
    st.bt = None
    _clamp_mood(st, BT_FLEE_MOOD)
    return st, '🐾 Ты убегаешь с поля боя (−2 настроения)', True


# ------------------------- авто-бой (арена) -------------------------

def resolve_auto(a: dict, b: dict, seed: str):
    """Авто-бой двух собранных бойцов. 'a' ходит первым; каждые cd личных
    ходов — скилл класса; ничья на лимите ходов = победа защищающегося.
    Возвращает (winner, log): winner — 'a' или 'b'."""
    rng = random.Random(seed)
    me_s = {'a': {'hp': int(a['max']), 'used': 0, 'skip': 0},
            'b': {'hp': int(b['max']), 'used': 0, 'skip': 0}}
    log = []
    for _ in range(BT_MAX_TURNS):
        for side in ('a', 'b'):
            foe_id = 'b' if side == 'a' else 'a'
            me_d = a if side == 'a' else b
            foe_d = b if side == 'a' else a
            mine = me_s[side]
            name = me_d.get('name', side)
            if mine['skip'] > 0:
                mine['skip'] -= 1
                log.append('%s пропускает ход 😴' % name)
                continue
            mine['used'] += 1
            skill = BT_SKILLS.get(me_d.get('cls', ''))
            if skill is not None and mine['used'] % skill['cd'] == 0:
                power = skill['mult'] * (me_d['mag'] if skill.get('element')
                                         else me_d['atk'])
                elem = skill.get('element', me_d['element'])
                dfn = foe_d['dfn'] * (1.0 - skill.get('def_ignore', 0.0))
                dmg, _ = _roll_damage(rng, power, elem, dfn, foe_d['element'])
                if skill.get('stun'):
                    me_s[foe_id]['skip'] = 1
                log.append('%s ✨ скилл на %d' % (name, dmg))
            else:
                dmg, _ = _roll_damage(rng, me_d['atk'], me_d['element'],
                                      foe_d['dfn'], foe_d['element'], me_d['crit'])
                log.append('%s бьёт на %d' % (name, dmg))
            me_s[foe_id]['hp'] -= dmg
            if me_s[foe_id]['hp'] <= 0:
                return side, log
    return 'b', log  # лимит ходов — ничья трактуется в пользу защищающегося
