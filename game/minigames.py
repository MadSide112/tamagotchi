"""Mini-games: server-authoritative sessions with anti-cheat.

Flow: the client posts action 'game_start' (arg = game id); the server
stores the start ts in st.cooldowns['gs_<id>'] and answers. When a round
ends the client posts 'game_end' with arg '<id>:<score>:<client_dur>' — the
client duration is ignored, the server re-measures the real elapsed time and
rejects anything outside [MG_MIN_SECONDS, MG_MAX_SECONDS+30]. Scores are
clamped to per-game caps, rewards are computed here, and daily coin/gem caps
live in the state, so no client value is trusted.
"""
import random
import time
from typing import List, Tuple

from game.balance import (
    CLASS_COIN_MULT_WARRIOR,
    HIDDEN_CAP,
    MG_DAILY_COIN_CAP,
    MG_ENERGY_COST,
    MG_GAMES,
    MG_GAMES_DAILY_CAP,
    MG_GEM_ROUND,
    MG_GEMS_DAILY_CAP,
    MG_MAX_SECONDS,
    MG_MIN_SECONDS,
    MG_SCORE_CAPS,
    SHOP,
    ZONE_SCORE_PER_LEVEL,
)
from game.progress import add_xp, day_of
from game.state import PetState

_SESSION_PREFIX = 'gs_'


def start(st: PetState, game_id: str, now: int) -> Tuple[PetState, str, bool]:
    game_id = (game_id or '').strip().lower()
    game = MG_GAMES.get(game_id)
    if game is None:
        return st, 'Не знаю такую игру 🤔', False
    if st.stage == 0:
        return st, 'Яйцу не до игр 🙂', False
    if st.sleeping:
        return st, '%s спит… не буди 🤫' % st.name, False
    if st.energy < MG_ENERGY_COST:
        return st, 'Мало энергии для игры (нужно %d) 😴' % int(MG_ENERGY_COST), False
    st.cooldowns[_SESSION_PREFIX + game_id] = now
    return st, '🎮 %s — старт! У тебя %d сек.' % (game['title'], MG_MAX_SECONDS), True


def end(st: PetState, arg: str, now: int) -> Tuple[PetState, str, bool]:
    parts = (arg or '').split(':')
    if len(parts) != 3:
        return st, 'Кривой результат игры 🤔', False
    game_id = parts[0].strip().lower()
    game = MG_GAMES.get(game_id)
    if game is None:
        return st, 'Не знаю такую игру 🤔', False
    started = st.cooldowns.pop(_SESSION_PREFIX + game_id, 0)
    if not started:
        return st, 'Сначала начни игру 🙂', False

    # анти-чит: длительность измеряет сервер, не клиент
    elapsed = now - started
    if elapsed < MG_MIN_SECONDS:
        return st, 'Сессия не засчитана: слишком быстро ⏱', False
    if elapsed > MG_MAX_SECONDS + 30:
        return st, 'Сессия истекла — начни заново ⏱', False
    try:
        score = int(parts[1])
    except (TypeError, ValueError):
        return st, 'Кривой результат игры 🤔', False
    cap = MG_SCORE_CAPS.get(game_id, 999)
    score = max(0, min(cap, score))

    _daily_reset(st, now)
    if st.mg_games >= MG_GAMES_DAILY_CAP:
        return st, 'Дневной лимит игр достигнут — заходи завтра 🙂', False

    # игровая зона в комнате усиливает результат
    score = min(cap, int(round(score * (1.0 + ZONE_SCORE_PER_LEVEL
                                            * st.room.get('zone', 0)))))

    st.energy = max(0.0, st.energy - MG_ENERGY_COST)
    st.mg_games += 1
    st.games_total += 1

    coins, xp, stat_gain, extra = _rewards(st, game_id, score, now)
    if st.cls == 'warrior':
        coins = int(round(coins * CLASS_COIN_MULT_WARRIOR))

    # мягкий дневной кап монет из мини-игр: сверх капа начисляется только XP
    room_left = MG_DAILY_COIN_CAP - st.mg_coins
    if coins > room_left:
        coins = max(0, room_left)
    st.mg_coins += coins
    note = ' (дневной кап монет — только XP)' if coins == 0 and room_left <= 0 else ''

    stat_key = game['stat']
    setattr(st, stat_key, min(HIDDEN_CAP, getattr(st, stat_key) + stat_gain))

    xp_line = add_xp(st, xp, now, bonus_source=True)
    lines: List[str] = ['🎮 %s: +%d🪙, +%d XP%s'
                        % (game['title'], coins, xp, note)]
    lines.extend(extra)
    if xp_line:
        lines.append(xp_line)
    return st, '\n'.join(lines), True


def _rewards(st: PetState, game_id: str, score: int, now: int) -> Tuple[int, int, float, List[str]]:
    """Per-game rewards: (coins, xp, hidden-stat gain, bonus lines)."""
    extra: List[str] = []
    if game_id == 'catch':
        coins = min(30, score // 3)
        xp = min(30, 10 + score // 15)
        stat = min(3.0, score / 30.0)
        if score >= 40:
            food = random.choice(('apple', 'fish'))
            st.inv[food] = st.inv.get(food, 0) + 1
            extra.append('%s в инвентаре 🧺' % SHOP[food]['title'])
        return coins, xp, stat, extra

    if game_id == 'fish':
        coins = score * 6
        xp = min(30, 8 + score * 4)
        stat = min(3.0, score / 3.0)
        if score >= 5:
            coins += 30
            extra.append('идеальный заброс: +30🪙 🎯')
        return coins, xp, stat, extra

    # simon: кристаллы капают с раунда MG_GEM_ROUND, дневной кап в cooldowns
    coins = min(32, score * 4)
    xp = min(30, 8 + score * 3)
    stat = min(3.0, score / 4.0)
    if score >= MG_GEM_ROUND:
        gems = _grant_gems(st, min(3, score - MG_GEM_ROUND + 1), now)
        if gems:
            extra.append('+%d💎' % gems)
    return coins, xp, stat, extra


def _grant_gems(st: PetState, want: int, now: int) -> int:
    """Simon gems with a per-UTC-day cap; the counter lives in cooldowns so it
    expires together with the other rate-limit keys."""
    day = now // 86400
    if st.cooldowns.get('gday') != day:
        st.cooldowns['gday'] = day
        st.cooldowns['gcnt'] = 0
    have = st.cooldowns.get('gcnt', 0)
    gems = max(0, min(want, MG_GEMS_DAILY_CAP - have))
    if gems:
        st.gems += gems
        st.cooldowns['gcnt'] = have + gems
    return gems


def _daily_reset(st: PetState, now: int) -> None:
    day = day_of(now)
    if st.mg_day != day:
        st.mg_day = day
        st.mg_coins = 0
        st.mg_games = 0


def games_meta() -> list:
    """Game catalog for the Mini App (delivered via /api/state meta)."""
    return [{'id': gid, 'title': g['title'], 'desc': g['desc'], 'stat': g['stat'],
             'score_cap': MG_SCORE_CAPS.get(gid, 0)}
            for gid, g in MG_GAMES.items()]
