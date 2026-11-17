"""Боевая система: подземелье (PvE-бой), авто-бой арены, экспедиции,
экипировка, чистка полей состояния и боевые ачивки/квесты/DB-хелперы."""
import json
import random
import time
import unittest

from game import arena, battle, expeditions, gear, progress
from game.balance import (
    ARENA_DAILY_CAP,
    ARENA_ENERGY_COST,
    ARENA_MIN_LEVEL,
    ARENA_RATING_FLOOR,
    BT_DAILY_COIN_CAP,
    BT_MAX_TURNS,
    BT_POTIONS_PER_BATTLE,
    BT_SESSION_SECONDS,
    BT_SKILLS,
    DUNGEON_ENEMIES,
    ELEMENTS,
    EXPEDITIONS,
    GEAR,
    GEAR_DUPE_COINS,
    GEAR_MAX_LEVEL,
    GEAR_SLOTS,
    SPECIES_ELEMENT,
)
from game.pets import SPECIES
from game.progress import ACHIEVEMENTS, check_achievements
from game.state import PetState
from storage.db import Db

T0 = 1_700_000_000  # 2023-11-14 00:46:40 UTC
T1 = T0 + 3_600


def mk(**kw):
    st = PetState.create('Тест', T0)
    st.stage = 1
    st.energy = 100.0
    for k, v in kw.items():
        setattr(st, k, v)
    return st


def started(**kw):
    """Питомец с начатым на T1 боем (этаж df+1)."""
    st = mk(**kw)
    st, msg, changed = battle.battle_start(st, '', T1)
    assert changed, msg
    return st


def rfighter(**kw):
    base = dict(species='cat', lv=5, mood=60.0, satiety=60.0)
    base.update(kw)
    return battle.fighter(**base)


def arena_row(uid, lv=10, stage=1):
    d = PetState.create('u%d' % uid, T0).to_dict()
    d['s'] = stage
    d['lv'] = lv
    return {'user_id': uid, 'state': d}


def state_json(**kw):
    d = PetState.create('Пуся', T0).to_dict()
    d.update(kw)
    return json.dumps(d, ensure_ascii=False)


# ------------------------- 1. Сантити-чек balance -------------------------

class TestBalanceSanity(unittest.TestCase):
    def test_element_wheel_closes(self):
        for elem, meta in ELEMENTS.items():
            self.assertIn(meta['strong'], ELEMENTS,
                          'колесо замкнуто: strong-цель должна существовать')

    def test_species_element_covers_all_species(self):
        self.assertEqual(set(SPECIES_ELEMENT), set(SPECIES))

    def test_gear_slots_and_up_costs(self):
        for gid, g in GEAR.items():
            self.assertIn(g['slot'], GEAR_SLOTS)
            self.assertEqual(len(g['up_cost']), GEAR_MAX_LEVEL - 1,
                             'up_cost: по цене на каждый уровень кроме первого')

    def test_bt_skills_all_classes_with_cd(self):
        for cls in ('warrior', 'mage', 'noble'):
            self.assertIn(cls, BT_SKILLS)
            self.assertGreaterEqual(BT_SKILLS[cls]['cd'], 1)

    def test_dungeon_enemies_registry(self):
        self.assertEqual(len(DUNGEON_ENEMIES), 6)
        for e in DUNGEON_ENEMIES.values():
            self.assertTrue(e['title'])
            self.assertIn(e['element'], ELEMENTS)


# ------------------------- 2. fighter -------------------------

class TestFighter(unittest.TestCase):
    def test_max_hp_formula(self):
        # 40 + 8*1 + round(0.6*60) = 84
        f = battle.fighter(species='cat', lv=1, satiety=60.0)
        self.assertEqual(f['max'], 84)
        self.assertEqual(f['hp'], f['max'])

    def test_gear_hp_adds_into_max(self):
        plain = battle.fighter(species='cat', lv=1, satiety=60.0)
        geared = battle.fighter(species='cat', lv=1, satiety=60.0, gear={'hp': 10})
        self.assertEqual(geared['max'], plain['max'] + 10)

    def test_gear_element_overrides_species(self):
        self.assertEqual(battle.fighter(species='bunny', lv=1)['element'], 'wind')
        f = battle.fighter(species='bunny', lv=1, gear={'element': 'fire'})
        self.assertEqual(f['element'], 'fire')

    def test_crit_from_mood_capped(self):
        f = battle.fighter(species='cat', lv=1, mood=60.0)
        self.assertAlmostEqual(f['crit'], 0.05 + 0.002 * 60)
        self.assertEqual(
            battle.fighter(species='cat', lv=1, mood=1000.0)['crit'], 0.35)


# ------------------------- 3. колесо элементов -------------------------

class TestElementMult(unittest.TestCase):
    def test_strong_weak_neutral(self):
        self.assertEqual(battle.element_mult('fire', 'wind'), 1.5)
        self.assertEqual(battle.element_mult('wind', 'fire'), 0.75)
        self.assertEqual(battle.element_mult('water', 'water'), 1.0)


# ------------------------- 4. battle_start -------------------------

class TestBattleStart(unittest.TestCase):
    def test_egg_rejected(self):
        st = mk(stage=0)
        st, msg, changed = battle.battle_start(st, '', T1)
        self.assertFalse(changed)
        self.assertIsNone(st.bt)

    def test_sleeping_rejected(self):
        st = mk(sleeping=True)
        st, msg, changed = battle.battle_start(st, '', T1)
        self.assertFalse(changed)

    def test_sick_rejected(self):
        st = mk(sick=True)
        st, msg, changed = battle.battle_start(st, '', T1)
        self.assertFalse(changed)

    def test_active_battle_rejected(self):
        st = started()
        st, msg, changed = battle.battle_start(st, '', T1 + 1)
        self.assertFalse(changed)

    def test_active_expedition_rejected(self):
        st = mk()
        st.ex = {'i': 'yard', 's': T0}
        st, msg, changed = battle.battle_start(st, '', T1)
        self.assertFalse(changed)

    def test_low_energy_rejected(self):
        st = mk(energy=5.0)
        st, msg, changed = battle.battle_start(st, '', T1)
        self.assertFalse(changed)
        self.assertIn('Мало энергии', msg)

    def test_energy_charged(self):
        st = mk(energy=60.0)
        st, msg, changed = battle.battle_start(st, '', T1)
        self.assertTrue(changed)
        self.assertEqual(st.energy, 48.0)

    def test_session_keys_exact(self):
        st = started()
        self.assertEqual(
            set(st.bt.keys()),
            {'m', 'ef', 'et', 'eh', 'ehm', 'ph', 'phm', 'tn', 'pu', 'sc',
             'es', 'sd', 'ts'})

    def test_floor_arg_clamped_to_df_plus_1(self):
        st = mk(df=0)
        st, msg, changed = battle.battle_start(st, 'f99', T1)
        self.assertTrue(changed)
        self.assertEqual(st.bt['ef'], 1)

    def test_default_floor_is_df_plus_1_boss_every_5th(self):
        st = mk(df=4)
        st, msg, changed = battle.battle_start(st, '', T1)
        self.assertTrue(changed)
        self.assertEqual(st.bt['ef'], 5)
        self.assertIn('БОСС', msg)

    def test_explicit_lower_floor_allowed(self):
        st = mk(df=2)
        st, msg, changed = battle.battle_start(st, '1', T1)
        self.assertTrue(changed)
        self.assertEqual(st.bt['ef'], 1)


# ------------------------- 5. battle_move -------------------------

class TestBattleMove(unittest.TestCase):
    def test_move_without_session(self):
        st, msg, changed = battle.battle_move(mk(), 'atk', T1)
        self.assertFalse(changed)

    def test_bad_action_ignored(self):
        st = started()
        st, msg, changed = battle.battle_move(st, 'xyz', T1 + 1)
        self.assertFalse(changed)
        self.assertEqual(st.bt['tn'], 0)

    def test_determinism_between_clones(self):
        a, b = mk(), mk()
        battle.battle_start(a, '', T1)
        battle.battle_start(b, '', T1)
        for i, act in enumerate(('atk', 'def', 'atk')):
            battle.battle_move(a, act, T1 + 1 + i)
            battle.battle_move(b, act, T1 + 1 + i)
        self.assertEqual(a.bt['eh'], b.bt['eh'])
        self.assertEqual(a.bt['ph'], b.bt['ph'])
        self.assertEqual(a.bt['tn'], b.bt['tn'])
        # клон состояния (to_dict/from_dict) продолжает бой идентично
        c = PetState.from_dict(a.to_dict())
        battle.battle_move(a, 'atk', T1 + 10)
        battle.battle_move(c, 'atk', T1 + 10)
        self.assertEqual(a.bt['eh'], c.bt['eh'])
        self.assertEqual(a.bt['ph'], c.bt['ph'])

    def test_instant_win_rewards(self):
        st = started()
        st.bt['eh'] = 1
        st, msg, changed = battle.battle_move(st, 'atk', T1 + 1)
        self.assertTrue(changed)
        self.assertIsNone(st.bt)
        self.assertIn('Победа', msg)
        self.assertEqual(st.df, 1)
        self.assertEqual(st.bw, 1)
        self.assertEqual(st.coins, 10)   # 8 + 2*этаж
        self.assertEqual(st.xp, 13)      # 10 + 3*этаж
        self.assertAlmostEqual(st.mood, 63.0)

    def test_daily_coin_cap_soft(self):
        st = mk()
        st.bd = time.strftime('%Y-%m-%d', time.gmtime(T1))
        st.bc = BT_DAILY_COIN_CAP
        st, _, _ = battle.battle_start(st, '', T1)
        st.bt['eh'] = 1
        st, msg, changed = battle.battle_move(st, 'atk', T1 + 1)
        self.assertTrue(changed)
        self.assertIn('кап', msg)
        self.assertEqual(st.coins, 0)
        self.assertEqual(st.bc, BT_DAILY_COIN_CAP)
        self.assertEqual(st.xp, 13)      # XP капом не режется
        self.assertEqual(st.bw, 1)

    def test_potion_needs_med(self):
        st = started()
        st, msg, changed = battle.battle_move(st, 'potion', T1 + 1)
        self.assertFalse(changed)
        self.assertEqual(st.bt['pu'], 0)

    def test_potion_heals_and_consumes_med(self):
        st = started()
        st.inv = {'med': 2}
        st.bt['ph'] = 10
        st, msg, changed = battle.battle_move(st, 'potion', T1 + 1)
        self.assertTrue(changed)
        self.assertEqual(st.bt['pu'], 1)
        self.assertEqual(st.inv['med'], 1)
        self.assertIn('+25 HP', msg)     # round(84 * 0.3)
        self.assertGreater(st.bt['ph'], 10)

    def test_potion_limit_per_battle(self):
        st = started()
        st.inv = {'med': 5}
        st.bt['pu'] = BT_POTIONS_PER_BATTLE
        st, msg, changed = battle.battle_move(st, 'potion', T1 + 1)
        self.assertFalse(changed)
        self.assertIn('закончились', msg)
        self.assertEqual(st.inv['med'], 5)

    def test_defend_message(self):
        st = started()
        st, msg, changed = battle.battle_move(st, 'def', T1 + 1)
        self.assertTrue(changed)
        self.assertIn('Защита', msg)

    def test_warrior_skill_cooldown(self):
        st = started(cls='warrior')
        st, msg, changed = battle.battle_move(st, 'skill', T1 + 1)
        self.assertTrue(changed)
        # cd ставится в ход скилла, затем тикает в конце того же хода
        self.assertEqual(st.bt['sc'], BT_SKILLS['warrior']['cd'] - 1)
        st, msg, changed = battle.battle_move(st, 'skill', T1 + 2)
        self.assertFalse(changed)
        self.assertIn('не готов', msg)
        self.assertEqual(st.bt['tn'], 1)  # отказ не съел ход

    def test_noble_skill_stuns_enemy(self):
        st = started(cls='noble')
        st, msg, changed = battle.battle_move(st, 'skill', T1 + 1)
        self.assertTrue(changed)
        # усыпление: враг пропускает свой ход сразу после скилла
        self.assertIn('пропустил', msg)
        self.assertEqual(st.bt['es'], 0)  # ход врага уже погашен
        st, msg, changed = battle.battle_move(st, 'atk', T1 + 2)
        self.assertTrue(changed)
        self.assertIn('отвечает', msg)    # следующий ход враг бьёт снова

    def test_skill_without_class(self):
        st = started(cls='')
        st, msg, changed = battle.battle_move(st, 'skill', T1 + 1)
        self.assertFalse(changed)
        self.assertIn('нет боевого скилла', msg)
        self.assertEqual(st.bt['tn'], 0)

    def test_flee(self):
        st = started()
        st, msg, changed = battle.battle_flee(st, '', T1 + 1)
        self.assertTrue(changed)
        self.assertIsNone(st.bt)
        self.assertAlmostEqual(st.mood, 58.0)

    def test_session_expiry_forfeit(self):
        st = started()
        st, msg, changed = battle.battle_move(st, 'atk', T1 + BT_SESSION_SECONDS + 1)
        self.assertTrue(changed)
        self.assertIn('заброшен', msg)
        self.assertIsNone(st.bt)
        self.assertAlmostEqual(st.mood, 58.0)

    def test_defeat_is_retreat_no_death(self):
        st = started()
        st.bt['ph'] = 1
        st, msg, changed = battle.battle_move(st, 'atk', T1 + 1)
        self.assertTrue(changed)
        self.assertIn('Отступление', msg)
        self.assertIsNone(st.bt)
        self.assertAlmostEqual(st.mood, 55.0)  # −5
        self.assertEqual(st.df, 0)             # поражение этаж не даёт


# ------------------------- 6. авто-бой -------------------------

class TestResolveAuto(unittest.TestCase):
    def test_winner_in_sides_and_log_bounded(self):
        a = rfighter()
        b = rfighter(species='duck')
        w, log = battle.resolve_auto(a, b, 'seed-1')
        self.assertIn(w, ('a', 'b'))
        self.assertTrue(log)
        self.assertLessEqual(len(log), BT_MAX_TURNS * 2)

    def test_same_seed_same_result(self):
        a, b = rfighter(), rfighter(species='duck')
        w1, log1 = battle.resolve_auto(a, b, 'seed-1')
        w2, log2 = battle.resolve_auto(a, b, 'seed-1')
        self.assertEqual(w1, w2)
        self.assertEqual(log1, log2)

    def test_hard_hitter_wins(self):
        a = rfighter(lv=10, p=60.0)          # atk 35
        b = rfighter(lv=1, satiety=10.0)     # max 54
        w, _ = battle.resolve_auto(a, b, 'seed-3')
        self.assertEqual(w, 'a')


# ------------------------- 7. экспедиции -------------------------

class TestExpeditions(unittest.TestCase):
    def test_start_gates(self):
        st = mk(stage=0)
        _, _, changed = expeditions.expedition_start(st, 'yard', T1)
        self.assertFalse(changed)
        st = mk(sleeping=True)
        _, _, changed = expeditions.expedition_start(st, 'yard', T1)
        self.assertFalse(changed)
        st = mk(sick=True)
        _, _, changed = expeditions.expedition_start(st, 'yard', T1)
        self.assertFalse(changed)
        st = started()  # активный бой
        _, _, changed = expeditions.expedition_start(st, 'yard', T1)
        self.assertFalse(changed)
        st = mk()
        st.ex = {'i': 'yard', 's': T0}
        _, msg, changed = expeditions.expedition_start(st, 'yard', T1)
        self.assertFalse(changed)
        self.assertIn('уже идёт', msg)
        _, msg, changed = expeditions.expedition_start(mk(), 'mars', T1)
        self.assertFalse(changed)
        self.assertIn('нет', msg)

    def test_start_records_session(self):
        st = mk()
        st, msg, changed = expeditions.expedition_start(st, 'yard', T1)
        self.assertTrue(changed)
        self.assertEqual(st.ex, {'i': 'yard', 's': T1})

    def test_early_collect_rejected(self):
        st = mk()
        expeditions.expedition_start(st, 'yard', T1)
        st, msg, changed = expeditions.expedition_collect(st, '', T1 + 100)
        self.assertFalse(changed)
        self.assertIn('мин', msg)
        self.assertIsNotNone(st.ex)
        self.assertEqual(st.ec, 0)

    def test_full_collect_rewards_and_counters(self):
        st = mk()  # satiety 60, mood 60 → care 1.1
        expeditions.expedition_start(st, 'yard', T1)
        exp = EXPEDITIONS['yard']
        care = max(0.5, min(1.5, 0.5 + st.satiety / 200 + st.mood / 200))
        coins0, gems0 = st.coins, st.gems
        # дроп детерминирован: воспроизводим тот же ролл (seed born:старт)
        rng = random.Random('%s:%s' % (st.born, T1))
        drops = exp['drops']
        r = rng.uniform(0, sum(d['w'] for d in drops))
        acc, picked = 0.0, drops[-1]
        for d in drops:
            acc += d['w']
            if r < acc:
                picked = d
                break
        drop_coins = rng.randint(*picked['n']) if picked['kind'] == 'coins' else 0
        drop_gems = rng.randint(*picked['n']) if picked['kind'] == 'gem' else 0

        st, msg, changed = expeditions.expedition_collect(
            st, '', T1 + exp['sec'])
        self.assertTrue(changed)
        self.assertIn('возвращение', msg)
        self.assertAlmostEqual(st.coins,
                               coins0 + round(exp['coins'] * care) + drop_coins)
        self.assertEqual(st.gems, gems0 + drop_gems)
        self.assertEqual(st.xp, round(exp['xp'] * care))
        self.assertEqual(st.ec, 1)
        self.assertIsNone(st.ex)
        self.assertAlmostEqual(st.mood, 65.0)  # +5 за поход

    def test_collect_deterministic_for_same_start(self):
        a, b = mk(), PetState.from_dict(mk().to_dict())
        expeditions.expedition_start(a, 'yard', T1)
        expeditions.expedition_start(b, 'yard', T1)
        sec = EXPEDITIONS['yard']['sec']
        _, msg_a, _ = expeditions.expedition_collect(a, '', T1 + sec)
        _, msg_b, _ = expeditions.expedition_collect(b, '', T1 + sec)
        self.assertEqual(msg_a, msg_b)


# ------------------------- 8. арена -------------------------

class TestArena(unittest.TestCase):
    def test_pick_opponents_filters(self):
        rows = [
            arena_row(1, lv=8),            # сам — исключён
            arena_row(2, lv=10, stage=0),  # яйцо — исключено
            arena_row(3, lv=2),            # ниже окна my_lv−5
            arena_row(4, lv=21),           # выше окна my_lv+10
            arena_row(5, lv=12),
            arena_row(6, lv=6),
        ]
        picked = arena.pick_opponents(rows, 1, 10)
        self.assertEqual({p['user_id'] for p in picked}, {5, 6})

    def test_pick_opponents_respects_limit(self):
        rows = [arena_row(5, lv=12), arena_row(6, lv=6), arena_row(7, lv=10)]
        picked = arena.pick_opponents(rows, 1, 10, limit=2)
        self.assertLessEqual(len(picked), 2)
        self.assertTrue({p['user_id'] for p in picked} <= {5, 6, 7})

    def test_fight_locked_below_min_level(self):
        st = mk(lv=2)
        snap = arena.snapshot_of(mk(lv=3))
        st, msg, changed = arena.fight(st, 42, snap, T1)
        self.assertFalse(changed)
        self.assertIn('уровне', msg)
        self.assertEqual(st.energy, 100.0)

    def test_fight_charges_energy_and_counts(self):
        st = mk(lv=3)
        snap = arena.snapshot_of(mk(lv=3))
        st, msg, changed = arena.fight(st, 42, snap, T1)
        self.assertTrue(changed)
        self.assertEqual(st.energy, 100.0 - ARENA_ENERGY_COST)
        self.assertEqual(st.an, 1)
        self.assertEqual(st.ad, time.strftime('%Y-%m-%d', time.gmtime(T1)))
        self.assertEqual(st.aw + st.al, 1)

    def test_fight_daily_cap(self):
        st = mk(lv=3)
        st.ad = time.strftime('%Y-%m-%d', time.gmtime(T1))
        st.an = ARENA_DAILY_CAP
        snap = arena.snapshot_of(mk(lv=3))
        st, msg, changed = arena.fight(st, 42, snap, T1)
        self.assertFalse(changed)
        self.assertEqual(st.energy, 100.0)
        self.assertEqual(st.an, ARENA_DAILY_CAP)

    def test_rating_int_and_floored_on_loss(self):
        st = mk(lv=3, ar=105)
        opp = mk(lv=20, ar=1400, cls='warrior')
        st, msg, changed = arena.fight(st, 42, arena.snapshot_of(opp), T1)
        self.assertTrue(changed)
        self.assertIsInstance(st.ar, int)
        self.assertGreaterEqual(st.ar, ARENA_RATING_FLOOR)
        self.assertEqual(st.al, 1)  # против lv20 проигрыш гарантирован
        self.assertEqual(st.aw, 0)


# ------------------------- 9. экипировка -------------------------

class TestGear(unittest.TestCase):
    def test_bonus_empty_is_zero(self):
        self.assertEqual(gear.gear_bonus({}, {}, {}),
                         {'atk': 0, 'mag': 0, 'def': 0, 'hp': 0, 'element': ''})

    def test_buy_rusty_sword(self):
        st = mk(coins=100)
        st, msg, changed = gear.gear_buy(st, 'sword_rusty', T1)
        self.assertTrue(changed)
        self.assertIn('Куплено', msg)
        self.assertEqual(st.coins, 20)  # 100 − 80
        self.assertIn('sword_rusty', st.gi)
        self.assertEqual(st.gl['sword_rusty'], 1)

    def test_equip_sets_slot(self):
        st = mk(coins=100)
        gear.gear_buy(st, 'sword_rusty', T1)
        st, msg, changed = gear.gear_equip(st, 'sword_rusty', T1)
        self.assertTrue(changed)
        self.assertEqual(st.gw['weapon'], 'sword_rusty')

    def test_upgrade_ladder_and_max(self):
        st = mk(coins=200, gi=['sword_rusty'], gl={'sword_rusty': 1})
        st, msg, changed = gear.gear_up(st, 'sword_rusty', T1)
        self.assertTrue(changed)
        self.assertEqual((st.gl['sword_rusty'], st.coins), (2, 140))  # −60
        st, msg, changed = gear.gear_up(st, 'sword_rusty', T1 + 1)
        self.assertTrue(changed)
        self.assertEqual((st.gl['sword_rusty'], st.coins), (3, 20))   # −120
        st, msg, changed = gear.gear_up(st, 'sword_rusty', T1 + 2)
        self.assertFalse(changed)
        self.assertEqual(st.gl['sword_rusty'], 3)
        self.assertEqual(st.coins, 20)

    def test_grant_dupe_pays_coins(self):
        st = mk(coins=0, gi=['sword_rusty'], gl={'sword_rusty': 1})
        msg = gear.grant_gear(st, 'sword_rusty')
        self.assertIn('дубликат', msg)
        self.assertEqual(st.coins, GEAR_DUPE_COINS)
        self.assertEqual(st.gi.count('sword_rusty'), 1)
        self.assertEqual(gear.grant_gear(st, 'nope'), '')

    def test_bonus_leveled_stats(self):
        bonus = gear.gear_bonus(['sword_rusty'], {'sword_rusty': 2},
                                {'weapon': 'sword_rusty'})
        self.assertEqual(bonus['atk'], 6)  # round(4 * 1.5)
        self.assertEqual(bonus['element'], '')  # у ржавого клинка элемента нет
        flame = gear.gear_bonus(['sword_flame'], {'sword_flame': 1},
                                {'weapon': 'sword_flame'})
        self.assertEqual(flame['element'], 'fire')


# ------------------------- 10. state: боевые поля -------------------------

class TestStateBattleFields(unittest.TestCase):
    def build_full(self):
        st = mk()
        st.df, st.bw, st.bd, st.bc = 7, 3, '2023-11-14', 120
        st.ar, st.aw, st.al, st.ad, st.an = 1234, 4, 2, '2023-11-14', 5
        st.ec = 9
        st.gi = ['sword_rusty']
        st.gl = {'sword_rusty': 2}
        st.gw = {'weapon': 'sword_rusty'}
        st, _, changed = battle.battle_start(st, '', T1)  # валидная сессия bt
        assert changed
        st.ex = {'i': 'yard', 's': T0}
        return st

    def test_battle_fields_roundtrip(self):
        st = self.build_full()
        st2 = PetState.from_dict(st.to_dict())
        self.assertEqual(st2.df, 7)
        self.assertEqual(st2.bt, st.bt)
        self.assertEqual((st2.bw, st2.bd, st2.bc), (3, '2023-11-14', 120))
        self.assertEqual((st2.ar, st2.aw, st2.al, st2.ad, st2.an),
                         (1234, 4, 2, '2023-11-14', 5))
        self.assertEqual(st2.ex, {'i': 'yard', 's': T0})
        self.assertEqual(st2.ec, 9)
        self.assertEqual(st2.gi, ['sword_rusty'])
        self.assertEqual(st2.gl, {'sword_rusty': 2})
        self.assertEqual(st2.gw, {'weapon': 'sword_rusty'})

    def test_garbage_cleaned(self):
        d = mk().to_dict()
        d['bt'] = {'et': 'dragon', 'ef': 3}
        self.assertIsNone(PetState.from_dict(d).bt)

        d = mk().to_dict()
        d['ex'] = {'i': 'mars', 's': T0}
        self.assertIsNone(PetState.from_dict(d).ex)

        d = mk().to_dict()
        d['gi'] = ['nope', 'sword_rusty', 'nope']
        self.assertEqual(PetState.from_dict(d).gi, ['sword_rusty'])

        d = mk().to_dict()
        d['gw'] = {'weapon': 'amulet_leather'}  # амулет в слот оружия — мимо
        self.assertEqual(PetState.from_dict(d).gw, {})

        d = mk().to_dict()
        d['ar'] = 5
        self.assertEqual(PetState.from_dict(d).ar, ARENA_RATING_FLOOR)

        d = mk().to_dict()
        d['bc'] = 99999
        self.assertEqual(PetState.from_dict(d).bc, BT_DAILY_COIN_CAP)

        d = mk().to_dict()
        d['an'] = 500
        self.assertEqual(PetState.from_dict(d).an, 99)


# ------------------------- 11. ачивки и квесты -------------------------

class TestProgressBattle(unittest.TestCase):
    def test_battle_achievement_registry(self):
        amap = {a['id']: a for a in ACHIEVEMENTS}
        for aid, target, gems in (('floor5', 5, 3), ('floor15', 15, 5),
                                  ('aw25', 25, 4), ('rt1400', 1400, 5),
                                  ('exp10', 10, 3), ('gear3', 3, 3)):
            self.assertIn(aid, amap)
            self.assertEqual(amap[aid]['target'], target)
            self.assertEqual(amap[aid]['gems'], gems)

    def test_floor5_granted_once(self):
        st = mk()
        st.df = 5
        gems0 = st.gems
        lines = check_achievements(st)
        self.assertIn('floor5', st.achv)
        self.assertEqual(st.gems, gems0 + 3)
        self.assertEqual(check_achievements(st), [])  # повторно — ничего

    def test_quest_pool_battle_quests(self):
        qmap = {q['id']: q for q in progress.QUEST_POOL}
        for qid, act in (('fight3', 'battle_start'),
                         ('arena1', 'arena_fight'),
                         ('exp1', 'expedition_start')):
            self.assertIn(qid, qmap)
            self.assertEqual(qmap[qid]['act'], act)
            self.assertGreaterEqual(qmap[qid]['need'], 1)


# ------------------------- 12. db: арена и промокоды -------------------------

class TestDbBattle(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = Db(':memory:')

    async def asyncTearDown(self):
        self.db.close()

    async def test_arena_rows_excludes_self_and_eggs(self):
        await self.db.save_pet(1, 100, None, state_json(s=1, lv=5, ar=1100), 0, 0, T0)
        await self.db.save_pet(2, 100, None, state_json(s=0, lv=5, ar=1200), 0, 0, T0)
        await self.db.save_pet(3, 100, None, state_json(s=1, lv=6, ar=900), 0, 0, T0)
        rows = await self.db.arena_rows(1)
        self.assertEqual([r['user_id'] for r in rows], [3])

    async def test_arena_top_sorted_and_limited(self):
        await self.db.save_pet(1, 100, None, state_json(s=1, ar=1100), 0, 0, T0)
        await self.db.save_pet(2, 100, None, state_json(s=1, ar=1500), 0, 0, T0)
        await self.db.save_pet(3, 100, None, state_json(s=1, ar=900), 0, 0, T0)
        await self.db.save_pet(4, 100, None, state_json(s=0, ar=5000), 0, 0, T0)
        top = await self.db.arena_top(2)
        self.assertEqual([r['rating'] for r in top], [1500, 1100])
        self.assertEqual(len(top), 2)

    async def test_promo_uses(self):
        self.db._run('INSERT INTO promo_stats(code, uses) VALUES(?, ?)',
                     ('CODE', 3))
        self.assertEqual(await self.db.promo_uses('CODE'), 3)
        self.assertEqual(await self.db.promo_uses('MISSING'), 0)


if __name__ == '__main__':
    unittest.main()
