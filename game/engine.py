"""Pure game logic: time decay, actions, economy, sickness, progression.

No I/O, fully unit-testable. Server-authoritative by design: the widget and
the chat commands never mutate state directly, they only request actions;
every mutation happens here and is persisted by the handlers.

By design there is NO death: the worst outcomes are care misses and an
ugly adult branch.
"""
import random
import time
from typing import Dict, List, Tuple

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
    LOW_STAT_THRESHOLD,
    MAX_OFFLINE_SECONDS,
    MOOD_DECAY_PER_HOUR,
    MOOD_EXTRA_DECAY_PER_HOUR,
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
)
from game.cases import CASES, CHEST_ACC_TITLES, apply_drop, roll
from game.pets import SPECIES, is_species
from game.promo import redeem as redeem_promo
from game.state import PetState

ACTIONS = frozenset({'sync', 'feed', 'play', 'sleep', 'pet', 'clean', 'heal',
                     'buy', 'wear', 'open_case', 'setpet', 'promo'})


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def tick(st: PetState, now: int) -> List[str]:
    """Advance the pet to `now`, applying lazy decay, economy and sickness.

    Events: 'hungry' (every tick while hungry; the handler throttles),
    'sick' (a new sickness started), 'healed_auto' (recovered on its own,
    +1 care miss), 'neglect' (a stat just hit zero, +1 care miss),
    'teen', 'adult'.
    """
    events: List[str] = []
    dt = max(0, min(now - st.last_tick, MAX_OFFLINE_SECONDS))
    if dt > 0 and st.stage != STAGE_EGG:
        hours = dt / 3600.0

        hunger_rate = HUNGER_DECAY_SLEEP_PER_HOUR if st.sleeping else HUNGER_DECAY_PER_HOUR
        prev_satiety = st.satiety
        st.satiety = _clamp(st.satiety - hunger_rate * hours)
        if prev_satiety > 0.0 and st.satiety <= 0.0:
            st.care_miss += 1
            events.append('neglect')

        if st.sleeping:
            st.energy = _clamp(st.energy + ENERGY_REGEN_SLEEP_PER_HOUR * hours)
            st.coins += SLEEP_COINS_PER_HOUR * hours
        else:
            st.energy = _clamp(st.energy - ENERGY_DECAY_PER_HOUR * hours)

        prev_hygiene = st.hygiene
        st.hygiene = _clamp(st.hygiene - HYGIENE_DECAY_PER_HOUR * hours)
        if prev_hygiene > 0.0 and st.hygiene <= 0.0:
            st.care_miss += 1
            events.append('neglect')

        mood_dec = MOOD_DECAY_PER_HOUR * hours
        if st.satiety < LOW_STAT_THRESHOLD:
            mood_dec += MOOD_EXTRA_DECAY_PER_HOUR * hours
        if st.sick:
            mood_dec += SICK_MOOD_EXTRA_PER_HOUR * hours
        st.mood = _clamp(st.mood - mood_dec)
        if st.sick:
            st.energy = _clamp(st.energy - SICK_ENERGY_EXTRA_PER_HOUR * hours)

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

    st.last_tick = now
    return events


def _adult_branch(st: PetState) -> int:
    if st.care_miss == 0:
        return STAGE_ADULT_WISE
    if st.care_score >= CARE_MISS_PENALTY * st.care_miss:
        return STAGE_ADULT_BEAUTY
    return STAGE_ADULT_HOOLIGAN


def update_streak(st: PetState, now: int) -> int:
    """Count a daily visit. Returns the coin bonus if a new day was counted, else 0."""
    from game.balance import STREAK_BONUS_BASE, STREAK_BONUS_CAP_DAYS, STREAK_BONUS_STEP
    day = time.strftime('%Y-%m-%d', time.gmtime(now))
    if st.streak_day == day:
        return 0
    yesterday = time.strftime('%Y-%m-%d', time.gmtime(now - 86400))
    st.streak = st.streak + 1 if st.streak_day == yesterday else 1
    st.streak_day = day
    bonus = STREAK_BONUS_BASE + STREAK_BONUS_STEP * min(st.streak - 1, STREAK_BONUS_CAP_DAYS)
    st.coins += bonus
    return bonus


def best_food(st: PetState) -> str:
    for item in FOOD_PRIORITY:
        if st.inv.get(item, 0) > 0:
            return item
    return ''


def apply(st: PetState, action: str, arg: str, now: int) -> Tuple[PetState, str, bool]:
    """Apply an action. Returns (state, message_for_user, changed).

    `changed` tells the handler whether to bump `rev` and edit the widget.
    """
    if action == 'sync':
        return st, '', False

    if action == 'feed':
        return _apply_feed(st, arg, now)

    if action == 'play':
        if st.stage == STAGE_EGG:
            return st, 'Яйцу не до игр 🙂', False
        if st.sleeping:
            return st, '%s спит… не буди 🤫' % st.name, False
        if st.energy < PLAY_MIN_ENERGY:
            return st, 'Слишком устал для игр 😴', False
        st.mood = _clamp(st.mood + PLAY_MOOD_GAIN)
        st.energy = _clamp(st.energy - PLAY_ENERGY_COST)
        st.care_score += 1
        return st, 'Ура, весело! 🎉', True

    if action == 'sleep':
        if st.stage == STAGE_EGG:
            return st, 'Яйцу не до сна 🙂', False
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
        return st, 'Муррр… 😊', True

    if action == 'clean':
        last = st.cooldowns.get('clean', 0)
        if now - last < CLEAN_COOLDOWN_SECONDS:
            return st, 'Мыть пока не нужно 🙂', False
        st.cooldowns['clean'] = now
        st.hygiene = 100.0
        st.coins += CLEAN_COINS
        st.care_score += 1
        return st, '🛁 Чистота! +2🪙', True

    if action == 'heal':
        if not st.sick:
            return st, '%s и не болеет 😊' % st.name, False
        if st.inv.get('med', 0) <= 0:
            return st, 'Нет лекарства! Купи: /buy med', False
        st.inv['med'] -= 1
        st.sick = False
        st.care_score += 2
        return st, '💊 Лекарство помогло, %s здоров!' % st.name, True

    if action == 'buy':
        return _apply_buy(st, arg)

    if action == 'wear':
        return _apply_wear(st, arg)

    if action == 'open_case':
        return _apply_open_case(st, arg)

    if action == 'setpet':
        return _apply_setpet(st, arg)

    if action == 'promo':
        return redeem_promo(st, arg)

    return st, 'Не понимаю 🤔', False


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
    verb = 'Снял' if not st.worn else 'Надел'
    title = (SHOP.get(item_id, {}).get('title')
             or CHEST_ACC_TITLES.get(item_id, item_id))
    return st, '%s %s' % (verb, title), True


def _apply_open_case(st: PetState, case_id: str) -> Tuple[PetState, str, bool]:
    case_id = (case_id or '').strip().lower()
    case = CASES.get(case_id)
    if case is None:
        return st, 'Нет такого сундука 🤔', False
    if st.coins < case['price']:
        return st, ('Не хватает монет: %s стоит %d🪙, у тебя %d🪙. '
                    'Спи побольше — во сне питомец зарабатывает!'
                    % (case['title'], case['price'], int(round(st.coins)))), False
    st.coins -= case['price']
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

    st.satiety = _clamp(st.satiety + effects.get('satiety', 0.0))
    st.mood = _clamp(st.mood + effects.get('mood', 0.0))
    st.energy = _clamp(st.energy + effects.get('energy', 0.0))
    st.care_score += 1
    suffix = ' 🤒' if st.sick else ''
    return st, '%s съеден%s: +%s сытости' % (title, suffix, int(effects.get('satiety', 0.0))), True


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
