"""Pet state model: the single source of truth mirrored into widget chat_data."""
import json
from dataclasses import dataclass


@dataclass
class PetState:
    rev: int = 1          # revision, raised on every change; guards stale widget updates
    name: str = 'Пуся'
    satiety: float = 60.0  # 0..100, 100 = fully fed
    mood: float = 60.0     # 0..100
    energy: float = 60.0   # 0..100
    sleeping: bool = False
    stage: int = 0         # 0 egg, 1 baby, 2 teen, 3 adult
    born: int = 0          # unix ts of creation
    last_tick: int = 0     # unix ts of last engine tick
    last_act: int = 0      # unix ts of last rate-limited action (pet)
    last_act_code: str = ''

    @staticmethod
    def create(name: str, now: int) -> 'PetState':
        return PetState(name=name, born=now, last_tick=now)

    def to_dict(self) -> dict:
        return {
            'r': self.rev,
            'n': self.name,
            'h': round(self.satiety),
            'm': round(self.mood),
            'e': round(self.energy),
            'sl': 1 if self.sleeping else 0,
            's': self.stage,
            'b': self.born,
            't': self.last_tick,
            'la': self.last_act,
            'lc': self.last_act_code,
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
            's': self.stage,
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

        stage = d.get('s', 0)
        try:
            stage = int(stage)
        except (TypeError, ValueError):
            stage = 0
        return PetState(
            rev=max(1, int(d.get('r', 1))),
            name=str(d.get('n', 'Пуся'))[:32],
            satiety=num('h', 60.0, 0.0, 100.0),
            mood=num('m', 60.0, 0.0, 100.0),
            energy=num('e', 60.0, 0.0, 100.0),
            sleeping=bool(d.get('sl', 0)),
            stage=max(0, min(3, stage)),
            born=int(d.get('b', 0)),
            last_tick=int(d.get('t', 0)),
            last_act=int(d.get('la', 0)),
            last_act_code=str(d.get('lc', '')),
        )

    @staticmethod
    def from_json(raw: str) -> 'PetState':
        return PetState.from_dict(json.loads(raw))
