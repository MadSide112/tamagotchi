"""Chests, promo codes, species switching and the promo_used table."""
import asyncio
import random
import tempfile
import unittest

from game import engine
from game.cases import CASES, apply_drop, roll, ui_meta
from game.pets import SPECIES
from game.promo import normalize
from game.state import PetState
from storage.db import Db

T0 = 1_700_000_000


def baby(now=T0):
    st = PetState.create('Пуся', now, start_coins=30)
    st.stage = 1
    return st


class TestPromo(unittest.TestCase):
    def test_coins200(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'promo', 'COINS200', T0)
        self.assertTrue(changed)
        self.assertEqual(st.coins, 230)
        self.assertIn('Промокод активирован', msg)

    def test_snowpet_grants_and_equips(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'promo', 'SNOWPET', T0)
        self.assertTrue(changed)
        self.assertIn('snow_leopard', st.pets)
        self.assertEqual(st.species, 'snow_leopard')

    def test_unknown_code(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'promo', 'NOPE', T0)
        self.assertFalse(changed)
        self.assertEqual(st.coins, 30)
        self.assertEqual(st.pets, ['cat'])

    def test_lowercase_via_normalize(self):
        st = baby()
        st, _, changed = engine.apply(st, 'promo', ' coins200 ', T0)
        self.assertTrue(changed)
        self.assertEqual(st.coins, 230)

    def test_dupe_pet_pays_coins_keeps_species(self):
        st = baby()
        st.pets.append('snow_leopard')
        st, msg, changed = engine.apply(st, 'promo', 'SNOWPET', T0)
        self.assertTrue(changed)
        self.assertEqual(st.coins, 180)  # 30 + dupe_coins 150
        self.assertEqual(st.species, 'cat')  # auto-equip only on new grant
        self.assertIn('компенсация', msg)

    def test_normalize(self):
        self.assertEqual(normalize(' snowpet '), 'SNOWPET')
        self.assertEqual(len(normalize('x' * 100)), 24)


class TestCases(unittest.TestCase):
    def test_roll_returns_valid_drop(self):
        for cid, case in CASES.items():
            random.seed(1)
            for _ in range(200):
                drop = roll(case)
                core = {k: v for k, v in drop.items() if k != 'amount'}
                self.assertIn(core, case['drops'])
                if drop['kind'] == 'coins':
                    self.assertTrue(drop['min'] <= drop['amount'] <= drop['max'])

    def test_apply_coins(self):
        st = baby()
        msg = apply_drop(st, {'kind': 'coins', 'amount': 25})
        self.assertEqual(st.coins, 55)
        self.assertIn('+25', msg)

    def test_apply_item(self):
        st = baby()
        apply_drop(st, {'kind': 'item', 'id': 'apple', 'qty': 2})
        self.assertEqual(st.inv.get('apple'), 2)

    def test_apply_acc_new_and_dupe(self):
        st = baby()
        apply_drop(st, {'kind': 'acc', 'id': 'bow'})
        self.assertIn('bow', st.acc)
        apply_drop(st, {'kind': 'acc', 'id': 'crown', 'dupe_coins': 100})
        self.assertIn('crown', st.acc)
        msg = apply_drop(st, {'kind': 'acc', 'id': 'crown', 'dupe_coins': 100})
        self.assertEqual(st.coins, 130)  # 30 + dupe_coins 100
        self.assertIn('компенсация', msg)

    def test_apply_pet_new_and_dupe(self):
        st = baby()
        msg = apply_drop(st, {'kind': 'pet', 'id': 'dog', 'dupe_coins': 60})
        self.assertEqual(st.species, 'dog')
        self.assertIn('Новый питомец', msg)
        msg = apply_drop(st, {'kind': 'pet', 'id': 'dog', 'dupe_coins': 60})
        self.assertEqual(st.coins, 90)
        self.assertEqual(st.species, 'dog')

    def test_open_case_unknown(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'open_case', 'wooden', T0)
        self.assertFalse(changed)
        self.assertEqual(msg, 'Нет такого сундука 🤔')

    def test_open_case_insufficient_coins(self):
        st = baby()
        st.coins = 10
        st, msg, changed = engine.apply(st, 'open_case', 'simple', T0)
        self.assertFalse(changed)
        self.assertIn('Не хватает монет', msg)
        self.assertEqual(st.coins, 10)

    def test_open_case_happy(self):
        st = baby()
        st.coins = 100
        st, msg, changed = engine.apply(st, 'open_case', 'simple', T0)
        self.assertTrue(changed)
        self.assertTrue(msg.startswith('Открыл 📦 Обычный сундук'))
        # цена списана, дроп монет только добавляет
        self.assertGreaterEqual(st.coins, 50)

    def test_ui_meta(self):
        meta = ui_meta()
        self.assertEqual([m['id'] for m in meta], ['simple', 'golden'])
        for m in meta:
            self.assertTrue(m['title'] and m['price'] > 0)
            self.assertTrue(m['drops'] and all(isinstance(d, str) for d in m['drops']))


class TestSetPet(unittest.TestCase):
    def test_unknown(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'setpet', 'dragon', T0)
        self.assertFalse(changed)
        self.assertEqual(msg, 'Нет такого питомца 🤔')

    def test_not_owned(self):
        st = baby()
        st, msg, changed = engine.apply(st, 'setpet', 'fox', T0)
        self.assertFalse(changed)
        self.assertIn('разблокирован', msg)

    def test_owned_switch(self):
        st = baby()
        st.pets.append('fox')
        st, msg, changed = engine.apply(st, 'setpet', 'fox', T0)
        self.assertTrue(changed)
        self.assertEqual(st.species, 'fox')

    def test_already_active(self):
        st = baby()
        st, _, changed = engine.apply(st, 'setpet', 'cat', T0)
        self.assertFalse(changed)

    def test_actions_registry(self):
        for action in ('open_case', 'setpet', 'promo'):
            self.assertIn(action, engine.ACTIONS)


class TestStatePets(unittest.TestCase):
    def test_defaults_and_roundtrip(self):
        st = baby()
        self.assertEqual(st.species, 'cat')
        self.assertEqual(st.pets, ['cat'])
        st.pets.append('panda')
        st.species = 'panda'
        st2 = PetState.from_dict(st.to_dict())
        self.assertEqual(st2.species, 'panda')
        self.assertEqual(st2.pets, ['cat', 'panda'])

    def test_legacy_dict_without_pets(self):
        d = PetState.create('Пуся', T0).to_dict()
        d.pop('sp', None)
        d.pop('pt', None)
        st = PetState.from_dict(d)
        self.assertEqual(st.species, 'cat')
        self.assertEqual(st.pets, ['cat'])

    def test_invalid_species_falls_back(self):
        st = baby()
        d = st.to_dict()
        d['pt'] = ['cat', 'ghost']
        d['sp'] = 'ghost'
        st2 = PetState.from_dict(d)
        self.assertEqual(st2.pets, ['cat'])
        self.assertEqual(st2.species, 'cat')

    def test_all_meta_species_have_sprites(self):
        for sid, sp in SPECIES.items():
            self.assertTrue(sp['title'] and sp['img'])

    def test_where_flags(self):
        # 'where' определяет вид неоткрытой карточки: chest — замок,
        # promo — карточка скрыта целиком (webapp renderPets).
        self.assertEqual(SPECIES['snow_leopard'].get('where'), 'promo')
        chest = [sid for sid, sp in SPECIES.items() if sp.get('where') == 'chest']
        self.assertEqual(sorted(chest),
                         sorted(['dog', 'bunny', 'hamster', 'fox', 'duck', 'panda']))


class TestDbPromo(unittest.IsolatedAsyncioTestCase):
    async def test_single_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Db(tmp + '/pets.db')
            self.assertFalse(await db.promo_redeemed(1, 'COINS200'))
            await db.promo_mark(1, 'COINS200', T0)
            self.assertTrue(await db.promo_redeemed(1, 'COINS200'))
            # другой пользователь не затронут
            self.assertFalse(await db.promo_redeemed(2, 'COINS200'))
            # повторный mark идемпотентен (INSERT OR IGNORE)
            await db.promo_mark(1, 'COINS200', T0 + 5)


if __name__ == '__main__':
    unittest.main()
