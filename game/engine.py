"""Pure game logic: time decay, actions, progression. No I/O, fully unit-testable.

Server-authoritative by design: the widget never edits state, it only requests
actions; every mutation happens here and is persisted by the handlers.
"""
from typing import List, Tuple

from game.balance import (
    ADULT_AFTER_DAYS,
    ENERGY_DECAY_PER_HOUR,
    ENERGY_REGEN_SLEEP_PER_HOUR,
    FEED_SATIETY_GAIN,
    HATCH_MOOD_GAIN,
    HUNGER_DECAY_PER_HOUR,
    HUNGER_DECAY_SLEEP_PER_HOUR,
    HUNGRY_NOTIFY_AT,
    LOW_STAT_THRESHOLD,
    MAX_OFFLINE_SECONDS,
    MOOD_DECAY_PER_HOUR,
    MOOD_EXTRA_DECAY_PER_HOUR,
    PET_COOLDOWN_SECONDS,
    PET_MOOD_GAIN,
    PLAY_ENERGY_COST,
    PLAY_MIN_ENERGY,
    PLAY_MOOD_GAIN,
    TEEN_AFTER_DAYS,
)
from game.state import PetState

ACTIONS = frozenset({'sync', 'feed', 'play', 'sleep', 'pet'})


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def tick(st: PetState, now: int) -> List[str]:
    """Advance the pet to `now`, applying lazy decay. Returns event list.

    Events: 'hungry' (fires every tick while satiety < threshold; the handler
    throttles notifications), 'teen', 'adult'.
    """
    events: List[str] = []
    dt = max(0, min(now - st.last_tick, MAX_OFFLINE_SECONDS))
    if dt > 0 and st.stage > 0:
        hours = dt / 3600.0
        hunger_rate = HUNGER_DECAY_SLEEP_PER_HOUR if st.sleeping else HUNGER_DECAY_PER_HOUR
        st.satiety = _clamp(st.satiety - hunger_rate * hours)
        if st.sleeping:
            st.energy = _clamp(st.energy + ENERGY_REGEN_SLEEP_PER_HOUR * hours)
        else:
            st.energy = _clamp(st.energy - ENERGY_DECAY_PER_HOUR * hours)
        mood_dec = MOOD_DECAY_PER_HOUR * hours
        if st.satiety < LOW_STAT_THRESHOLD:
            mood_dec += MOOD_EXTRA_DECAY_PER_HOUR * hours
        st.mood = _clamp(st.mood - mood_dec)
        if st.stage == 1:
            days = (now - st.born) / 86400.0
            if days >= ADULT_AFTER_DAYS:
                st.stage = 3
                events.append('adult')
            elif days >= TEEN_AFTER_DAYS:
                st.stage = 2
                events.append('teen')
        if st.satiety < HUNGRY_NOTIFY_AT:
            events.append('hungry')
    st.last_tick = now
    return events


def apply(st: PetState, action: str, now: int) -> Tuple[PetState, str, bool]:
    """Apply a widget action. Returns (state, message_for_widget, changed).

    `changed` tells the handler whether to bump `rev` and edit the widget.
    """
    if action == 'sync':
        return st, '', False

    if action == 'feed':
        if st.stage == 0:
            st.stage = 1
            st.satiety = _clamp(st.satiety + FEED_SATIETY_GAIN)
            st.mood = _clamp(st.mood + HATCH_MOOD_GAIN)
            return st, '🥚 Треснуло! %s вылупился!' % st.name, True
        st.satiety = _clamp(st.satiety + FEED_SATIETY_GAIN)
        return st, 'Ням-ням! 🍎', True

    if action == 'play':
        if st.stage == 0:
            return st, 'Яйцу не до игр 🙂', False
        if st.sleeping:
            return st, '%s спит… не буди 🤫' % st.name, False
        if st.energy < PLAY_MIN_ENERGY:
            return st, 'Слишком устал для игр 😴', False
        st.mood = _clamp(st.mood + PLAY_MOOD_GAIN)
        st.energy = _clamp(st.energy - PLAY_ENERGY_COST)
        return st, 'Ура, весело! 🎉', True

    if action == 'sleep':
        if st.stage == 0:
            return st, 'Яйцу не до сна 🙂', False
        st.sleeping = not st.sleeping
        if st.sleeping:
            return st, '😴 %s уснул…' % st.name, True
        return st, '☀️ Доброе утро!', True

    if action == 'pet':
        if st.stage == 0:
            return st, 'Яйцо довольно завибрировало 🥚', False
        if st.last_act_code == 'pet' and now - st.last_act < PET_COOLDOWN_SECONDS:
            return st, 'Ещё рано, погладь позже 🙂', False
        st.mood = _clamp(st.mood + PET_MOOD_GAIN)
        st.last_act = now
        st.last_act_code = 'pet'
        return st, 'Муррр… 😊', True

    return st, 'Не понимаю 🤔', False
