"""Pet state model: the single source of truth mirrored into widget chat_data."""
import json
from dataclasses import dataclass, field
from typing import Dict, List

from game.balance import (
    ARENA_DAILY_CAP,
    ARENA_RATING_FLOOR,
    ARENA_RATING_START,
    BT_DAILY_COIN_CAP,
    BT_POTIONS_PER_BATTLE,
    BT_SKILLS,
    CLASSES,
    DUNGEON_ENEMIES,
    EXPEDITIONS,
    FRAG_NEED,
    GEAR,
    GEAR_MAX_LEVEL,
    GEAR_SLOTS,
    HIDDEN_CAP,
    LEVEL_XP_BASE,
    LEVEL_XP_STEP,
    MAX_LEVEL,
    MG_DAILY_COIN_CAP,
    ROOM,
    SPECIES_ELEMENT,
)
from game.pets import DEFAULT_SPECIES, is_species


@dataclass
class PetState:
    rev: int = 1            # revision, raised on every change; guards stale widget updates
    name: str = 'Пуся'
    satiety: float = 60.0   # 0..100, 100 = fully fed
    mood: float = 60.0      # 0..100
    energy: float = 60.0    # 0..100
    hygiene: float = 80.0   # 0..100, low hygiene -> sickness chance
    sleeping: bool = False
    auto_sleep: bool = False  # True, если сон включён автоматически (ночь 23:00–07:00)
    tz_offset: float = 0.0   # пояс пользователя (часов к востоку от UTC); запоминается с последнего визита в Mini App
    sick: bool = False
    sick_since: int = 0     # unix ts when current sickness started
    stage: int = 0          # 0 egg, 1 baby, 2 teen, 3 wise, 4 beauty, 5 hooligan
    born: int = 0           # unix ts of creation
    last_tick: int = 0      # unix ts of last engine tick
    last_act: int = 0       # unix ts of last rate-limited action (pet)
    last_act_code: str = ''
    cooldowns: Dict[str, int] = field(default_factory=dict)   # action -> unix ts
    coins: float = 0.0      # earned by sleep streaks cleaning referrals
    care_score: int = 0     # good actions, drives leaderboard and adult branch
    care_miss: int = 0      # neglected episodes, drives adult branch
    inv: Dict[str, int] = field(default_factory=dict)  # item id -> qty (food/med)
    acc: List[str] = field(default_factory=list)       # owned accessory ids
    worn: str = ''          # worn accessory id ('' = none)
    streak: int = 0         # consecutive daily-visit days
    streak_day: str = ''    # YYYY-MM-DD of the last counted day (user local day; UTC in chat)
    ref_by: int = 0         # user id of the referrer, 0 = none
    species: str = DEFAULT_SPECIES  # active look id (game.pets.SPECIES)
    pets: List[str] = field(default_factory=lambda: [DEFAULT_SPECIES])  # owned looks
    # --- Progression 2.0 ---
    xp: int = 0             # XP текущего уровня
    lv: int = 1             # уровень 1..MAX_LEVEL
    cls: str = ''           # класс взрослого (game.balance.CLASSES), '' = не присвоен
    gen: int = 1            # поколение (Зал Славы / New Game+)
    p: float = 0.0          # скрытый стат: сила (активные мини-игры)
    iq: float = 0.0         # скрытый стат: интеллект (логические мини-игры)
    ch: float = 0.0         # скрытый стат: харизма (чистота, наряды)
    gems: int = 0           # кристаллы (премиум-валюта)
    room: Dict[str, int] = field(default_factory=dict)  # апгрейд комнаты id -> уровень
    tree_pending: float = 0.0  # накопленные монеты денежного дерева
    frags: Dict[str, int] = field(default_factory=dict)  # осколки яиц id -> count
    hall: List[list] = field(default_factory=list)      # Зал Славы: [species, cls, gen]
    achv: List[str] = field(default_factory=list)       # полученные ачивки (id)
    friend_pts: int = 0     # очки дружбы (визиты к друзьям)
    mg_day: str = ''        # UTC YYYY-MM-DD последнего сброса капов мини-игр
    mg_coins: int = 0       # монеты из мини-игр за день (анти-фарм кап)
    mg_games: int = 0       # мини-игр за день
    games_total: int = 0    # мини-игр за всё время
    chests_total: int = 0   # сундуков открыто за всё время
    pending_case: str = ''  # id бесплатного сундука из ежедневной награды (ждёт открытия)
    q_day: str = ''         # день выдачи текущих квестов
    quests: List[list] = field(default_factory=list)    # [id, need, prog] x3
    q_claimed: int = 0      # награда за квесты дня уже получена
    boost_until: int = 0    # unix ts: эликсир ×2 XP активен до
    # --- Боевая система ---
    df: int = 0             # глубочайший взятый этаж подземелья
    bt: Dict = None         # активная сессия боя (None = боя нет)
    bw: int = 0             # побед в подземелье за всё время
    bd: str = ''            # UTC-день дневного капа монет из боёв
    bc: int = 0             # монеты из боёв за этот день
    ar: int = ARENA_RATING_START  # рейтинг арены
    aw: int = 0             # побед на арене
    al: int = 0             # поражений на арене
    ad: str = ''            # UTC-день дневного капа арены
    an: int = 0             # боёв на арене за этот день
    ex: Dict = None         # активная экспедиция {'i': id, 's': unix ts старта}
    ec: int = 0             # экспедиций собрано за всё время
    gi: List[str] = field(default_factory=list)       # экипировка: полученные id
    gl: Dict[str, int] = field(default_factory=dict)  # уровни предметов 1..GEAR_MAX_LEVEL
    gw: Dict[str, str] = field(default_factory=dict)  # надето: слот -> id предмета

    @staticmethod
    def create(name: str, now: int, start_coins: float = 0.0,
               start_inv: Dict[str, int] = None) -> 'PetState':
        st = PetState(name=name, born=now, last_tick=now, coins=start_coins)
        if start_inv:
            st.inv = dict(start_inv)
        return st

    def to_dict(self) -> dict:
        return {
            'r': self.rev,
            'n': self.name,
            'h': round(self.satiety),
            'm': round(self.mood),
            'e': round(self.energy),
            'hy': round(self.hygiene),
            'sl': 1 if self.sleeping else 0,
            'sk': 1 if self.sick else 0,
            'ss': self.sick_since,
            's': self.stage,
            'b': self.born,
            't': self.last_tick,
            'la': self.last_act,
            'lc': self.last_act_code,
            'cd': self.cooldowns,
            'cn': int(round(self.coins)),
            'cs': self.care_score,
            'cm': self.care_miss,
            'as': 1 if self.auto_sleep else 0,
            'tz': self.tz_offset,
            'iv': self.inv,
            'ao': self.acc,
            'wn': self.worn,
            'kr': self.streak,
            'kd': self.streak_day,
            'rb': self.ref_by,
            'sp': self.species,
            'pt': self.pets,
            'xp': self.xp,
            'lv': self.lv,
            'cl': self.cls,
            'gn': self.gen,
            'p': round(self.p),
            'iq': round(self.iq),
            'ch': round(self.ch),
            'gm': self.gems,
            'rm': self.room,
            'tp': round(self.tree_pending),
            'fg': self.frags,
            'hl': self.hall,
            'av': self.achv,
            'fp': self.friend_pts,
            'md': self.mg_day,
            'mc': self.mg_coins,
            'mn': self.mg_games,
            'gt': self.games_total,
            'ct': self.chests_total,
            'pc': self.pending_case,
            'qd': self.q_day,
            'ql': self.quests,
            'qc': self.q_claimed,
            'bu': self.boost_until,
            # --- battle system ---
            'df': self.df,
            'bt': dict(self.bt) if self.bt else None,
            'bw': self.bw,
            'bd': self.bd,
            'bc': self.bc,
            'ar': self.ar,
            'aw': self.aw,
            'al': self.al,
            'ad': self.ad,
            'an': self.an,
            'ex': dict(self.ex) if self.ex else None,
            'ec': self.ec,
            'gi': list(self.gi),
            'gl': dict(self.gl),
            'gw': dict(self.gw),
        }

    def public_dict(self) -> dict:
        # Only fields the widget renders; keeps the answerWidgetQuery payload small.
        return {
            'r': self.rev,
            'n': self.name,
            'h': round(self.satiety),
            'm': round(self.mood),
            'e': round(self.energy),
            'sl': 1 if self.sleeping else 0,
            'sk': 1 if self.sick else 0,
            's': self.stage,
            'cn': int(round(self.coins)),
            'wn': self.worn,
        }

    def web_dict(self) -> dict:
        """Full state for the authenticated Mini App API (web UI only)."""
        # Вью боя собирается здесь из таблиц balance (state не может импортировать
        # game.gear — см. circular-import правило; таблицы balance ни от кого не зависят).
        bt = self.bt
        battle = None
        if bt:
            enemy = DUNGEON_ENEMIES.get(bt.get('et', ''), DUNGEON_ENEMIES['slime'])
            skill = BT_SKILLS.get(self.cls)
            weapon = GEAR.get(self.gw.get('weapon', ''))
            battle = {
                'mode': bt.get('m', 'dungeon'),
                'floor': bt.get('ef', 1),
                'boss': bt.get('ef', 1) % 5 == 0,
                'enemy_id': bt.get('et', ''),
                'enemy_title': enemy['title'],
                'enemy_element': enemy['element'],
                'enemy_hp': bt.get('eh', 0),
                'enemy_max': bt.get('ehm', 0),
                'hp': bt.get('ph', 0),
                'max': bt.get('phm', 0),
                'turn': bt.get('tn', 0),
                'potions_left': max(0, BT_POTIONS_PER_BATTLE - bt.get('pu', 0)),
                'potions_max': BT_POTIONS_PER_BATTLE,
                'skill_cd': bt.get('sc', 0),
                'skill': None if skill is None else {
                    'id': skill['id'], 'title': skill['title'],
                    'emoji': skill['emoji'], 'desc': skill['desc']},
                'my_element': weapon.get('element') or SPECIES_ELEMENT.get(self.species, 'fire'),
            }
        return {
            'rev': self.rev,
            'name': self.name,
            'satiety': round(self.satiety),
            'mood': round(self.mood),
            'energy': round(self.energy),
            'hygiene': round(self.hygiene),
            'sleeping': self.sleeping,
            'auto_sleep': self.auto_sleep,
            'sick': self.sick,
            'stage': self.stage,
            'born': self.born,
            'coins': int(round(self.coins)),
            'care_score': self.care_score,
            'care_miss': self.care_miss,
            'streak': self.streak,
            'inv': dict(self.inv),
            'acc': list(self.acc),
            'worn': self.worn,
            'species': self.species,
            'pets': list(self.pets),
            'cooldowns': dict(self.cooldowns),
            'xp': self.xp,
            'level': self.lv,
            'xp_need': LEVEL_XP_BASE + LEVEL_XP_STEP * (self.lv - 1),
            'cls': self.cls,
            'gen': self.gen,
            'p': round(self.p),
            'iq': round(self.iq),
            'ch': round(self.ch),
            'gems': self.gems,
            'room': dict(self.room),
            'tree_pending': int(self.tree_pending),
            'frags': dict(self.frags),
            'hall': [list(h) for h in self.hall],
            'achv': list(self.achv),
            'friend_pts': self.friend_pts,
            'mg_coins': self.mg_coins,
            'mg_games': self.mg_games,
            'games_total': self.games_total,
            'chests_total': self.chests_total,
            'pending_case': self.pending_case,
            'quests': [list(q) for q in self.quests],
            'q_claimed': self.q_claimed,
            'boost_until': self.boost_until,
            # --- battle system ---
            'battle': battle,
            'dungeon_floor': self.df,
            'battle_wins': self.bw,
            'arena': {'rating': self.ar, 'wins': self.aw, 'losses': self.al,
                      'fights_today': self.an, 'daily_cap': ARENA_DAILY_CAP},
            'expedition': ({'id': self.ex['i'],
                            'title': EXPEDITIONS[self.ex['i']]['title'],
                            'ends_at': self.ex['s'] + EXPEDITIONS[self.ex['i']]['sec'],
                            'sec': EXPEDITIONS[self.ex['i']]['sec']}
                           if self.ex and self.ex.get('i') in EXPEDITIONS else None),
            'expeditions_done': self.ec,
            'gear': {'owned': list(self.gi), 'levels': dict(self.gl), 'worn': dict(self.gw)},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(',', ':'))

    @staticmethod
    def from_dict(d: dict) -> 'PetState':
        def num(key, default, lo, hi):
            v = d.get(key, default)
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = default
            return max(lo, min(hi, v))

        def int_or(key, default):
            try:
                return int(d.get(key, default))
            except (TypeError, ValueError):
                return default

        stage = int_or('s', 0)
        inv = d.get('iv') if isinstance(d.get('iv'), dict) else {}
        clean_inv: Dict[str, int] = {}
        for k, qty in inv.items():
            try:
                clean_inv[str(k)[:16]] = max(0, int(qty))
            except (TypeError, ValueError):
                continue
        acc = d.get('ao') if isinstance(d.get('ao'), list) else []
        clean_acc: List[str] = [str(a)[:16] for a in acc][:16]
        cd = d.get('cd') if isinstance(d.get('cd'), dict) else {}
        clean_cd: Dict[str, int] = {}
        for k, ts in cd.items():
            try:
                clean_cd[str(k)[:16]] = int(ts)
            except (TypeError, ValueError):
                continue
        pets_raw = d.get('pt') if isinstance(d.get('pt'), list) else []
        clean_pets: List[str] = []
        for sp in pets_raw:
            sp = str(sp)[:16]
            if is_species(sp) and sp not in clean_pets:
                clean_pets.append(sp)
        if DEFAULT_SPECIES not in clean_pets:
            clean_pets.insert(0, DEFAULT_SPECIES)
        species = str(d.get('sp', ''))[:16]
        if not (is_species(species) and species in clean_pets):
            species = DEFAULT_SPECIES

        clean_room: Dict[str, int] = {}
        for k, lvl in (d.get('rm') if isinstance(d.get('rm'), dict) else {}).items():
            k = str(k)[:12]
            if k not in ROOM:
                continue
            try:
                clean_room[k] = max(0, min(len(ROOM[k]['prices']), int(lvl)))
            except (TypeError, ValueError):
                continue
        clean_frags: Dict[str, int] = {}
        for k, cnt in (d.get('fg') if isinstance(d.get('fg'), dict) else {}).items():
            k = str(k)[:16]
            if k not in FRAG_NEED:
                continue
            try:
                clean_frags[k] = max(0, min(FRAG_NEED[k], int(cnt)))
            except (TypeError, ValueError):
                continue
        clean_hall: List[list] = []
        for entry in (d.get('hl') if isinstance(d.get('hl'), list) else []):
            if not (isinstance(entry, (list, tuple)) and len(entry) >= 3):
                continue
            h_sp, h_cl = str(entry[0])[:16], str(entry[1])[:16]
            if not is_species(h_sp) or h_cl not in CLASSES:
                continue
            try:
                clean_hall.append([h_sp, h_cl, max(1, min(99, int(entry[2])))])
            except (TypeError, ValueError):
                continue
        clean_hall = clean_hall[-10:]
        clean_achv: List[str] = []
        for a in (d.get('av') if isinstance(d.get('av'), list) else []):
            a = str(a)[:12]
            if a not in clean_achv:
                clean_achv.append(a)
        clean_achv = clean_achv[:24]
        clean_quests: List[list] = []
        for q in (d.get('ql') if isinstance(d.get('ql'), list) else []):
            if not (isinstance(q, (list, tuple)) and len(q) >= 3):
                continue
            try:
                need = max(1, min(99, int(q[1])))
                prog = max(0, min(999, int(q[2])))
            except (TypeError, ValueError):
                continue
            clean_quests.append([str(q[0])[:12], need, prog])
        clean_quests = clean_quests[:3]
        cls_in = str(d.get('cl', ''))[:16]
        if cls_in not in CLASSES:
            cls_in = ''

        # --- Боевая система: строгая валидация сессий и инвентаря gear ---
        bt_raw = d.get('bt') if isinstance(d.get('bt'), dict) else None
        clean_bt: Dict = None
        if bt_raw is not None:
            enemy_id = str(bt_raw.get('et', ''))[:16]
            if enemy_id in DUNGEON_ENEMIES:
                try:
                    clean_bt = {
                        'm': 'dungeon',
                        'ef': max(1, min(999, int(bt_raw.get('ef', 1)))),
                        'et': enemy_id,
                        'eh': max(0, min(99999, int(bt_raw.get('eh', 0)))),
                        'ehm': max(1, min(99999, int(bt_raw.get('ehm', 1)))),
                        'ph': max(0, min(99999, int(bt_raw.get('ph', 0)))),
                        'phm': max(1, min(99999, int(bt_raw.get('phm', 1)))),
                        'tn': max(0, min(999, int(bt_raw.get('tn', 0)))),
                        'pu': max(0, min(BT_POTIONS_PER_BATTLE, int(bt_raw.get('pu', 0)))),
                        'sc': max(0, min(99, int(bt_raw.get('sc', 0)))),
                        'es': 1 if bt_raw.get('es', 0) else 0,
                        'sd': str(bt_raw.get('sd', ''))[:16],
                        'ts': max(0, min(4_000_000_000, int(bt_raw.get('ts', 0)))),
                    }
                except (TypeError, ValueError):
                    clean_bt = None
        ex_raw = d.get('ex') if isinstance(d.get('ex'), dict) else None
        clean_ex: Dict = None
        if ex_raw is not None:
            ex_id = str(ex_raw.get('i', ''))[:16]
            if ex_id in EXPEDITIONS:
                try:
                    clean_ex = {'i': ex_id,
                                's': max(0, min(4_000_000_000, int(ex_raw.get('s', 0))))}
                except (TypeError, ValueError):
                    clean_ex = None
        clean_gi: List[str] = []
        for g in (d.get('gi') if isinstance(d.get('gi'), list) else []):
            g = str(g)[:16]
            if g in GEAR and g not in clean_gi:
                clean_gi.append(g)
        clean_gi = clean_gi[:16]
        clean_gl: Dict[str, int] = {}
        for k, lvl in (d.get('gl') if isinstance(d.get('gl'), dict) else {}).items():
            k = str(k)[:16]
            if k not in GEAR:
                continue
            try:
                clean_gl[k] = max(1, min(GEAR_MAX_LEVEL, int(lvl)))
            except (TypeError, ValueError):
                continue
        clean_gw: Dict[str, str] = {}
        for slot, gid in (d.get('gw') if isinstance(d.get('gw'), dict) else {}).items():
            slot, gid = str(slot)[:12], str(gid)[:16]
            if slot in GEAR_SLOTS and gid in GEAR and GEAR[gid]['slot'] == slot:
                clean_gw[slot] = gid

        return PetState(
            rev=max(1, int_or('r', 1)),
            name=str(d.get('n', 'Пуся'))[:32],
            satiety=num('h', 60.0, 0.0, 100.0),
            mood=num('m', 60.0, 0.0, 100.0),
            energy=num('e', 60.0, 0.0, 100.0),
            hygiene=num('hy', 80.0, 0.0, 100.0),
            sleeping=bool(d.get('sl', 0)),
            auto_sleep=bool(d.get('as', 0)),
            tz_offset=float(d.get('tz', 0) or 0),
            sick=bool(d.get('sk', 0)),
            sick_since=int_or('ss', 0),
            stage=max(0, min(5, stage)),
            born=int_or('b', 0),
            last_tick=int_or('t', 0),
            last_act=int_or('la', 0),
            last_act_code=str(d.get('lc', '')),
            cooldowns=clean_cd,
            coins=num('cn', 0.0, 0.0, 1e9),
            care_score=max(0, int_or('cs', 0)),
            care_miss=max(0, int_or('cm', 0)),
            inv=clean_inv,
            acc=clean_acc,
            worn=str(d.get('wn', ''))[:16],
            streak=max(0, int_or('kr', 0)),
            streak_day=str(d.get('kd', ''))[:10],
            ref_by=int_or('rb', 0),
            species=species,
            pets=clean_pets,
            xp=max(0, min(int_or('xp', 0), 10_000_000)),
            lv=max(1, min(MAX_LEVEL, int_or('lv', 1))),
            cls=cls_in,
            gen=max(1, min(99, int_or('gn', 1))),
            p=num('p', 0.0, 0.0, HIDDEN_CAP),
            iq=num('iq', 0.0, 0.0, HIDDEN_CAP),
            ch=num('ch', 0.0, 0.0, HIDDEN_CAP),
            gems=max(0, min(int_or('gm', 0), 1_000_000)),
            room=clean_room,
            tree_pending=num('tp', 0.0, 0.0, 999.0),
            frags=clean_frags,
            hall=clean_hall,
            achv=clean_achv,
            friend_pts=max(0, min(int_or('fp', 0), 1_000_000)),
            mg_day=str(d.get('md', ''))[:10],
            mg_coins=max(0, min(int_or('mc', 0), MG_DAILY_COIN_CAP)),
            mg_games=max(0, min(int_or('mn', 0), 999)),
            games_total=max(0, min(int_or('gt', 0), 1_000_000)),
            chests_total=max(0, min(int_or('ct', 0), 1_000_000)),
            pending_case=str(d.get('pc', ''))[:16],
            q_day=str(d.get('qd', ''))[:10],
            quests=clean_quests,
            q_claimed=1 if d.get('qc', 0) else 0,
            boost_until=max(0, min(int_or('bu', 0), 4_000_000_000)),
            # --- battle system ---
            df=max(0, min(999, int_or('df', 0))),
            bt=clean_bt,
            bw=max(0, min(int_or('bw', 0), 1_000_000)),
            bd=str(d.get('bd', ''))[:10],
            bc=max(0, min(int_or('bc', 0), BT_DAILY_COIN_CAP)),
            ar=max(ARENA_RATING_FLOOR, min(int_or('ar', ARENA_RATING_START), 4000)),
            aw=max(0, min(int_or('aw', 0), 1_000_000)),
            al=max(0, min(int_or('al', 0), 1_000_000)),
            ad=str(d.get('ad', ''))[:10],
            an=max(0, min(int_or('an', 0), 99)),
            ex=clean_ex,
            ec=max(0, min(int_or('ec', 0), 1_000_000)),
            gi=clean_gi,
            gl=clean_gl,
            gw=clean_gw,
        )

    @staticmethod
    def from_json(raw: str) -> 'PetState':
        return PetState.from_dict(json.loads(raw))
