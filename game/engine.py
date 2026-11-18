"""Pure game logic: time decay, actions, economy, sickness, progression.

No I/O, fully unit-testable. Server-authoritative by design: the widget and
the chat commands never mutate state directly, they only request actions;
every mutation happens here and is persisted by the handlers.

By design there is NO death: the worst outcomes are care misses and an
ugly adult branch.
"""
import random
import time
from typing import Dict, List, Optional, Tuple

from game.balance import (
    ADULT_AFTER_DAYS,
    CARE_MISS_PENALTY,
    CLEAN_COINS,
    CLEAN_COOLDOWN_SECONDS,
    ENERGY_DECAY_PER_HOUR,
    ENERGY_REGEN_SLEEP_PER_HOUR,
    FOOD_EFFECTS,
    FOOD_PRIORITY,
    HATCH_MOOD_GAIN,
    HUNGER_DECAY_PER_HOUR,
    HUNGER_DECAY_SLEEP_PER_HOUR,
    HUNGRY_NOTIFY_AT,
    HYGIENE_DECAY_PER_HOUR,
    NAME_MAX_LEN,
    LOW_STAT_THRESHOLD,
    MAX_OFFLINE_SECONDS,
    MOOD_DECAY_PER_HOUR,
    MOOD_EXTRA_DECAY_PER_HOUR,
    NIGHT_END_HOUR,
    NIGHT_START_HOUR,
    PET_COOLDOWN_SECONDS,
    PET_MOOD_GAIN,
    PLAY_ENERGY_COST,
    PLAY_MIN_ENERGY,
    PLAY_MOOD_GAIN,
    SCAVENGE_COOLDOWN_SECONDS,
    SCAVENGE_SATIETY,
    SHOP,
    SICK_AUTO_HEAL_HOURS,
    SICK_CHANCE_BASE_PER_HOUR,
    SICK_CHANCE_DIRTY_PER_HOUR,
    SICK_CHANCE_STARVE_PER_HOUR,
    SICK_ENERGY_EXTRA_PER_HOUR,
    SICK_MOOD_EXTRA_PER_HOUR,
    SLEEP_COINS_PER_HOUR,
    STAGE_ADULT_BEAUTY,
    STAGE_ADULT_HOOLIGAN,
    STAGE_ADULT_WISE,
    STAGE_BABY,
    STAGE_EGG,
    STAGE_TEEN,
    TEEN_AFTER_DAYS,
    BED_REGEN_PER_LEVEL,
    BOWL_SATIETY_PER_LEVEL,
    CHARISMA_HYGIENE_MIN,
    CHARISMA_PER_HOUR,
    HIDDEN_CAP,
    HUNGER_DECAY_NOBLE_MULT,
    ROOM,
    TREE_CAP_HOURS,
    TREE_COINS_PER_HOUR,
    WEAR_CHARISMA,
    XP_GRANTS,
    ZONE_PLAY_MOOD_PER_LEVEL,
)
from game import battle
from game import expeditions
from game import gear
from game import minigames
from game import progress
from game.cases import CASES, CHEST_ACC_TITLES, apply_drop, roll
from game.pets import SPECIES, is_species
from game.promo import redeem as redeem_promo
from game.state import PetState

ACTIONS = frozenset({'sync', 'feed', 'play', 'sleep', 'pet', 'clean', 'heal',
                     'buy', 'wear', 'open_case', 'setpet', 'promo',
                     'game_start', 'game_end', 'quest_claim', 'collect_tree',
                     'prestige', 'visit', 'rename',
                     'battle_start', 'battle_move', 'battle_flee',
                     'expedition_start', 'expedition_collect',
                     'gear_buy', 'gear_equip', 'gear_up', 'arena_fight'})


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _local_hour(now: int, tz_offset: float) -> float:
    """Local wall-clock hour at `now` (fractional, 0..24)."""
    return ((now + tz_offset * 3600) % 86400) / 3600.0


def _night_hours(start: float, end: float, tz_offset: float) -> float:
    """Hours of the interval [start, end] falling into the 23:00–07:00
    local night window (auto sleep)."""
    if end <= start:
        return 0.0
    tz_shift = tz_offset * 3600
    first_day = int((start + tz_shift) // 86400)
    total = 0.0
    for day in range(first_day - 1, first_day + 3):
        # окно: локальные 23:00 дня day -> локальные 07:00 следующего дня
        ns = day * 86400 + NIGHT_START_HOUR * 3600 - tz_shift
        ne = day * 86400 + (NIGHT_START_HOUR + 8) * 3600 - tz_shift
        s = max(start, ns)
        e = min(end, ne)
        if e > s:
            total += e - s
    return total / 3600.0


def tick(st: PetState, now: int, tz_offset: float = 0) -> List[str]:
    """Advance the pet to `now`, applying lazy decay, economy and sickness.

    The pet auto-sleeps during the local night (23:00–07:00 by tz_offset,
    hours east of UTC); auto sleep ends by itself in the morning. A manual
    sleep (the sleep action) is never cancelled by the clock.

    Events: 'hungry' (every tick while hungry; the handler throttles),
    'sick' (a new sickness started), 'healed_auto' (recovered on its own,
    +1 care miss), 'neglect' (a stat just hit zero, +1 care miss),
    'teen', 'adult', 'class' (hidden stats picked an adult class).
    """
    events: List[str] = []
    dt = max(0, min(now - st.last_tick, MAX_OFFLINE_SECONDS))
    hours = dt / 3600.0

    # сколько часов паузы питомец проспал (ночь и/или ручной сон)
    sleep_h = 0.0
    if st.stage != STAGE_EGG:
        if st.sleeping and not st.auto_sleep:
            # ручной сон длится, пока игрок не разбудит: вся пауза — сон
            sleep_h = hours
            st.auto_sleep = False
        else:
            night_h = _night_hours(now - dt, now, tz_offset)
            if _local_hour(now, tz_offset) >= NIGHT_START_HOUR \
                    or _local_hour(now, tz_offset) < NIGHT_END_HOUR:
                st.sleeping = True
                st.auto_sleep = True
            elif st.auto_sleep:
                # 7:00 утра — питомец просыпается сам
                st.sleeping = False
                st.auto_sleep = False
            sleep_h = night_h

    if dt > 0 and st.stage != STAGE_EGG:
        awake_h = max(0.0, hours - sleep_h)

        hunger_rate = (HUNGER_DECAY_PER_HOUR * awake_h
                       + HUNGER_DECAY_SLEEP_PER_HOUR * sleep_h) / hours if hours else 0.0
        if st.cls == 'noble':
            hunger_rate *= HUNGER_DECAY_NOBLE_MULT
        prev_satiety = st.satiety
        st.satiety = _clamp(st.satiety - hunger_rate * hours)
        if prev_satiety > 0.0 and st.satiety <= 0.0:
            st.care_miss += 1
            events.append('neglect')

        st.energy = _clamp(st.energy
                           + ENERGY_REGEN_SLEEP_PER_HOUR
                           * (1.0 + BED_REGEN_PER_LEVEL * st.room.get('bed', 0)) * sleep_h
                           - ENERGY_DECAY_PER_HOUR * awake_h)
        st.coins += SLEEP_COINS_PER_HOUR * sleep_h

        # денежное дерево: пассивный доход, копится до тапа-сбора
        tree_lvl = st.room.get('tree', 0)
        if tree_lvl > 0:
            rate = TREE_COINS_PER_HOUR * tree_lvl
            st.tree_pending = min(rate * TREE_CAP_HOURS,
                                  st.tree_pending + rate * hours)

        prev_hygiene = st.hygiene
        st.hygiene = _clamp(st.hygiene - HYGIENE_DECAY_PER_HOUR * hours)
        if prev_hygiene > 0.0 and st.hygiene <= 0.0:
            st.care_miss += 1
            events.append('neglect')

        # харизма растёт только при идеальной гигиене (скрытая стата)
        if st.hygiene >= CHARISMA_HYGIENE_MIN:
            st.ch = min(HIDDEN_CAP, st.ch + CHARISMA_PER_HOUR * hours)

        mood_dec = MOOD_DECAY_PER_HOUR * hours
        if st.satiety < LOW_STAT_THRESHOLD:
            mood_dec += MOOD_EXTRA_DECAY_PER_HOUR * hours
        if st.sick:
            mood_dec += SICK_MOOD_EXTRA_PER_HOUR * hours
        st.mood = _clamp(st.mood - mood_dec)
        if st.sick:
            # болезнь давит на силы только пока питомец не спит
            st.energy = _clamp(st.energy - SICK_ENERGY_EXTRA_PER_HOUR * awake_h)

        # sickness roll (a sick pet cannot catch a new disease)
        if not st.sick:
            chance_per_hour = SICK_CHANCE_BASE_PER_HOUR
            if st.hygiene < LOW_STAT_THRESHOLD:
                chance_per_hour = max(chance_per_hour, SICK_CHANCE_DIRTY_PER_HOUR)
            if st.satiety < LOW_STAT_THRESHOLD:
                chance_per_hour = max(chance_per_hour, SICK_CHANCE_STARVE_PER_HOUR)
            if random.random() < chance_per_hour * hours:
                st.sick = True
                st.sick_since = now
                events.append('sick')
        elif now - st.sick_since >= SICK_AUTO_HEAL_HOURS * 3600:
            st.sick = False
            st.care_miss += 1
            events.append('healed_auto')

        # progression (only the healthy track: egg hatches via feed action)
        if st.stage == STAGE_BABY and now - st.born >= TEEN_AFTER_DAYS * 86400:
            st.stage = STAGE_TEEN
            events.append('teen')
        if st.stage == STAGE_TEEN and now - st.born >= ADULT_AFTER_DAYS * 86400:
            st.stage = _adult_branch(st)
            events.append('adult')

        # класс по доминирующей скрытой стате (догоняем и пропустивших тик)
        if st.stage not in (STAGE_EGG, STAGE_BABY, STAGE_TEEN) and not st.cls:
            st.cls = progress.dominant_class(st)
            if st.cls:
                events.append('class')

    st.last_tick = now
    return events


def _adult_branch(st: PetState) -> int:
    if st.care_miss == 0:
        return STAGE_ADULT_WISE
    if st.care_score >= CARE_MISS_PENALTY * st.care_miss:
        return STAGE_ADULT_BEAUTY
    return STAGE_ADULT_HOOLIGAN


def update_streak(st: PetState, now: int,
                  tz_offset: float = 0) -> Optional[dict]:
    """Count the first visit of a local day (user timezone, hours east of UTC).

    Streak grants a reward from the DAILY_REWARDS table by cycle day
    ((streak - 1) % len(DAILY_REWARDS) + 1) once per local day.
    Returns the granted reward dict (with 'label' and 'cycle_day') or None.
    """
    from game.balance import DAILY_REWARDS
    day = time.strftime('%Y-%m-%d', time.gmtime(now + tz_offset * 3600))
    if st.streak_day == day:
        return None
    yesterday = time.strftime('%Y-%m-%d', time.gmtime(now + tz_offset * 3600 - 86400))
    st.streak = st.streak + 1 if st.streak_day == yesterday else 1
    st.streak_day = day
    cycle_day = (st.streak - 1) % len(DAILY_REWARDS) + 1
    reward = dict(DAILY_REWARDS[cycle_day - 1])
    reward['cycle_day'] = cycle_day
    if 'coins' in reward:
        st.coins += reward['coins']
    if 'item' in reward:
        st.inv[reward['item']] = st.inv.get(reward['item'], 0) + reward.get('n', 1)
    if 'case' in reward:
        st.pending_case = reward['case']
    return reward


def best_food(st: PetState) -> str:
    for item in FOOD_PRIORITY:
        if st.inv.get(item, 0) > 0:
            return item
    return ''


def apply(st: PetState, action: str, arg: str, now: int) -> Tuple[PetState, str, bool]:
    """Apply an action. Returns (state, message_for_user, changed).

    Central Progression 2.0 hook: every successful action feeds daily
    quests and re-checks achievements; earned achievements are appended
    to the message. `changed` tells the handler whether to bump `rev`
    and edit the widget.
    """
    if action == 'sync':
        progress.ensure_quests(st, now)
        return st, '', False
    st, message, changed = _apply_core(st, action, arg, now)
    if changed:
        progress.on_action(st, action)
    achv_lines = progress.check_achievements(st)
    if achv_lines:
        message = '\n'.join(([message] if message else []) + achv_lines)
    return st, message, changed


def _apply_core(st: PetState, action: str, arg: str,
                now: int) -> Tuple[PetState, str, bool]:

    if action == 'feed':
        return _apply_feed(st, arg, now)

    if action == 'play':
        if st.stage == STAGE_EGG:
            return st, 'Яйцу не до игр 🙂', False
        if st.sleeping:
            return st, '%s спит… не буди 🤫' % st.name, False
        if st.energy < PLAY_MIN_ENERGY:
            return st, 'Слишком устал для игр 😴', False
        st.mood = _clamp(st.mood + PLAY_MOOD_GAIN
                         * (1.0 + ZONE_PLAY_MOOD_PER_LEVEL * st.room.get('zone', 0)))
        st.energy = _clamp(st.energy - PLAY_ENERGY_COST)
        st.care_score += 1
        message = 'Ура, весело! 🎉\n' + progress.add_xp(st, XP_GRANTS['play'], now)
        return st, message.strip(), True

    if action == 'sleep':
        if st.stage == STAGE_EGG:
            return st, 'Яйцу не до сна 🙂', False
        if st.sleeping and st.auto_sleep:
            # ночной сон (23:00–07:00) вручную не прерывается
            return st, '🌙 %s крепко спит — проснётся в 7:00 утра.' % st.name, False
        st.auto_sleep = False
        st.sleeping = not st.sleeping
        if st.sleeping:
            return st, '😴 %s уснул… Пока спит, ищет монетки (+%d🪙/час).' % (
                st.name, int(SLEEP_COINS_PER_HOUR)), True
        return st, '☀️ Доброе утро!', True

    if action == 'pet':
        if st.stage == STAGE_EGG:
            return st, 'Яйцо довольно завибрировало 🥚', False
        if st.last_act_code == 'pet' and now - st.last_act < PET_COOLDOWN_SECONDS:
            return st, 'Ещё рано, погладь позже 🙂', False
        st.mood = _clamp(st.mood + PET_MOOD_GAIN)
        st.last_act = now
        st.last_act_code = 'pet'
        message = 'Муррр… 😊\n' + progress.add_xp(st, XP_GRANTS['pet'], now)
        return st, message.strip(), True

    if action == 'clean':
        last = st.cooldowns.get('clean', 0)
        if now - last < CLEAN_COOLDOWN_SECONDS:
            return st, 'Мыть пока не нужно 🙂', False
        st.cooldowns['clean'] = now
        st.hygiene = 100.0
        st.coins += CLEAN_COINS
        st.care_score += 1
        message = ('🛁 Чистота! +%d🪙\n' % CLEAN_COINS
                   + progress.add_xp(st, XP_GRANTS['clean'], now))
        return st, message.strip(), True

    if action == 'heal':
        if not st.sick:
            return st, '%s и не болеет 😊' % st.name, False
        if st.inv.get('med', 0) <= 0:
            return st, 'Нет лекарства! Купи: /buy med', False
        st.inv['med'] -= 1
        st.sick = False
        st.care_score += 2
        message = ('💊 Лекарство помогло, %s здоров!\n' % st.name
                   + progress.add_xp(st, XP_GRANTS['heal'], now))
        return st, message.strip(), True

    if action == 'buy':
        room_id = (arg or '').strip().lower()
        if room_id in ROOM:
            return _apply_buy_room(st, room_id)
        return _apply_buy(st, arg)

    if action == 'wear':
        return _apply_wear(st, arg)

    if action == 'open_case':
        return _apply_open_case(st, arg)

    if action == 'setpet':
        return _apply_setpet(st, arg)

    if action == 'promo':
        return redeem_promo(st, arg, now)

    if action == 'game_start':
        return minigames.start(st, arg, now)

    if action == 'game_end':
        return minigames.end(st, arg, now)

    if action == 'quest_claim':
        return progress.claim_quests(st, now)

    if action == 'prestige':
        return progress.prestige(st, now)

    if action == 'collect_tree':
        return _apply_collect_tree(st)

    if action == 'rename':
        return _apply_rename(st, arg)

    # --- боевая система ---
    if action == 'battle_start':
        return battle.battle_start(st, arg, now)
    if action == 'battle_move':
        return battle.battle_move(st, arg, now)
    if action == 'battle_flee':
        return battle.battle_flee(st, arg, now)
    if action == 'expedition_start':
        return expeditions.expedition_start(st, arg, now)
    if action == 'expedition_collect':
        return expeditions.expedition_collect(st, arg, now)
    if action == 'gear_buy':
        return gear.gear_buy(st, arg, now)
    if action == 'gear_equip':
        return gear.gear_equip(st, arg, now)
    if action == 'gear_up':
        return gear.gear_up(st, arg, now)
    # arena_fight перехватывается в handlers.web_action (нужен соперник из БД)

    return st, 'Не понимаю 🤔', False


def _apply_rename(st: PetState, arg: str) -> Tuple[PetState, str, bool]:
    name = ' '.join((arg or '').split())
    if not name:
        return st, 'Имя не может быть пустым 🙃', False
    if len(name) > NAME_MAX_LEN:
        return st, 'Имя длиннее %d символов 🤏' % NAME_MAX_LEN, False
    if name == st.name:
        return st, 'Так уже зовут 🙂', False
    st.name = name
    return st, 'Теперь я %s!' % name, True


def _apply_collect_tree(st: PetState) -> Tuple[PetState, str, bool]:
    pending = int(round(st.tree_pending))
    if pending <= 0:
        lvl = st.room.get('tree', 0)
        if lvl == 0:
            return st, 'Дерева ещё нет — купи его в магазине комнат 🌳', False
        return st, 'Дерево пока не накопило монет, заходи позже 🌳', False
    st.coins += pending
    st.tree_pending = 0.0
    return st, '🌳 Тряс дерево: +%d🪙 упало!' % pending, True


def _apply_buy_room(st: PetState, room_id: str) -> Tuple[PetState, str, bool]:
    item = ROOM[room_id]
    lvl = st.room.get(room_id, 0)
    if lvl >= len(item['prices']):
        return st, '%s уже на максимальном уровне!' % item['title'], False
    price = item['prices'][lvl]
    if st.coins < price:
        return st, ('Не хватает монет: нужно %d🪙, есть %d🪙'
                    % (price, int(round(st.coins)))), False
    st.coins -= price
    st.room[room_id] = lvl + 1
    return st, '%s — уровень %d! ✨' % (item['title'], lvl + 1), True


def _apply_buy(st: PetState, item_id: str) -> Tuple[PetState, str, bool]:
    item_id = (item_id or '').strip().lower()
    item = SHOP.get(item_id)
    if item is None:
        return st, 'Нет такого товара. Смотри /shop', False
    if item['kind'] == 'accessory' and item_id in st.acc:
        return st, '%s уже куплен — надеть: /wear %s' % (item['title'], item_id), False
    if st.coins < item['price']:
        return st, ('Не хватает монет: нужно %d🪙, у тебя %d🪙. '
                    'Спи побольше — во сне питомец зарабатывает!'
                    % (item['price'], int(round(st.coins)))), False
    st.coins -= item['price']
    if item['kind'] == 'accessory':
        st.acc.append(item_id)
        return st, '%s куплен! Надеть: /wear %s' % (item['title'], item_id), True
    st.inv[item_id] = st.inv.get(item_id, 0) + 1
    return st, '%s в инвентаре: ×%d' % (item['title'], st.inv[item_id]), True


def _apply_wear(st: PetState, item_id: str) -> Tuple[PetState, str, bool]:
    item_id = (item_id or '').strip().lower()
    if item_id in ('', 'off'):
        st.worn = ''
        return st, 'Снял всё нарядное', True
    if item_id not in st.acc:
        return st, 'Сначала купи: /buy %s' % item_id, False
    st.worn = '' if st.worn == item_id else item_id
    if st.worn:
        st.ch = min(HIDDEN_CAP, st.ch + WEAR_CHARISMA)
    verb = 'Снял' if not st.worn else 'Надел'
    title = (SHOP.get(item_id, {}).get('title')
             or CHEST_ACC_TITLES.get(item_id, item_id))
    return st, '%s %s' % (verb, title), True


def _apply_open_case(st: PetState, case_id: str) -> Tuple[PetState, str, bool]:
    case_id = (case_id or '').strip().lower()
    case = CASES.get(case_id)
    if case is None:
        return st, 'Нет такого сундука 🤔', False
    if st.pending_case == case_id:
        # бесплатный сундук из ежедневной награды — цена не списывается
        st.pending_case = ''
        st.chests_total += 1
        line = apply_drop(st, roll(case))
        return st, 'Открыл %s (награда за вход): %s' % (case['title'], line), True
    currency = case.get('currency', 'coins')
    if currency == 'gems':
        if st.gems < case['price']:
            return st, ('Не хватает кристаллов: %s стоит %d💎, у тебя %d💎. '
                        'Кристаллы дают мини-игры и ачивки!'
                        % (case['title'], case['price'], int(st.gems))), False
        st.gems -= case['price']
    else:
        if st.coins < case['price']:
            return st, ('Не хватает монет: %s стоит %d🪙, у тебя %d🪙. '
                        'Спи побольше — во сне питомец зарабатывает!'
                        % (case['title'], case['price'], int(round(st.coins)))), False
        st.coins -= case['price']
    st.chests_total += 1
    line = apply_drop(st, roll(case))
    return st, 'Открыл %s: %s' % (case['title'], line), True


def _apply_setpet(st: PetState, species_id: str) -> Tuple[PetState, str, bool]:
    species_id = (species_id or '').strip().lower()
    if not is_species(species_id):
        return st, 'Нет такого питомца 🤔', False
    if species_id == st.species:
        return st, '%s уже активен' % SPECIES[species_id]['title'], False
    if species_id not in st.pets:
        return st, 'Этот питомец ещё не разблокирован 🔒', False
    st.species = species_id
    return st, '%s теперь твой активный питомец!' % SPECIES[species_id]['title'], True


def _apply_feed(st: PetState, arg: str, now: int) -> Tuple[PetState, str, bool]:
    if st.stage == STAGE_EGG:
        st.stage = STAGE_BABY
        st.satiety = _clamp(st.satiety + 25.0)
        st.mood = _clamp(st.mood + HATCH_MOOD_GAIN)
        st.care_score += 1
        return st, '🥚 Треснуло! %s вылупился!' % st.name, True

    item = ''
    if arg:
        arg = arg.lower()
        if arg in FOOD_EFFECTS and st.inv.get(arg, 0) > 0:
            item = arg
        else:
            return st, 'Такой еды нет в инвентаре — загляни в /shop', False
    else:
        item = best_food(st)

    effects: Dict[str, float] = {}
    if item:
        st.inv[item] -= 1
        effects = FOOD_EFFECTS[item]
        title = SHOP[item]['title']
    else:
        # nothing in inventory: the pet forages, weaker effect, no lock-out
        last = st.cooldowns.get('scavenge', 0)
        if now - last < SCAVENGE_COOLDOWN_SECONDS:
            minutes = max(1, (SCAVENGE_COOLDOWN_SECONDS - (now - last) + 59) // 60)
            return st, 'Питомец недавно искал еду — попробуй через ~%d мин 🌿' % minutes, False
        st.cooldowns['scavenge'] = now
        effects = {'satiety': SCAVENGE_SATIETY}
        title = 'яблочко, найденное в кустах 🌿'

    st.satiety = _clamp(st.satiety + effects.get('satiety', 0.0)
                        + BOWL_SATIETY_PER_LEVEL * st.room.get('bowl', 0))
    st.mood = _clamp(st.mood + effects.get('mood', 0.0))
    st.energy = _clamp(st.energy + effects.get('energy', 0.0))
    st.care_score += 1
    suffix = ' 🤒' if st.sick else ''
    message = ('%s съеден%s: +%s сытости\n'
               % (title, suffix, int(effects.get('satiety', 0.0)))
               + progress.add_xp(st, XP_GRANTS['feed'], now))
    return st, message.strip(), True


def phrase(st: PetState) -> str:
    """A short line the pet 'says', derived from its state."""
    if st.sick:
        return random.choice(['🤒 %s чихает… нужен /buy med' % st.name,
                              '%s грустно смотрит на градусник 🤒' % st.name])
    if st.sleeping:
        return random.choice(['😴 %s посапывает и мечтает о %d🪙' % (st.name, int(st.coins)),
                              'Тише… %s видит сон про торт 🍰' % st.name])
    if st.satiety < LOW_STAT_THRESHOLD or st.mood < LOW_STAT_THRESHOLD:
        return random.choice(['%s грустно смотрит в пустую миску 🥣' % st.name,
                              'Кажется, %s скучает… /pet' % st.name])
    return random.choice(['%s довольно мурлычет 😊' % st.name,
                          '%s играет с солнечным зайчиком ☀️' % st.name,
                          '%s в отличной форме! 💪' % st.name])
