import time
import unittest

from game import engine
from game.state import PetState

T0 = 1_700_000_000
HOUR = 3600


def baby(now=T0):
    st = PetState.create('Пуся', now)
    st.stage = 1
    st.satiety = 100.0
    st.mood = 100.0
    st.energy = 100.0
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

    def test_sleep_regen_and_faster_hunger(self):
        st = baby()
        st.sleeping = True
        st.energy = 50.0
        engine.tick(st, T0 + HOUR)
        self.assertAlmostEqual(st.energy, 60.0)
        self.assertAlmostEqual(st.satiety, 91.0)

    def test_low_satiety_speeds_mood_decay(self):
        st = baby()
        st.satiety = 20.0
        engine.tick(st, T0 + HOUR)
        self.assertAlmostEqual(st.mood, 92.0)

    def test_offline_decay_is_capped(self):
        st = baby(now=0)
        engine.tick(st, 100 * 24 * HOUR)
        self.assertEqual(st.satiety, 0.0)

    def test_stage_progression(self):
        st = baby(now=0)
        events = engine.tick(st, int(4 * 24 * HOUR))
        self.assertEqual(st.stage, 2)
        self.assertIn('teen', events)
        st = baby(now=0)
        events = engine.tick(st, int(8 * 24 * HOUR))
        self.assertEqual(st.stage, 3)
        self.assertIn('adult', events)

    def test_hungry_event_fires(self):
        st = baby()
        st.satiety = 19.0
        events = engine.tick(st, T0 + HOUR)
        self.assertIn('hungry', events)


class TestApply(unittest.TestCase):
    def test_feed_hatches_egg(self):
        st = PetState.create('Пуся', T0)
        st, msg, changed = engine.apply(st, 'feed', T0 + 5)
        self.assertTrue(changed)
        self.assertEqual(st.stage, 1)
        self.assertIn('вылупился', msg)

    def test_feed_adds_satiety(self):
        st = baby()
        st.satiety = 50.0
        st, msg, changed = engine.apply(st, 'feed', T0)
        self.assertTrue(changed)
        self.assertAlmostEqual(st.satiety, 75.0)

    def test_play_requires_energy(self):
        st = baby()
        st.energy = 5.0
        st, msg, changed = engine.apply(st, 'play', T0)
        self.assertFalse(changed)
        self.assertIn('устал', msg)

    def test_play_blocked_while_sleeping(self):
        st = baby()
        st.sleeping = True
        st, msg, changed = engine.apply(st, 'play', T0)
        self.assertFalse(changed)
        self.assertIn('спит', msg)

    def test_play_changes_mood_and_energy(self):
        st = baby()
        st.mood = 50.0
        st.energy = 50.0
        st, msg, changed = engine.apply(st, 'play', T0)
        self.assertTrue(changed)
        self.assertAlmostEqual(st.mood, 68.0)
        self.assertAlmostEqual(st.energy, 40.0)

    def test_sleep_toggle(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'sleep', T0)
        self.assertTrue(changed)
        self.assertTrue(st.sleeping)
        st, msg, changed = engine.apply(st, 'sleep', T0 + 1)
        self.assertTrue(changed)
        self.assertFalse(st.sleeping)

    def test_pet_cooldown(self):
        st = baby()
        st, msg1, changed1 = engine.apply(st, 'pet', T0)
        self.assertTrue(changed1)
        st, msg2, changed2 = engine.apply(st, 'pet', T0 + 30)
        self.assertFalse(changed2)
        self.assertIn('рано', msg2)
        st, msg3, changed3 = engine.apply(st, 'pet', T0 + 61)
        self.assertTrue(changed3)

    def test_unknown_action(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'hack_server', T0)
        self.assertFalse(changed)
        self.assertIn('Не понимаю', msg)


class TestJson(unittest.TestCase):
    def test_roundtrip(self):
        st = baby()
        st.sleeping = True
        st.last_act = 1
        st.last_act_code = 'pet'
        st2 = PetState.from_json(st.to_json())
        self.assertEqual(st2.to_dict(), st.to_dict())

    def test_json_fits_budgets(self):
        st = baby()
        self.assertLess(len(st.to_json().encode('utf-8')), 1024)  # chat_data limit
        import json
        pub_json = json.dumps(st.public_dict(), ensure_ascii=False)
        self.assertLess(len(pub_json.encode('utf-8')), 256)  # answer payload part


if __name__ == '__main__':
    unittest.main()
