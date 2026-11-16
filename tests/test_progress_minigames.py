"""Progression 2.0: XP/levels/classes, daily quests, achievements, prestige,
and server-authoritative minigames with anti-cheat."""
import unittest

from game import engine, minigames, progress
from game.balance import (
    MAX_LEVEL,
    MG_DAILY_COIN_CAP,
    MG_ENERGY_COST,
    MG_GAMES_DAILY_CAP,
    MG_MIN_SECONDS,
    MG_SCORE_CAPS,
    QUEST_ALL_BONUS,
    QUEST_POOL,
)
from game.progress import (
    ACHIEVEMENTS,
    add_xp,
    claim_quests,
    check_achievements,
    day_of,
    dominant_class,
    ensure_quests,
    on_action,
    progress_for,
    xp_need,
)
from game.state import PetState

T0 = 1_700_000_000  # 2023-11-14 UTC


def baby(now=T0):
    st = PetState.create('Пуся', now, start_coins=30)
    st.stage = 1
    return st


def pool_reward(qid):
    return next(q['reward'] for q in QUEST_POOL if q['id'] == qid)


def force_quests(st, ids, now=T0):
    st.quests = [[qid, next(q['need'] for q in QUEST_POOL if q['id'] == qid), 0]
                 for qid in ids]
    st.q_day = day_of(now)
    st.q_claimed = 0


class TestXp(unittest.TestCase):
    def test_xp_need_formula(self):
        self.assertEqual(xp_need(1), 60)
        self.assertEqual(xp_need(2), 86)

    def test_egg_gains_nothing(self):
        st = PetState.create('Яйцо', T0)  # stage 0
        self.assertEqual(add_xp(st, 100, T0), '')
        self.assertEqual(st.xp, 0)

    def test_level_up(self):
        st = baby()
        line = add_xp(st, 70, T0)
        self.assertEqual((st.lv, st.xp), (2, 10))
        self.assertIn('Уровень 2', line)

    def test_generation_bonus(self):
        st = baby()
        st.gen = 2
        add_xp(st, 10, T0)
        self.assertEqual(st.xp, 11)

    def test_mage_bonus_only_for_bonus_sources(self):
        st = baby()
        st.cls = 'mage'
        add_xp(st, 10, T0, bonus_source=True)
        self.assertEqual(st.xp, 12)
        st2 = baby()
        st2.cls = 'mage'
        add_xp(st2, 10, T0)
        self.assertEqual(st2.xp, 10)

    def test_level_30_caps_xp(self):
        st = baby()
        st.lv = MAX_LEVEL
        st.xp = 10
        add_xp(st, 10_000, T0)
        self.assertEqual(st.lv, MAX_LEVEL)
        self.assertLess(st.xp, xp_need(MAX_LEVEL))


class TestClasses(unittest.TestCase):
    def test_no_class_below_bar(self):
        st = baby()
        st.p = st.iq = st.ch = 19.9
        self.assertEqual(dominant_class(st), '')

    def test_warrior_mage_noble(self):
        st = baby()
        st.p, st.iq, st.ch = 25.0, 10.0, 5.0
        self.assertEqual(dominant(st=st) if False else dominant_class(st), 'warrior')
        st.p, st.iq, st.ch = 5.0, 25.0, 10.0
        self.assertEqual(dominant_class(st), 'mage')
        st.p, st.iq, st.ch = 10.0, 5.0, 25.0
        self.assertEqual(dominant_class(st), 'noble')


class TestQuests(unittest.TestCase):
    def test_ensure_deterministic_per_day(self):
        st = baby()
        ensure_quests(st, T0)
        first = [q[0] for q in st.quests]
        ensure_quests(st, T0 + 3600)
        self.assertEqual([q[0] for q in st.quests], first)
        self.assertEqual(len(st.quests), 3)

    def test_ensure_resets_next_day(self):
        st = baby()
        ensure_quests(st, T0)
        st.quests[0][2] = 99
        ensure_quests(st, T0 + 86400)
        self.assertEqual(day_of(T0 + 86400), '2023-11-15')
        self.assertTrue(all(q[2] == 0 for q in st.quests))
        self.assertEqual(st.q_claimed, 0)

    def test_on_action_counts_only_matching(self):
        st = baby()
        force_quests(st, ['feed3', 'pet5', 'clean2'])
        on_action(st, 'pet')
        self.assertEqual(st.quests[0][2], 0)
        self.assertEqual(st.quests[1][2], 1)

    def test_sleep_counts_laying_down_only(self):
        st = baby()
        force_quests(st, ['sleep1', 'feed3', 'clean2'])
        on_action(st, 'sleep')  # ещё не спит — не засчитано
        self.assertEqual(st.quests[0][2], 0)
        st.sleeping = True
        on_action(st, 'sleep')
        self.assertEqual(st.quests[0][2], 1)

    def test_claim_requires_all_done(self):
        st = baby()
        force_quests(st, ['feed3', 'pet5', 'clean2'])
        st.quests[0][2] = 3
        st, msg, changed = claim_quests(st, T0)
        self.assertFalse(changed)
        self.assertEqual(st.q_claimed, 0)

    def test_claim_happy_and_once(self):
        st = baby()
        force_quests(st, ['feed3', 'pet5', 'clean2'])
        for q in st.quests:
            q[2] = q[1]
        coins_before = st.coins
        expected = (pool_reward('feed3') + pool_reward('pet5')
                    + pool_reward('clean2') + QUEST_ALL_BONUS)
        st, msg, changed = claim_quests(st, T0)
        self.assertTrue(changed)
        self.assertEqual(st.coins, coins_before + expected)
        self.assertEqual(st.q_claimed, 1)
        st, msg, changed = claim_quests(st, T0 + 60)
        self.assertFalse(changed)

    def test_quest_flow_via_engine(self):
        st = baby()
        force_quests(st, ['feed3', 'pet5', 'clean2'])
        for i in range(3):
            st, _, changed = engine.apply(st, 'feed', '', T0 + i * 181)
            self.assertTrue(changed)
        self.assertEqual(st.quests[0][2], 3)


class TestAchievements(unittest.TestCase):
    def test_grant_once(self):
        st = baby()
        st.lv = 10
        gems_before = st.gems
        lines = check_achievements(st)
        self.assertTrue(any('Подрос' in l for l in lines))
        self.assertIn('lvl10', st.achv)
        self.assertEqual(st.gems, gems_before + 20)
        self.assertEqual(check_achievements(st), [])

    def test_progress_for_bars(self):
        st = baby()
        st.lv = 4
        bars = progress_for(st)
        self.assertEqual(bars['lvl10'], [4, 10])
        self.assertEqual({a['id'] for a in ACHIEVEMENTS}, set(bars))


class TestPrestige(unittest.TestCase):
    def test_rejects_baby(self):
        st = baby()
        st.lv = MAX_LEVEL
        st, msg, changed = engine.apply(st, 'prestige', '', T0)
        self.assertFalse(changed)
        self.assertIn('взрослый', msg)

    def test_rejects_low_level(self):
        st = baby()
        st.stage = 3
        st, msg, changed = engine.apply(st, 'prestige', '', T0)
        self.assertFalse(changed)
        self.assertIn('уровня %d' % MAX_LEVEL, msg)

    def test_prestige_resets_and_keeps_assets(self):
        st = baby()
        st.stage = 3
        st.lv = MAX_LEVEL
        st.cls = 'warrior'
        st.coins = 500
        st.gems = 7
        st.pets = ['cat']
        species_before = st.species
        st, msg, changed = engine.apply(st, 'prestige', '', T0)
        self.assertTrue(changed)
        self.assertIn('Зал Славы', msg)
        self.assertEqual(st.gen, 2)
        self.assertEqual(st.stage, 0)
        self.assertEqual(st.lv, 1)
        self.assertEqual(st.cls, '')
        self.assertEqual(st.hall, [[species_before, 'warrior', 1]])
        # +40💎 за ачивку 'Наставник' (hall1), выданную движком после престижа
        self.assertIn('hall1', st.achv)
        self.assertEqual((st.coins, st.gems, st.pets), (500, 47, ['cat']))


class TestMinigameStart(unittest.TestCase):
    def test_unknown_game(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'game_start', 'chess', T0)
        self.assertFalse(changed)

    def test_egg_and_sleep_and_energy_gates(self):
        st = PetState.create('Яйцо', T0)
        st, msg, changed = engine.apply(st, 'game_start', 'catch', T0)
        self.assertFalse(changed)
        st = baby()
        st.sleeping = True
        st, msg, changed = engine.apply(st, 'game_start', 'catch', T0)
        self.assertFalse(changed)
        st = baby()
        st.energy = 5.0
        st, msg, changed = engine.apply(st, 'game_start', 'catch', T0)
        self.assertFalse(changed)
        self.assertIn('энергии', msg)

    def test_start_records_session(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'game_start', 'catch', T0)
        self.assertTrue(changed)
        self.assertEqual(st.cooldowns.get('gs_catch'), T0)


class TestMinigameEnd(unittest.TestCase):
    def end_game(self, st, game, score, t_start=T0, t_end=None, extra=''):
        st, _, changed = engine.apply(st, 'game_start', game, t_start)
        self.assertTrue(changed)
        arg = '%s:%d%s' % (game, score, extra or (':%d' % (t_end or t_start + 1)))
        return engine.apply(st, 'game_end', arg, t_end or t_start + 1)

    def test_end_without_start(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'game_end', 'catch:50:1', T0)
        self.assertFalse(changed)

    def test_too_fast_rejected(self):
        st = baby()
        st, msg, changed = self.end_game(st, 'catch', 100, t_end=T0 + MG_MIN_SECONDS - 1)
        self.assertFalse(changed)
        self.assertIn('быстро', msg)
        self.assertEqual(st.mg_games, 0)
        # сессия потреблена — повторный end тоже мимо
        st, msg, changed = engine.apply(st, 'game_end', 'catch:50:%d' % (T0 + 30),
                                        T0 + 30)
        self.assertFalse(changed)

    def test_too_slow_rejected(self):
        st = baby()
        st, msg, changed = self.end_game(st, 'catch', 100, t_end=T0 + 331)
        self.assertFalse(changed)
        self.assertIn('истекла', msg)

    def test_malformed_result(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'game_end', 'catch:abc', T0)
        self.assertFalse(changed)

    def test_catch_rewards_and_score_cap(self):
        st = baby()
        energy_before = st.energy
        st, msg, changed = self.end_game(st, 'catch', 10_000, t_end=T0 + 30)
        self.assertTrue(changed)
        self.assertEqual(st.energy, energy_before - MG_ENERGY_COST)
        self.assertEqual(st.mg_games, 1)
        self.assertEqual(st.games_total, 1)
        # 10000 → кламп до капа 120: coins = 120//3 = 30
        self.assertIn('+30🪙', msg)
        self.assertEqual(st.mg_coins, 30)
        # сила: 120/30 = 4.0 → кап 3.0
        self.assertEqual(st.p, 3.0)

    def test_fish_perfect_bonus(self):
        st = baby()
        st, msg, changed = self.end_game(st, 'fish', 5, t_end=T0 + 20)
        self.assertTrue(changed)
        self.assertIn('идеальный заброс', msg)
        self.assertEqual(st.mg_coins, 60)

    def test_simon_gems_with_daily_cap(self):
        st = baby()
        st, msg, changed = self.end_game(st, 'simon', MG_SCORE_CAPS['simon'],
                                         t_end=T0 + 60)
        self.assertTrue(changed)
        self.assertIn('+3💎', msg)
        self.assertEqual(st.gems, 3)

    def test_daily_coin_cap_soft(self):
        st = baby()
        st.mg_day = day_of(T0)
        st.mg_coins = MG_DAILY_COIN_CAP
        st, msg, changed = self.end_game(st, 'catch', 120, t_end=T0 + 30)
        self.assertTrue(changed)
        self.assertIn('дневной кап', msg)
        self.assertEqual(st.mg_coins, MG_DAILY_COIN_CAP)

    def test_daily_games_cap(self):
        st = baby()
        st.mg_day = day_of(T0)
        st.mg_games = MG_GAMES_DAILY_CAP
        st, msg, changed = self.end_game(st, 'catch', 100, t_end=T0 + 30)
        self.assertFalse(changed)
        self.assertIn('лимит игр', msg)

    def test_warrior_coin_bonus(self):
        st = baby()
        st.cls = 'warrior'
        st, msg, changed = self.end_game(st, 'catch', 120, t_end=T0 + 30)
        self.assertTrue(changed)
        self.assertEqual(st.mg_coins, int(round(30 * 1.15)))

    def test_zone_upscale(self):
        st = baby()
        st.room = {'zone': 2}
        st, msg, changed = self.end_game(st, 'catch', 100, t_end=T0 + 30)
        self.assertTrue(changed)
        # 100 * (1 + 0.05*2) = 110 → XP = 10 + 110//15 = 17 (без зоны было бы 16)
        self.assertIn('+17 XP', msg)

    def test_reset_day(self):
        st = baby()
        st, msg, changed = self.end_game(st, 'catch', 120, t_end=T0 + 30)
        self.assertEqual(st.mg_coins, 30)
        st.mg_day = 'yesterday'  # форсируем сброс
        st, msg, changed = self.end_game(st, 'catch', 120, t_end=T0 + 80)
        self.assertEqual(st.mg_coins, 30)


class TestMeta(unittest.TestCase):
    def test_games_meta(self):
        meta = minigames.games_meta()
        self.assertEqual({m['id'] for m in meta}, {'catch', 'fish', 'simon'})
        for m in meta:
            self.assertTrue(m['title'] and m['score_cap'] > 0)
            self.assertIn(m['stat'], ('p', 'iq', 'ch'))

    def test_achv_meta(self):
        meta = progress.achv_meta()
        self.assertTrue(all(m['title'] and m['gems'] > 0 for m in meta))
        self.assertTrue(any(m['title_reward'] for m in meta))


if __name__ == '__main__':
    unittest.main()
