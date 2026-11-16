import time
import unittest
from unittest import mock

from game import engine
from game.state import PetState

T0 = 1_700_000_000
HOUR = 3600
DAY = 86400


def baby(now=T0):
    st = PetState.create('Пуся', now, start_coins=30, start_inv={'apple': 3})
    st.stage = 1
    st.satiety = 100.0
    st.mood = 100.0
    st.energy = 100.0
    st.hygiene = 100.0
    return st


class TestTick(unittest.TestCase):
    def test_egg_does_not_decay(self):
        st = PetState.create('Пуся', T0)
        engine.tick(st, T0 + HOUR)
        self.assertEqual(st.satiety, 60.0)
        self.assertEqual(st.mood, 60.0)

    def test_hour_of_decay(self):
        st = baby()
        engine.tick(st, T0 + HOUR)
        self.assertAlmostEqual(st.satiety, 94.0)
        self.assertAlmostEqual(st.mood, 96.0)
        self.assertAlmostEqual(st.energy, 96.0)
        self.assertAlmostEqual(st.hygiene, 96.0)

    def test_sleep_regen_and_faster_hunger_and_coins(self):
        st = baby()
        st.sleeping = True
        st.energy = 50.0
        engine.tick(st, T0 + HOUR)
        self.assertAlmostEqual(st.energy, 60.0)
        self.assertAlmostEqual(st.satiety, 91.0)
        self.assertAlmostEqual(st.coins, 33.0)  # 30 + 3/h sleep income

    def test_low_satiety_speeds_mood_decay(self):
        st = baby()
        st.satiety = 20.0
        engine.tick(st, T0 + HOUR)
        self.assertAlmostEqual(st.mood, 92.0)

    def test_offline_decay_is_capped(self):
        st = baby(now=0)
        engine.tick(st, 100 * 24 * HOUR)
        self.assertEqual(st.satiety, 0.0)

    def test_care_miss_on_satiety_hitting_zero(self):
        st = baby()
        st.satiety = 1.0
        events = engine.tick(st, T0 + HOUR)  # 1 - 6 < 0 -> zero, one miss
        self.assertEqual(st.care_miss, 1)
        self.assertIn('neglect', events)
        engine.tick(st, T0 + 2 * HOUR)  # still zero, no second miss
        self.assertEqual(st.care_miss, 1)

    def test_stage_progression_teen(self):
        st = baby(now=0)
        events = engine.tick(st, int(4 * DAY))
        self.assertEqual(st.stage, 2)
        self.assertIn('teen', events)

    def test_adult_branch_wise(self):
        st = baby(now=0)
        # first tick eats the capped offline budget (48h), which zeroes stats;
        # restore them so the branch decision sees clean care history
        engine.tick(st, int(8 * DAY) - HOUR)
        st.stage = 2
        st.satiety = st.mood = st.energy = st.hygiene = 100.0
        st.care_miss = 0
        st.care_score = 5
        events = engine.tick(st, int(8 * DAY))
        self.assertEqual(st.stage, 3)
        self.assertIn('adult', events)

    def test_adult_branch_beauty_and_hooligan(self):
        st = baby(now=0)
        engine.tick(st, int(8 * DAY) - HOUR)
        st.stage = 2
        st.satiety = st.mood = st.energy = st.hygiene = 100.0
        st.care_miss = 2
        st.care_score = 6  # 6 >= 3*2 -> beauty
        engine.tick(st, int(8 * DAY))
        self.assertEqual(st.stage, 4)
        st2 = baby(now=0)
        engine.tick(st2, int(8 * DAY) - HOUR)
        st2.stage = 2
        st2.satiety = st2.mood = st2.energy = st2.hygiene = 100.0
        st2.care_miss = 3
        st2.care_score = 2  # 2 < 9 -> hooligan
        engine.tick(st2, int(8 * DAY))
        self.assertEqual(st2.stage, 5)

    def test_sickness_roll_and_auto_heal(self):
        st = baby()
        st.hygiene = 10.0
        with mock.patch.object(engine.random, 'random', lambda: 0.0):
            events = engine.tick(st, T0 + HOUR)
        self.assertTrue(st.sick)
        self.assertIn('sick', events)
        # auto-heal after 24h adds exactly one care miss; the 25h decay window
        # legitimately zeroes satiety (100-6*25<0) and hygiene (100-4*25<=0),
        # adding two more misses -> 3 total
        st.sick_since = T0 + HOUR
        st.satiety = st.hygiene = st.mood = st.energy = 100.0
        events = engine.tick(st, T0 + HOUR + int(25 * 3600))
        self.assertFalse(st.sick)
        self.assertEqual(st.care_miss, 3)
        self.assertIn('healed_auto', events)


class TestStreak(unittest.TestCase):
    def test_first_day_counts_and_rewards(self):
        st = baby()
        bonus = engine.update_streak(st, T0)
        self.assertEqual(st.streak, 1)
        self.assertEqual(bonus, 10)

    def test_same_day_counted_once(self):
        st = baby()
        engine.update_streak(st, T0)
        self.assertEqual(engine.update_streak(st, T0 + HOUR), 0)

    def test_consecutive_and_gap(self):
        st = baby()
        engine.update_streak(st, T0)
        bonus = engine.update_streak(st, T0 + DAY)
        self.assertEqual(st.streak, 2)
        self.assertEqual(bonus, 15)
        # gap of 3 days resets
        bonus = engine.update_streak(st, T0 + 5 * DAY)
        self.assertEqual(st.streak, 1)
        self.assertEqual(bonus, 10)

    def test_bonus_capped(self):
        base = 1699920000  # 2023-11-14T00:00:00Z, day-aligned so dates stay consecutive
        st = baby()
        engine.update_streak(st, base + 3600)
        for d in range(2, 15):
            bonus = engine.update_streak(st, base + (d - 1) * DAY + 3600)
        self.assertEqual(st.streak, 14)
        self.assertEqual(bonus, 10 + 5 * 10)  # capped at 10-day step


class TestApply(unittest.TestCase):
    def test_feed_hatches_egg(self):
        st = PetState.create('Пуся', T0)
        st, msg, changed = engine.apply(st, 'feed', '', T0 + 5)
        self.assertTrue(changed)
        self.assertEqual(st.stage, 1)
        self.assertIn('вылупился', msg)

    def test_feed_uses_best_food_first(self):
        st = baby()
        st.inv = {'apple': 2, 'cake': 1}
        st.satiety = 50.0
        st, msg, changed = engine.apply(st, 'feed', '', T0)
        self.assertTrue(changed)
        self.assertAlmostEqual(st.satiety, 90.0)  # cake: +40
        self.assertEqual(st.inv, {'apple': 2, 'cake': 0})

    def test_feed_specific_item(self):
        st = baby()
        st.inv = {'apple': 1, 'fish': 1}
        st.satiety = 50.0
        st.energy = 50.0
        st, msg, changed = engine.apply(st, 'feed', 'fish', T0)
        self.assertTrue(changed)
        self.assertAlmostEqual(st.satiety, 80.0)
        self.assertAlmostEqual(st.energy, 55.0)
        self.assertEqual(st.inv['fish'], 0)
        self.assertEqual(st.inv['apple'], 1)

    def test_feed_missing_item_rejected(self):
        st = baby()
        st.satiety = 50.0
        st, msg, changed = engine.apply(st, 'feed', 'cake', T0)
        self.assertFalse(changed)
        self.assertAlmostEqual(st.satiety, 50.0)

    def test_scavenge_when_empty(self):
        st = baby()
        st.inv = {}
        st.satiety = 50.0
        st, msg, changed = engine.apply(st, 'feed', '', T0)
        self.assertTrue(changed)
        self.assertAlmostEqual(st.satiety, 60.0)  # scavenge +10

    def test_scavenge_cooldown(self):
        st = baby()
        st.inv = {}
        st.satiety = 50.0
        st, msg, changed = engine.apply(st, 'feed', '', T0)
        self.assertTrue(changed)
        st2, msg2, changed2 = engine.apply(st, 'feed', '', T0 + 60)
        self.assertFalse(changed2)
        self.assertIn('искал еду', msg2)
        self.assertEqual(st2.cooldowns.get('scavenge'), T0)
        st3, msg3, changed3 = engine.apply(st2, 'feed', '', T0 + 181)
        self.assertTrue(changed3)
        self.assertGreater(st3.satiety, 65.0)  # ~59.7 after decay + scavenge 10

    def test_clean_cooldown_and_coins(self):
        st = baby()
        st.hygiene = 10.0
        st, msg1, changed1 = engine.apply(st, 'clean', '', T0)
        self.assertTrue(changed1)
        self.assertEqual(st.hygiene, 100.0)
        self.assertAlmostEqual(st.coins, 32.0)
        st2, msg2, changed2 = engine.apply(st, 'clean', '', T0 + 60)
        self.assertFalse(changed2)
        st3, msg3, changed3 = engine.apply(st, 'clean', '', T0 + 301)
        self.assertTrue(changed3)

    def test_heal_flow(self):
        st = baby()
        st.sick = True
        st, msg, changed = engine.apply(st, 'heal', '', T0)
        self.assertFalse(changed)  # no medicine
        st.inv['med'] = 1
        st, msg, changed = engine.apply(st, 'heal', '', T0 + 1)
        self.assertTrue(changed)
        self.assertFalse(st.sick)
        self.assertEqual(st.inv['med'], 0)

    def test_play_requires_energy(self):
        st = baby()
        st.energy = 5.0
        st, msg, changed = engine.apply(st, 'play', '', T0)
        self.assertFalse(changed)
        self.assertIn('устал', msg)

    def test_play_blocked_while_sleeping(self):
        st = baby()
        st.sleeping = True
        st, msg, changed = engine.apply(st, 'play', '', T0)
        self.assertFalse(changed)
        self.assertIn('спит', msg)

    def test_play_changes_mood_and_energy(self):
        st = baby()
        st.mood = 50.0
        st.energy = 50.0
        st, msg, changed = engine.apply(st, 'play', '', T0)
        self.assertTrue(changed)
        self.assertAlmostEqual(st.mood, 68.0)
        self.assertAlmostEqual(st.energy, 40.0)

    def test_sleep_toggle(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'sleep', '', T0)
        self.assertTrue(changed)
        self.assertTrue(st.sleeping)
        st, msg, changed = engine.apply(st, 'sleep', '', T0 + 1)
        self.assertTrue(changed)
        self.assertFalse(st.sleeping)

    def test_pet_cooldown(self):
        st = baby()
        st, msg1, changed1 = engine.apply(st, 'pet', '', T0)
        self.assertTrue(changed1)
        st, msg2, changed2 = engine.apply(st, 'pet', '', T0 + 30)
        self.assertFalse(changed2)
        self.assertIn('рано', msg2)
        st, msg3, changed3 = engine.apply(st, 'pet', '', T0 + 61)
        self.assertTrue(changed3)

    def test_unknown_action(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'hack_server', '', T0)
        self.assertFalse(changed)
        self.assertIn('Не понимаю', msg)

    def test_buy_food_deducts_coins(self):
        st = baby()
        st.coins = 30.0
        st, msg, changed = engine.apply(st, 'buy', 'fish', T0)
        self.assertTrue(changed)
        self.assertAlmostEqual(st.coins, 20.0)
        self.assertEqual(st.inv.get('fish'), 1)

    def test_buy_not_enough_coins(self):
        st = baby()
        st.coins = 4.0
        st, msg, changed = engine.apply(st, 'buy', 'cake', T0)
        self.assertFalse(changed)
        self.assertIn('Не хватает монет', msg)
        self.assertAlmostEqual(st.coins, 4.0)
        self.assertIsNone(st.inv.get('cake'))

    def test_buy_unknown_item(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'buy', 'yacht', T0)
        self.assertFalse(changed)
        self.assertIn('Нет такого товара', msg)

    def test_buy_accessory_once_and_case_insensitive(self):
        st = baby()
        st.coins = 100.0
        st, msg, changed = engine.apply(st, 'buy', 'Hat', T0)
        self.assertTrue(changed)
        self.assertIn('hat', st.acc)
        self.assertAlmostEqual(st.coins, 50.0)
        st2, msg2, changed2 = engine.apply(st, 'buy', 'hat', T0 + 1)
        self.assertFalse(changed2)
        self.assertIn('уже куплен', msg2)
        self.assertAlmostEqual(st2.coins, 50.0)  # no double charge

    def test_wear_toggle_and_off(self):
        st = baby()
        st.acc = ['hat']
        st, msg, changed = engine.apply(st, 'wear', 'hat', T0)
        self.assertTrue(changed)
        self.assertEqual(st.worn, 'hat')
        self.assertIn('Надел', msg)
        st, msg, changed = engine.apply(st, 'wear', 'hat', T0 + 1)
        self.assertTrue(changed)
        self.assertEqual(st.worn, '')
        self.assertIn('Снял', msg)
        st.acc = ['bow']
        st.worn = 'hat'
        st, msg, changed = engine.apply(st, 'wear', 'off', T0 + 2)
        self.assertTrue(changed)
        self.assertEqual(st.worn, '')

    def test_wear_not_owned(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'wear', 'crown', T0)
        self.assertFalse(changed)
        self.assertIn('Сначала купи', msg)
        self.assertEqual(st.worn, '')


class TestJson(unittest.TestCase):
    def test_roundtrip(self):
        st = baby()
        st.sleeping = True
        st.sick = True
        st.sick_since = 123
        st.last_act = 1
        st.last_act_code = 'pet'
        st.inv = {'apple': 2, 'med': 1}
        st.acc = ['hat', 'bow']
        st.worn = 'hat'
        st.streak = 4
        st.streak_day = '2026-11-14'
        st.ref_by = 42
        st.cooldowns = {'clean': 5}
        st2 = PetState.from_json(st.to_json())
        self.assertEqual(st2.to_dict(), st.to_dict())

    def test_json_fits_budgets(self):
        st = baby()
        st.inv = {k: 99 for k in ('apple', 'fish', 'cake', 'med')}
        st.acc = ['hat', 'bow', 'scarf']
        st.worn = 'hat'
        self.assertLess(len(st.to_json().encode('utf-8')), 1024)  # chat_data limit
        import json
        pub_json = json.dumps(st.public_dict(), ensure_ascii=False)
        self.assertLess(len(pub_json.encode('utf-8')), 256)  # answer payload part


class TestRename(unittest.TestCase):
    def test_rename_ok(self):
        st = baby()
        st2, msg, changed = engine.apply(st, 'rename', 'Барсик', T0)
        self.assertTrue(changed)
        self.assertEqual(st2.name, 'Барсик')

    def test_rename_exactly_15(self):
        st = baby()
        name = 'Б' * 15
        st2, msg, changed = engine.apply(st, 'rename', name, T0)
        self.assertTrue(changed)
        self.assertEqual(st2.name, name)

    def test_rename_too_long(self):
        st = baby()
        st2, msg, changed = engine.apply(st, 'rename', 'x' * 16, T0)
        self.assertFalse(changed)
        self.assertEqual(st2.name, st.name)

    def test_rename_empty(self):
        st = baby()
        st2, msg, changed = engine.apply(st, 'rename', '   ', T0)
        self.assertFalse(changed)
        self.assertEqual(st2.name, st.name)

    def test_rename_same(self):
        st = baby()
        st2, msg, changed = engine.apply(st, 'rename', st.name, T0)
        self.assertFalse(changed)

    def test_rename_collapses_whitespace(self):
        st = baby()
        st2, msg, changed = engine.apply(st, 'rename', '  Мур   зик ', T0)
        self.assertTrue(changed)
        self.assertEqual(st2.name, 'Мур зик')


if __name__ == '__main__':
    unittest.main()
