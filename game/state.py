"""Pet state model: the single source of truth mirrored into widget chat_data."""
import json
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class PetState:
    rev: int = 1            # revision, raised on every change; guards stale widget updates
    name: str = 'Пуся'
    satiety: float = 60.0   # 0..100, 100 = fully fed
    mood: float = 60.0      # 0..100
    energy: float = 60.0    # 0..100
    hygiene: float = 80.0   # 0..100, low hygiene -> sickness chance
    sleeping: bool = False
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
    streak_day: str = ''    # UTC YYYY-MM-DD of the last counted day
    ref_by: int = 0         # user id of the referrer, 0 = none

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
            'iv': self.inv,
            'ao': self.acc,
            'wn': self.worn,
            'kr': self.streak,
            'kd': self.streak_day,
            'rb': self.ref_by,
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
        return {
            'rev': self.rev,
            'name': self.name,
            'satiety': round(self.satiety),
            'mood': round(self.mood),
            'energy': round(self.energy),
            'hygiene': round(self.hygiene),
            'sleeping': self.sleeping,
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
            'cooldowns': dict(self.cooldowns),
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
        return PetState(
            rev=max(1, int_or('r', 1)),
            name=str(d.get('n', 'Пуся'))[:32],
            satiety=num('h', 60.0, 0.0, 100.0),
            mood=num('m', 60.0, 0.0, 100.0),
            energy=num('e', 60.0, 0.0, 100.0),
            hygiene=num('hy', 80.0, 0.0, 100.0),
            sleeping=bool(d.get('sl', 0)),
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
        )

    @staticmethod
    def from_json(raw: str) -> 'PetState':
        return PetState.from_dict(json.loads(raw))
