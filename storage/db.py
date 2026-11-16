"""SQLite persistence: one row per user (pet state + widget message pointer).

Sync sqlite3 wrapped with asyncio.to_thread + a thread lock: the bot is a
single asyncio loop, so a single connection with a mutex is sufficient and
keeps the dependency list at just aiohttp.
"""
import asyncio
import json
import sqlite3
import threading
from typing import Any, Dict, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pets (
    user_id    INTEGER PRIMARY KEY,
    chat_id    INTEGER NOT NULL,
    message_id INTEGER,
    state      TEXT    NOT NULL,
    warn_ts    INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);
"""

_ROW_KEYS = ('user_id', 'chat_id', 'message_id', 'state', 'warn_ts', 'sick_warn', 'updated_at')


class Db:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._migrate()
        self._conn.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        cols = {r[1] for r in self._conn.execute('PRAGMA table_info(pets)')}
        if 'sick_warn' not in cols:
            self._conn.execute(
                'ALTER TABLE pets ADD COLUMN sick_warn INTEGER NOT NULL DEFAULT 0')
        # single-use promo codes (game/promo.py); CREATE в _migrate, а не в
        # _SCHEMA: execute() выполняет только один statement
        self._conn.execute(
            'CREATE TABLE IF NOT EXISTS promo_used ('
            'user_id INTEGER NOT NULL, code TEXT NOT NULL, ts INTEGER NOT NULL, '
            'PRIMARY KEY (user_id, code))')
        # глобальные счётчики активаций (лимиты max_uses у timed-промокодов)
        self._conn.execute(
            'CREATE TABLE IF NOT EXISTS promo_stats ('
            'code TEXT PRIMARY KEY, uses INTEGER NOT NULL DEFAULT 0)')

    def _run(self, sql: str, params: tuple = (), fetch: str = ''):
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = None
            if fetch == 'one':
                row = cur.fetchone()
            elif fetch == 'all':
                row = cur.fetchall()
            self._conn.commit()
            return row

    async def get_pet(self, user_id: int) -> Optional[Dict[str, Any]]:
        row = await asyncio.to_thread(
            self._run,
            'SELECT user_id, chat_id, message_id, state, warn_ts, sick_warn, updated_at '
            'FROM pets WHERE user_id = ?',
            (user_id,),
            'one',
        )
        if row is None:
            return None
        return dict(zip(_ROW_KEYS, row))

    async def save_pet(self, user_id: int, chat_id: int, message_id: Optional[int],
                       state_json: str, warn_ts: int, sick_warn: int, now: int) -> None:
        await asyncio.to_thread(
            self._run,
            'INSERT INTO pets(user_id, chat_id, message_id, state, warn_ts, sick_warn, '
            'updated_at) VALUES(?,?,?,?,?,?,?) '
            'ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id, '
            'message_id=excluded.message_id, state=excluded.state, '
            'warn_ts=excluded.warn_ts, sick_warn=excluded.sick_warn, '
            'updated_at=excluded.updated_at',
            (user_id, chat_id, message_id, state_json, warn_ts, sick_warn, now),
        )

    async def list_pets(self, limit: int = 10) -> list:
        # name/stage/care_score живут внутри state JSON, поэтому сортируем в Python
        rows = await asyncio.to_thread(
            self._run,
            'SELECT state, updated_at FROM pets',
            (),
            'all',
        )
        pets = []
        for state_json, updated_at in rows or []:
            try:
                st = json.loads(state_json)
            except (ValueError, TypeError):
                continue
            # stage 0 — яйцо: в топе попечителей ему не место
            if st.get('s', 0) == 0:
                continue
            pets.append(({
                'name': st.get('n', '???'),
                'stage': st.get('s', 0),
                'care_score': st.get('cs', 0),
            }, updated_at))
        pets.sort(key=lambda p: (-p[0]['care_score'], p[1]))
        return [p[0] for p in pets[:limit]]

    async def all_pet_ids(self) -> list:
        rows = await asyncio.to_thread(
            self._run, 'SELECT user_id FROM pets ORDER BY updated_at ASC', (), 'all')
        return [r[0] for r in rows or []]

    async def promo_redeemed(self, user_id: int, code: str) -> bool:
        row = await asyncio.to_thread(
            self._run,
            'SELECT 1 FROM promo_used WHERE user_id = ? AND code = ?',
            (user_id, code),
            'one',
        )
        return row is not None

    async def promo_mark(self, user_id: int, code: str, ts: int) -> None:
        await asyncio.to_thread(
            self._run,
            'INSERT OR IGNORE INTO promo_used(user_id, code, ts) VALUES(?,?,?)',
            (user_id, code, ts),
        )

    async def promo_uses(self, code: str) -> int:
        row = await asyncio.to_thread(
            self._query, 'SELECT uses FROM promo_stats WHERE code=?', (code,))
        return int(row[0][0]) if row else 0

    async def promo_inc(self, code: str) -> None:
        await asyncio.to_thread(
            self._run,
            'INSERT INTO promo_stats(code, uses) VALUES(?, 1) '
            'ON CONFLICT(code) DO UPDATE SET uses = uses + 1',
            (code,),
        )
