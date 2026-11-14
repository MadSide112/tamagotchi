"""Update routing and use cases: commands, widget queries, economy, referrals.

Server-authoritative rules implemented here:
- pet state lives in SQLite; widget chat_data is only a projection;
- the widget's action is committed only after editMessageWidgetData succeeds;
- every widget_query gets an answerWidgetQuery, even on failure;
- in groups the bot answers only commands addressed to it, mentions and replies.
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
    HUNGRY_NOTIFY_AT,
    NAME_MAX_LEN,
    REF_BONUS,
    SICK_NOTIFY_EVERY_SECONDS,
    SHOP,
    START_APPLES,
    START_COINS,
    STAGE_NAMES,
)
from game.state import PetState
from storage.db import Db

log = logging.getLogger('tg.app')

WIDGET_CAPTION = 'Твой питомец живёт здесь 🐣 Кормите, играйте и не забывайте про сон.'
HELP_TEXT = (
    'Я тамагочи-бот, питомец живёт прямо в чате 🐣\n\n'
    '/start [ref_ID] — завести питомца\n'
    '/feed [apple|fish|cake] — покормить\n'
    '/clean — помыть (+2🪙)\n'
    '/heal — вылечить (нужно 💊)\n'
    '/play, /sleep, /pet — игры, сон, ласка\n'
    '/shop — магазин · /buy <id> — купить\n'
    '/wear <id>|off — надеть аксессуар\n'
    '/name <имя> — переименовать\n'
    '/stats — статы · /top — лидерборд'
)
GROUP_HINT = 'Я тамагочи-бот 🐣 Питомец заводится в личке — напиши мне /start.'

_TEXT_ANSWER_LIMIT = 1024


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
                 bot_username: str, bot_id: int, web_app_url: str = '') -> None:
        self.api = api
        self.db = db
        self.widget_html = widget_html
        self.bot_username = bot_username
        self.bot_id = bot_id
        self.web_app_url = web_app_url
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
        private = msg['chat']['type'] == 'private'
        if kind == 'command':
            if cmd == 'start':
                await self._send_pet(user_id, chat_id, ref_arg=args)
            elif cmd == 'feed':
                await self._action(user_id, chat_id, 'feed', args.strip().lower())
            elif cmd == 'clean':
                await self._action(user_id, chat_id, 'clean')
            elif cmd == 'heal':
                await self._action(user_id, chat_id, 'heal')
            elif cmd == 'play':
                await self._action(user_id, chat_id, 'play')
            elif cmd == 'sleep':
                await self._action(user_id, chat_id, 'sleep')
            elif cmd == 'pet':
                await self._action(user_id, chat_id, 'pet')
            elif cmd == 'shop':
                await self._shop(user_id, chat_id)
            elif cmd == 'buy':
                await self._buy(user_id, chat_id, args.strip().lower())
            elif cmd == 'wear':
                await self._wear(user_id, chat_id, args.strip().lower())
            elif cmd == 'top':
                await self._top(chat_id)
            elif cmd == 'name':
                await self._rename(user_id, chat_id, args)
            elif cmd == 'stats':
                await self._stats(user_id, chat_id)
            elif cmd == 'help':
                await self.api.send_message(chat_id, HELP_TEXT)
            elif private:
                await self.api.send_message(chat_id, 'Я тамагочи-бот. Отправь /start 🐣')
            # неизвестная команда в группе — молчание
        elif kind == 'mention':
            await self.api.send_message(chat_id, GROUP_HINT)
        else:  # private_text
            st = await self._load_state(user_id)
            reply = engine.phrase(st) if st else 'Я тамагочи-бот. Отправь /start 🐣'
            await self.api.send_message(chat_id, reply)

    # --- state helpers ----------------------------------------------------

    async def _load_state(self, user_id: int) -> Optional[PetState]:
        row = await self.db.get_pet(user_id)
        if row is None:
            return None
        return PetState.from_json(row['state'])

    async def _run_action(self, user_id: int, chat_id: int, action: str,
                          arg: str = '') -> None:
        """Shared path for chat care commands: load, tick, streak, apply, save."""
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            now = int(time.time())
            st = PetState.from_json(row['state'])
            engine.tick(st, now)
            bonus = engine.update_streak(st, now)
            st, message, changed = engine.apply(st, action, arg, now)
            if changed:
                st.rev += 1
                if bonus:
                    message = '%s\n🔥 Стрик %d: +%d🪙' % (message, st.streak, bonus)
                if row['message_id']:
                    try:
                        await self.api.edit_widget_data(chat_id, row['message_id'],
                                                        st.to_json())
                    except ApiError as err:
                        log.warning('editMessageWidgetData failed: %s', err.description)
            await self.db.save_pet(user_id, chat_id, row['message_id'], st.to_json(),
                                   row['warn_ts'], row.get('sick_warn', 0), now)
            await self.api.send_message(chat_id, message)

    # kept for backward compatibility of call sites that pass an explicit action
    async def _action(self, user_id: int, chat_id: int, action: str, arg: str = '') -> None:
        await self._run_action(user_id, chat_id, action, arg)

    async def web_action(self, user_id: int, action: str, arg: str = ''):
        """Care action coming from the Mini App (authenticated via initData).

        Same pipeline as chat commands (tick, streak, apply, save, widget edit),
        but without Telegram messages: the HTTP response carries the result.
        Returns (public_state_dict, message) or (None, hint) when no pet exists.
        """
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                return None, 'Сначала заведи питомца: /start 🐣'
            now = int(time.time())
            st = PetState.from_json(row['state'])
            events = engine.tick(st, now)
            bonus = engine.update_streak(st, now)
            st, message, changed = engine.apply(st, action, arg, now)
            if changed:
                st.rev += 1
            if bonus:
                message = (message + '\n' if message else '') + \
                    '🔥 Стрик %d: +%d🪙' % (st.streak, bonus)
                changed = True
            if row['message_id'] and changed:
                try:
                    await self.api.edit_widget_data(row['chat_id'], row['message_id'],
                                                    st.to_json())
                except ApiError as err:
                    log.warning('editMessageWidgetData failed: %s', err.description)
            await self.db.save_pet(user_id, row['chat_id'], row['message_id'],
                                   st.to_json(), row['warn_ts'], row['sick_warn'], now)
            return st.public_dict(), message

    # --- /start flow --------------------------------------------------------

    async def _send_pet(self, user_id: int, chat_id: int, ref_arg: str = '') -> None:
        async with self._lock(user_id):
            now = int(time.time())
            row = await self.db.get_pet(user_id)
            ref_id = self._parse_ref(ref_arg)
            fresh = row is None
            if row:
                if row['message_id']:
                    await self.api.delete_message(chat_id, row['message_id'])
                st = PetState.from_json(row['state'])
                engine.tick(st, now)
            else:
                st = PetState.create('Пуся', now, START_COINS, {'apple': START_APPLES})
                if ref_id and ref_id != user_id and await self.db.get_pet(ref_id):
                    st.ref_by = ref_id
                    st.coins += REF_BONUS
            try:
                msg = await self.api.send_widget(chat_id, self.widget_html, st.to_json(),
                                                 WIDGET_CAPTION)
            except ApiError as err:
                log.error('sendWidget failed for chat %s: %s', chat_id, err.description)
                reply_markup = None
                if self.web_app_url:
                    reply_markup = {'inline_keyboard': [[
                        {'text': '🐣 Открыть питомца', 'web_app': {'url': self.web_app_url}}
                    ]]}
                await self.api.send_message(
                    chat_id,
                    'Питомец готов, но Telegram пока не пускает обычных ботов к виджетам '
                    '(ограничение сервера с 13.11.2026, INPUT_MEDIA_WIDGET_NOT_ALLOWED).\n'
                    'Играй через кнопку ниже или командами: /feed /play /sleep /pet /clean '
                    '/shop /buy /wear /top!',
                    reply_markup=reply_markup)
                # persist the pet even without a widget: text-mode care commands
                # (feed/clean/heal/...) must work regardless of widget availability
                await self.db.save_pet(user_id, chat_id, None, st.to_json(), 0, 0, now)
                if st.ref_by and fresh:
                    await self._grant_ref(user_id, st.ref_by)
                return
            await self.api.pin_message(chat_id, msg['message_id'])
            await self.db.save_pet(user_id, chat_id, msg['message_id'], st.to_json(),
                                   0, 0, now)
            if st.ref_by and fresh:
                await self.api.send_message(
                    chat_id, '🎁 Ты пришёл по приглашению: +%d🪙 стартовый бонус!' % REF_BONUS)
                await self._grant_ref(user_id, st.ref_by)

    async def _grant_ref(self, invitee_id: int, referrer_id: int) -> None:
        row = await self.db.get_pet(referrer_id)
        if row is None:
            return
        async with self._lock(referrer_id):
            now = int(time.time())
            st = PetState.from_json(row['state'])
            st.coins += REF_BONUS
            st.rev += 1
            await self.db.save_pet(referrer_id, row['chat_id'], row['message_id'],
                                   st.to_json(), row['warn_ts'], row['sick_warn'], now)
            try:
                await self.api.send_message(
                    row['chat_id'], '🎁 По твоему приглашению завёлся питомец: +%d🪙!' % REF_BONUS)
            except ApiError as err:
                log.warning('ref notify failed: %s', err.description)

    @staticmethod
    def _parse_ref(args: str) -> int:
        args = (args or '').strip()
        if args.startswith('ref_'):
            try:
                return int(args[4:])
            except ValueError:
                return 0
        return 0

    # --- shop / inventory ---------------------------------------------------

    async def _shop(self, user_id: int, chat_id: int) -> None:
        async with self._lock(user_id):
            st = await self._load_state(user_id)
            if st is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            lines = ['🛒 Магазин — баланс: %d🪙' % int(round(st.coins)), '']
            for item_id, item in SHOP.items():
                owned = ''
                if item['kind'] == 'accessory' and item_id in st.acc:
                    owned = ' (есть)'
                lines.append('/buy %s — %s · %d🪙%s' % (item_id, item['title'],
                                                        item['price'], owned))
            lines.append('')
            inv = ', '.join('%s×%d' % (SHOP[i]['title'], q) for i, q in st.inv.items() if q > 0)
            lines.append('Инвентарь: %s' % (inv or 'пусто — /feed ищет еду сам'))
            await self.api.send_message(chat_id, '\n'.join(lines))

    async def _buy(self, user_id: int, chat_id: int, item_id: str) -> None:
        if item_id not in SHOP:
            await self.api.send_message(chat_id, 'Нет такого товара. Смотри /shop')
            return
        item = SHOP[item_id]
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            now = int(time.time())
            st = PetState.from_json(row['state'])
            if st.coins < item['price']:
                await self.api.send_message(
                    chat_id, 'Не хватает монет: нужно %d🪙, у тебя %d🪙. '
                             'Спи побольше — во сне питомец зарабатывает!' %
                             (item['price'], int(round(st.coins))))
                return
            st.coins -= item['price']
            if item['kind'] == 'accessory':
                if item_id in st.acc:
                    await self.api.send_message(chat_id, 'Этот аксессуар уже куплен — /wear %s' % item_id)
                    return
                st.acc.append(item_id)
                reply = '%s куплен! Надеть: /wear %s' % (item['title'], item_id)
            else:
                st.inv[item_id] = st.inv.get(item_id, 0) + 1
                reply = '%s в инвентаре: ×%d' % (item['title'], st.inv[item_id])
            st.rev += 1
            if row['message_id']:
                try:
                    await self.api.edit_widget_data(chat_id, row['message_id'], st.to_json())
                except ApiError as err:
                    log.warning('editMessageWidgetData failed: %s', err.description)
            await self.db.save_pet(user_id, chat_id, row['message_id'], st.to_json(),
                                   row['warn_ts'], row['sick_warn'], now)
            await self.api.send_message(chat_id, '✅ %s (−%d🪙)' % (reply, item['price']))

    async def _wear(self, user_id: int, chat_id: int, item_id: str) -> None:
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            st = PetState.from_json(row['state'])
            if item_id == 'off':
                st.worn = ''
                reply = 'Снял всё нарядное'
            elif item_id in st.acc:
                st.worn = '' if st.worn == item_id else item_id
                reply = ('Снял %s' % SHOP[item_id]['title']) if not st.worn \
                    else ('Надел %s' % SHOP[item_id]['title'])
            else:
                await self.api.send_message(chat_id, 'Сначала купи: /buy %s' % item_id)
                return
            st.rev += 1
            if row['message_id']:
                try:
                    await self.api.edit_widget_data(chat_id, row['message_id'], st.to_json())
                except ApiError as err:
                    log.warning('editMessageWidgetData failed: %s', err.description)
            await self.db.save_pet(user_id, chat_id, row['message_id'], st.to_json(),
                                   row['warn_ts'], row['sick_warn'], now)
            await self.api.send_message(chat_id, '✅ %s' % reply)

    # --- leaderboard / rename / stats ----------------------------------------

    async def _top(self, chat_id: int) -> None:
        rows = await self.db.list_pets()
        if not rows:
            await self.api.send_message(chat_id, 'Питомцев ещё нет — /start 🐣')
            return
        lines = ['🏆 Топ попечителей:']
        for i, r in enumerate(rows, 1):
            lines.append('%d. %s %s — %d pts' % (i, STAGE_NAMES[min(r['stage'], 5)],
                                                 r['name'], r['care_score']))
        await self.api.send_message(chat_id, '\n'.join(lines))

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
                                   row['warn_ts'], row['sick_warn'], now)
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
                                   row['warn_ts'], row['sick_warn'], now)
            worn = (' · ' + SHOP[st.worn]['title']) if st.worn else ''
            await self.api.send_message(chat_id, '\n'.join([
                '%s (%s%s)' % (st.name, STAGE_NAMES[st.stage], worn),
                'Сытость:    %d/100' % round(st.satiety),
                'Настроение: %d/100' % round(st.mood),
                'Энергия:    %d/100' % round(st.energy),
                'Чистота:    %d/100' % round(st.hygiene),
                '%sБолезнь: %s' % ('🤒 ' if st.sick else '',
                                   'да — /heal' if st.sick else 'нет'),
                '🪙 %d · уход %d · промахи %d · 🔥 стрик %d' % (
                    int(round(st.coins)), st.care_score, st.care_miss, st.streak),
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
            bonus = engine.update_streak(st, now)
            message = ''
            changed = False
            if action != 'sync':
                st, message, changed = engine.apply(st, action, '', now)
                if changed:
                    st.rev += 1
            if bonus:
                changed = True
                message = (message + '\n' if message else '') + \
                    '🔥 Стрик %d: +%d🪙' % (st.streak, bonus)

            state_json = st.to_json()

            warn_ts = row['warn_ts']
            sick_warn = row.get('sick_warn', 0)
            if 'hungry' in events and now - warn_ts > HUNGRY_NOTIFY_EVERY_SECONDS:
                warn_ts = now
                changed = True
            if 'sick' in events and now - sick_warn > SICK_NOTIFY_EVERY_SECONDS:
                sick_warn = now
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

            await self.db.save_pet(user_id, chat_id, message_id, state_json,
                                   warn_ts, sick_warn, now)

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
            if 'sick' in events and sick_warn == now:
                await self.api.send_message(
                    chat_id, '🤒 %s заболел! Купи лекарство: /buy med и /heal' % st.name)
            if 'adult' in events:
                await self.api.send_message(
                    chat_id, '🎉 %s повзрослел и стал %s!' % (st.name, STAGE_NAMES[st.stage]))

    async def _safe_answer(self, query_id: str, data: str) -> None:
        try:
            await self.api.answer_widget_query(query_id, data)
        except ApiError as err:
            log.warning('answerWidgetQuery failed: %s', err.description)
