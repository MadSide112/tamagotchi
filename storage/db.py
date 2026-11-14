"""SQLite persistence: one row per user (pet state + widget message pointer).

Sync sqlite3 wrapped with asyncio.to_thread + a thread lock: the bot is a
single asyncio loop, so a single connection with a mutex is sufficient and
keeps the dependency list at just aiohttp.
"""
import asyncio
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

_ROW_KEYS = ('user_id', 'chat_id', 'message_id', 'state', 'warn_ts', 'updated_at')


class Db:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(_SCHEMA)
        self._conn.commit()
        self._lock = threading.Lock()

    def _run(self, sql: str, params: tuple = (), fetch: bool = False):
        with self._lock:
            cur = self._conn.execute(sql, params)
            row = cur.fetchone() if fetch else None
            self._conn.commit()
            return row

    async def get_pet(self, user_id: int) -> Optional[Dict[str, Any]]:
        row = await asyncio.to_thread(
            self._run,
            'SELECT user_id, chat_id, message_id, state, warn_ts, updated_at '
            'FROM pets WHERE user_id = ?',
            (user_id,),
            True,
        )
        if row is None:
            return None
        return dict(zip(_ROW_KEYS, row))

    async def save_pet(self, user_id: int, chat_id: int, message_id: Optional[int],
                       state_json: str, warn_ts: int, now: int) -> None:
        await asyncio.to_thread(
            self._run,
            'INSERT INTO pets(user_id, chat_id, message_id, state, warn_ts, updated_at) '
            'VALUES(?,?,?,?,?,?) '
            'ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id, '
            'message_id=excluded.message_id, state=excluded.state, '
            'warn_ts=excluded.warn_ts, updated_at=excluded.updated_at',
            (user_id, chat_id, message_id, state_json, warn_ts, now),
        )
