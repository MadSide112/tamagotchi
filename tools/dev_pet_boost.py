"""One-off: boost the /app_test dev pet (user 900000001) on the prod DB
so battle features can be verified in a browser. Dev-harness pet only —
real users have their own Telegram ids."""
import json
import sqlite3
import sys
import time

sys.path.insert(0, '/root/tama/repo')
from game.balance import ROOM  # noqa: E402
from game.progress import add_xp  # noqa: E402
from game.state import PetState  # noqa: E402

DB = '/root/tama/repo/data/tamagotchi.db'
UID = 900000001

db = sqlite3.connect(DB)
row = db.execute('SELECT state FROM pets WHERE user_id=?', (UID,)).fetchone()
if row is None:
    print('NO ROW for', UID)
    sys.exit(1)
st = PetState.from_json(row[0])
print('fields:', sorted(vars(st).keys()))
print('before:', json.dumps(st.to_dict(), ensure_ascii=False)[:300])


def setmax(attr, val):
    cur = getattr(st, attr, None)
    if cur is None:
        print('  skip missing attr', attr)
        return
    setattr(st, attr, max(cur, val))


st.stage = max(1, int(st.stage))
if not getattr(st, 'name', ''):
    st.name = 'Тестик'
for a, v in (('mood', 80.0), ('satiety', 80.0), ('energy', 100.0), ('hygiene', 70.0),
             ('p', 20.0), ('iq', 20.0), ('ch', 20.0), ('coins', 300), ('gems', 20)):
    setmax(a, v)
try:
    add_xp(st, 400, int(time.time()))
except Exception as e:
    print('add_xp failed:', e)
for a in ('sick', 'sleeping', 'auto_sleep'):
    if hasattr(st, a):
        setattr(st, a, False)
for a in ('bt', 'ex'):
    if hasattr(st, a):
        setattr(st, a, None)
# ВАЖНО: сдвинуть last_tick на сейчас, иначе первый sync-тик сервера списит
# часы распада от старой метки и закатит болезнь поверх буста.
st.last_tick = int(time.time())
# комната: все апгрейды на максимум — видно и оверлеи дома, и спрайты магазина
st.room = {rid: len(item['prices']) for rid, item in ROOM.items()}
db.execute('UPDATE pets SET state=? WHERE user_id=?', (st.to_json(), UID))
db.commit()
after = PetState.from_json(db.execute(
    'SELECT state FROM pets WHERE user_id=?', (UID,)).fetchone()[0])
print('after: stage=%s name=%s lv=%s mood=%s sat=%s en=%s p=%s iq=%s ch=%s coins=%s room=%s' % (
    after.stage, after.name, after.lv, after.mood, after.satiety,
    after.energy, after.p, after.iq, after.ch, after.coins, after.room))
