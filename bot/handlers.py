"""Update routing and use cases: /start flow, widget queries, notifications.

Server-authoritative rules implemented here:
- pet state lives in SQLite; widget chat_data is only a projection;
- the widget's action is committed only after editMessageWidgetData succeeds;
- every widget_query gets an answerWidgetQuery, even on failure.
"""
import asyncio
import json
import logging
import time
from typing import Dict, Optional

from bot.api import ApiError, TelegramApi
from game import engine
from game.balance import (
    HUNGRY_NOTIFY_EVERY_SECONDS,
    NAME_MAX_LEN,
    STAGE_NAMES,
)
from game.state import PetState
from storage.db import Db

log = logging.getLogger('tg.app')

WIDGET_CAPTION = 'Твой питомец живёт здесь 🐣 Кормите, играйте и не забывайте про сон.'
HELP_TEXT = (
    'Я тамагочи-бот, питомец живёт прямо в чате 🐣\n\n'
    '/start — завести питомца\n'
    '/name <имя> — переименовать\n'
    '/stats — статы питомца\n'
    '/newpet — начать заново\n'
    '/help — эта справка'
)

_TEXT_ANSWER_LIMIT = 1024

GROUP_HINT = 'Я тамагочи-бот 🐣 Питомец заводится в личке — напиши мне /start.'


def classify(msg: dict, bot_username: str, bot_id: int):
    """Route an incoming message. Returns (kind, cmd, args).

    kind: 'ignored' | 'command' | 'private_text' | 'mention'.
    Groups: only commands addressed to this bot (plain /cmd or /cmd@me),
    mentions of @bot_username and replies to the bot's own messages count;
    everything else is ignored (the bot is usually an admin and sees all traffic).
    Private chats: every message is answered, as before.
    """
    text = (msg.get('text') or '').strip()
    if not text:
        return 'ignored', '', ''
    chat_type = msg.get('chat', {}).get('type', 'private')
    tokens = text.split(None, 1)
    first = tokens[0]
    args = tokens[1] if len(tokens) > 1 else ''

    if first.startswith('/'):
        cmd, _, target = first[1:].partition('@')
        cmd = cmd.lower()
        if target and target.lower() != bot_username.lower():
            return 'ignored', '', ''  # команда чужому боту
        return 'command', cmd, args

    mention = ('@' + bot_username.lower()) in text.lower()
    reply = msg.get('reply_to_message') or {}
    replied_to_me = (reply.get('from') or {}).get('id') == bot_id
    if chat_type != 'private':
        if mention or replied_to_me:
            return 'mention', '', text
        return 'ignored', '', text
    return 'private_text', '', text


class App:
    def __init__(self, api: TelegramApi, db: Db, widget_html: str,
                 bot_username: str, bot_id: int) -> None:
        self.api = api
        self.db = db
        self.widget_html = widget_html
        self.bot_username = bot_username
        self.bot_id = bot_id
        self._locks: Dict[int, asyncio.Lock] = {}

    def _lock(self, user_id: int) -> asyncio.Lock:
        return self._locks.setdefault(user_id, asyncio.Lock())

    async def handle_update(self, update: dict) -> None:
        if 'widget_query' in update:
            await self._on_widget_query(update['widget_query'])
        elif 'message' in update:
            await self._on_message(update['message'])

    # --- text commands ---------------------------------------------------

    async def _on_message(self, msg: dict) -> None:
        chat_id = msg['chat']['id']
        user_id = msg['from']['id']
        kind, cmd, args = classify(msg, self.bot_username, self.bot_id)
        if kind == 'ignored':
            return
        if kind == 'command':
            if cmd == 'start':
                await self._send_pet(user_id, chat_id, reset=False)
            elif cmd == 'newpet':
                await self._send_pet(user_id, chat_id, reset=True)
            elif cmd == 'name':
                await self._rename(user_id, chat_id, args)
            elif cmd == 'stats':
                await self._stats(user_id, chat_id)
            elif cmd == 'help':
                await self.api.send_message(chat_id, HELP_TEXT)
            elif msg['chat']['type'] == 'private':
                await self.api.send_message(chat_id, 'Я тамагочи-бот. Отправь /start 🐣')
            # неизвестная команда в группе — молчание
        elif kind == 'mention':
            await self.api.send_message(chat_id, GROUP_HINT)
        else:  # private_text
            await self.api.send_message(chat_id, 'Я тамагочи-бот. Отправь /start 🐣')

    async def _send_pet(self, user_id: int, chat_id: int, reset: bool) -> None:
        async with self._lock(user_id):
            now = int(time.time())
            row = await self.db.get_pet(user_id)
            if row:
                if row['message_id']:
                    await self.api.delete_message(chat_id, row['message_id'])
                if reset:
                    st = PetState.create('Пуся', now)
                else:
                    st = PetState.from_json(row['state'])
                    engine.tick(st, now)
            else:
                st = PetState.create('Пуся', now)
            try:
                msg = await self.api.send_widget(chat_id, self.widget_html, st.to_json(),
                                                 WIDGET_CAPTION)
            except ApiError as err:
                log.error('sendWidget failed for chat %s: %s', chat_id, err.description)
                await self.api.send_message(
                    chat_id,
                    'Питомец готов, но Telegram пока не пускает обычных ботов к виджетам '
                    '(ограничение сервера с 13.11.2026, INPUT_MEDIA_WIDGET_NOT_ALLOWED).\n'
                    'Виджет заработает, когда Telegram снова откроет доступ — просто '
                    'отправь /start. Игра уже живёт в этом боте, жди Открытия 🙂')
                return
            await self.api.pin_message(chat_id, msg['message_id'])
            await self.db.save_pet(user_id, chat_id, msg['message_id'], st.to_json(), 0, now)

    async def _rename(self, user_id: int, chat_id: int, name: str) -> None:
        name = (name or '').strip()
        if not name or name.startswith('/'):
            await self.api.send_message(chat_id, 'Как его назвать? Например: /name Пуся')
            return
        if len(name) > NAME_MAX_LEN:
            await self.api.send_message(chat_id, 'Имя длиннее %d символов 🤏' % NAME_MAX_LEN)
            return
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            now = int(time.time())
            st = PetState.from_json(row['state'])
            engine.tick(st, now)
            st.name = name
            st.rev += 1
            state_json = st.to_json()
            if row['message_id']:
                await self.api.edit_widget_data(chat_id, row['message_id'], state_json)
            await self.db.save_pet(user_id, chat_id, row['message_id'], state_json,
                                   row['warn_ts'], now)
            await self.api.send_message(chat_id, 'Теперь его зовут %s!' % name)

    async def _stats(self, user_id: int, chat_id: int) -> None:
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            now = int(time.time())
            st = PetState.from_json(row['state'])
            engine.tick(st, now)
            await self.db.save_pet(user_id, chat_id, row['message_id'], st.to_json(),
                                   row['warn_ts'], now)
            await self.api.send_message(chat_id, '\n'.join([
                '🐣 %s (%s)' % (st.name, STAGE_NAMES[st.stage]),
                'Сытость:    %d/100' % round(st.satiety),
                'Настроение: %d/100' % round(st.mood),
                'Энергия:    %d/100' % round(st.energy),
                'Спит: %s' % ('да 😴' if st.sleeping else 'нет'),
            ]))

    # --- widget queries ---------------------------------------------------

    async def _on_widget_query(self, query: dict) -> None:
        try:
            await self._process_widget_query(query)
        except ApiError as err:
            log.warning('widget query failed: %s', err.description)
            await self._safe_answer(query['id'], 'Ой, ошибка 😿 Попробуй ещё раз')
        except Exception:
            log.exception('widget query crashed')
            await self._safe_answer(query['id'], 'Ой, ошибка 😿 Попробуй ещё раз')

    async def _process_widget_query(self, query: dict) -> None:
        query_id = query['id']
        user_id = query['from']['id']
        action = query.get('data') or ''
        chat_id = (query.get('chat') or {}).get('id')
        message_id = query.get('message_id')

        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self._safe_answer(query_id, 'Питомец не найден. Отправь /start 🐣')
                return
            if action not in engine.ACTIONS:
                await self._safe_answer(query_id, 'Не понимаю 🤔')
                return

            now = int(time.time())
            st = PetState.from_json(row['state'])
            events = engine.tick(st, now)
            message = ''
            changed = False
            if action != 'sync':
                st, message, changed = engine.apply(st, action, now)
                if changed:
                    st.rev += 1
            state_json = st.to_json()

            warn_ts = row['warn_ts']
            if 'hungry' in events and now - warn_ts > HUNGRY_NOTIFY_EVERY_SECONDS:
                warn_ts = now
                changed = True

            if chat_id and message_id and state_json != row['state']:
                try:
                    await self.api.edit_widget_data(chat_id, message_id, state_json)
                except ApiError as err:
                    if 'not found' in err.description.lower():
                        # Widget message was deleted by the user: keep server state,
                        # drop the stale pointer. /start will send a fresh widget.
                        message_id = None
                    else:
                        log.warning('editMessageWidgetData failed: %s', err.description)
                        await self._safe_answer(query_id,
                                                'Слишком много действий, подожди минуту 🙂')
                        return

            await self.db.save_pet(user_id, chat_id, message_id, state_json, warn_ts, now)

            payload = {'s': st.public_dict()}
            if message:
                payload['m'] = message
            answer = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
            if len(answer.encode('utf-8')) > _TEXT_ANSWER_LIMIT:
                answer = json.dumps({'s': st.public_dict()}, ensure_ascii=False,
                                    separators=(',', ':'))
            await self._safe_answer(query_id, answer)

            # Side-effect notifications, after the query is answered.
            if 'hungry' in events and warn_ts == now:
                await self.api.send_message(
                    chat_id, '⚠️ %s проголодался! Загляни покормить 🍎' % st.name)
            if 'adult' in events:
                await self.api.send_message(chat_id, '🎉 %s повзрослел!' % st.name)

    async def _safe_answer(self, query_id: str, data: str) -> None:
        try:
            await self.api.answer_widget_query(query_id, data)
        except ApiError as err:
            log.warning('answerWidgetQuery failed: %s', err.description)
