"""Update routing and use cases: commands, widget queries, economy, referrals.

Server-authoritative rules implemented here:
- pet state lives in SQLite; widget chat_data is only a projection;
- the widget's action is committed only after editMessageWidgetData succeeds;
- every widget_query gets an answerWidgetQuery, even on failure;
- in groups the bot answers only commands addressed to it, mentions and replies.
"""
import asyncio
import calendar
import json
import logging
import time
from typing import Dict, Optional, Tuple

from bot.api import ApiError, TelegramApi
from game import engine
from game import progress
from game.balance import (
    FRIEND_ACC,
    FRIEND_POINTS_PER_VISIT,
    FRIEND_VISIT_COOLDOWN_HOURS,
    HUNGRY_NOTIFY_EVERY_SECONDS,
    HUNGRY_NOTIFY_AT,
    MG_DAILY_COIN_CAP,
    MG_ENERGY_COST,
    NAME_MAX_LEN,
    QUEST_ALL_BONUS,
    QUEST_POOL,
    REF_BONUS,
    SICK_NOTIFY_EVERY_SECONDS,
    SHOP,
    START_APPLES,
    START_COINS,
    STAGE_NAMES,
)
from game.promo import PROMO_CODES, normalize as promo_normalize
from game.state import PetState
from storage.db import Db

log = logging.getLogger('tg.app')

WIDGET_CAPTION = 'Твой питомец живёт здесь 🐣 Кормите, играйте и не забывайте про сон.'
HELP_TEXT = (
    'Я тамагочи-бот: питомец живёт в чате и в Mini App 🐣\n\n'
    'УХОД\n'
    '/feed [apple|fish|cake] — покормить лучшей едой из инвентаря; '
    'если еды нет — питомец ищет сам (+10 сытости, раз в 3 мин)\n'
    '/clean — помыть (+2🪙)\n'
    '/play — игры: +настроение, −энергия\n'
    '/sleep — сон: энергия +10/ч и доход 3🪙/ч\n'
    '/pet — погладить (кулдаун 1 мин)\n'
    '/heal — вылечить (нужен 💊)\n\n'
    'БОЛЕЗНЬ 🤒\n'
    'Шанс заболеть растёт, если чистота ниже 25 или сытость ниже 25 — '
    'следи за ними. Лечится 💊 из /shop (/heal) или само проходит за 24 ч, '
    'но это промах ухода. Смерти нет.\n\n'
    'ЭВОЛЮЦИЯ\n'
    'Яйцо → Малыш (первое кормление) → Подросток (3 дня) → Взрослый (7 дней). '
    'Каким он станет — решает уход: без промахов — Мудрец 🎓, '
    'при хорошем уходе — Красавец ✨, запущенный — Хулиган 😈. Промахи — '
    'это нули в статах и запущенная болезнь, они не откатываются.\n\n'
    'МОНЕТЫ 🪙\n'
    'Копятся во сне (+3/ч), за мытьё (+2), за ежедневный стрик '
    '(+10 и +5 за каждый день подряд, кап +60) и за друзей (/ref).\n\n'
    'ПРОГРЕСС 2.0 🎮\n'
    'Действия дают опыт: уровни, скрытые статы (сила/ум/харизма) и класс '
    'взрослого: Воин ⚔️ +15%% монет в играх, Маг 🔮 +20%% XP, '
    'Аристократ 👑 −25%% голод.\n'
    'На 30 уровне — /prestige: питомец в Зал Славы 🏛, новое яйцо, '
    '+10%% XP навсегда за каждое поколение.\n'
    '/games — мини-игры (монеты капятся на день: %d🪙)\n'
    '/quests — 3 квеста в день, все три — бонус +%d🪙\n\n'
    'МАГАЗИН И ПРОЧЕЕ\n'
    '/shop — список товаров · /buy <id> — купить\n'
    '/wear <id>|off — надеть/снять аксессуар\n'
    '/stats — все статы · /top — лидерборд\n'
    '/ref [код] — свой код приглашения или ввод чужого\n'
    'Друзья: визиты в гости из Mini App — очки дружбы → 💍 кольцо'
    % (MG_DAILY_COIN_CAP, QUEST_ALL_BONUS)
)
GROUP_HINT = 'Я тамагочи-бот 🐣 Питомец заводится в личке — напиши мне /start.'

GAMES_TEXT = (
    '🎮 Мини-игры — по одному пальцу:\n'
    '🍎 Ловец вкусняшек: ловь еду, уворачивайся от бомб (сила)\n'
    '🎣 Тайминг-рыбалка: останови ползунок в зелёной зоне (сила)\n'
    '🧪 Алхимия памяти: повтори последовательность колб (ум и 💎)\n\n'
    'Одна игра стоит %d энергии; монеты за игры капятся на день (%d🪙).\n'
    'Играть — в Mini App во вкладке 🎮.'
    % (MG_ENERGY_COST, MG_DAILY_COIN_CAP)
)

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
            elif cmd == 'ref':
                await self._ref(user_id, chat_id, args.strip())
            elif cmd == 'name':
                await self._rename(user_id, chat_id, args)
            elif cmd == 'stats':
                await self._stats(user_id, chat_id)
            elif cmd == 'quests':
                if args.strip().lower() == 'claim':
                    await self._run_action(user_id, chat_id, 'quest_claim')
                else:
                    await self._quests(user_id, chat_id)
            elif cmd == 'games':
                await self.api.send_message(chat_id, GAMES_TEXT)
            elif cmd == 'prestige':
                await self._run_action(user_id, chat_id, 'prestige', '')
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
            if action == 'visit':
                st, message = await self._visit(user_id, st, row, arg, now)
                return st.web_dict(), message
            if action == 'promo':
                arg = promo_normalize(arg)
                if not arg:
                    return st.web_dict(), 'Введи промокод'
                if await self.db.promo_redeemed(user_id, arg):
                    return st.web_dict(), 'Этот промокод уже активирован 🙈'
                pdata = PROMO_CODES.get(arg)
                if pdata and 'active_until' in pdata:
                    deadline = calendar.timegm(
                        time.strptime(pdata['active_until'], '%Y-%m-%d')) + 86400
                    if now >= deadline:
                        return st.web_dict(), 'Срок действия этого промокода истёк.'
                if pdata and 'max_uses' in pdata:
                    if await self.db.promo_uses(arg) >= pdata['max_uses']:
                        return st.web_dict(), 'Лимит активаций этого промокода исчерпан.'
            st, message, changed = engine.apply(st, action, arg, now)
            if changed:
                st.rev += 1
                if action == 'promo':
                    await self.db.promo_mark(user_id, arg, now)
                    await self.db.promo_inc(arg)
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
            return st.web_dict(), message

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
        """Reward the referrer. Lock-free on purpose: acquiring the referrer's
        lock here could deadlock opposite-direction referrals; the lost-update
        window is a single coins increment and is acceptable."""
        row = await self.db.get_pet(referrer_id)
        if row is None:
            return
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

    async def _ref(self, user_id: int, chat_id: int, args: str) -> None:
        if not args:
            await self.api.send_message(
                chat_id,
                '🎁 Твой код: ref_%d\nПриглашение: t.me/%s?start=ref_%d\n'
                'Новый игрок получает +%d🪙 и ты получаешь +%d🪙. '
                'Чужой код можно ввести здесь: /ref ref_<id>' % (
                    user_id, self.bot_username, user_id, REF_BONUS, REF_BONUS))
            return
        code = args.lower().removeprefix('ref_')
        try:
            ref_id = int(code)
        except ValueError:
            await self.api.send_message(chat_id, 'Код выглядит так: ref_123456789')
            return
        if ref_id == user_id:
            await self.api.send_message(chat_id, 'Это твой же код 🙂')
            return
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            st = PetState.from_json(row['state'])
            if st.ref_by:
                await self.api.send_message(chat_id,
                                            'Питомец уже привязан к коду ref_%d' % st.ref_by)
                return
            if not await self.db.get_pet(ref_id):
                await self.api.send_message(chat_id,
                                            'У этого кода нет питомца — код недействителен')
                return
            now = int(time.time())
            st.ref_by = ref_id
            st.coins += REF_BONUS
            st.rev += 1
            state_json = st.to_json()
            if row['message_id']:
                try:
                    await self.api.edit_widget_data(chat_id, row['message_id'], state_json)
                except ApiError as err:
                    log.warning('editMessageWidgetData failed: %s', err.description)
            await self.db.save_pet(user_id, chat_id, row['message_id'], state_json,
                                   row['warn_ts'], row['sick_warn'], now)
            await self.api.send_message(chat_id, '🎁 Код принят: +%d🪙!' % REF_BONUS)
            await self._grant_ref(user_id, ref_id)

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
            now = int(time.time())
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

    async def _quests(self, user_id: int, chat_id: int) -> None:
        async with self._lock(user_id):
            row = await self.db.get_pet(user_id)
            if row is None:
                await self.api.send_message(chat_id, 'Сначала заведи питомца: /start 🐣')
                return
            now = int(time.time())
            st = PetState.from_json(row['state'])
            progress.ensure_quests(st, now)
            lines = ['📋 Квесты дня:']
            for qid, need, prog in st.quests:
                meta = next((q for q in QUEST_POOL if q['id'] == qid), None)
                title = meta['title'] if meta else qid
                reward = meta['reward'] if meta else 10
                done = prog >= need
                lines.append('%s %s — %d/%d (награда %d🪙)'
                             % ('✅' if done else '⬜', title, prog, need, reward))
            if st.q_claimed:
                lines.append('Награды за день уже получены ✅')
            else:
                lines.append('Забрать: /quests claim (все три → бонус +%d🪙)'
                             % QUEST_ALL_BONUS)
            await self.db.save_pet(user_id, chat_id, row['message_id'],
                                   st.to_json(), row['warn_ts'], row['sick_warn'], now)
            await self.api.send_message(chat_id, '\n'.join(lines))

    async def _visit(self, user_id: int, st: PetState, row, arg: str,
                     now: int) -> Tuple[PetState, str]:
        """Визит в гости к другу. Гость: +1 очко дружбы (кулдаун 20 ч),
        хозяину питомца +3 сытости. При 10 очках — 💍 Кольцо дружбы."""
        target_id = (arg or '').strip()
        if not target_id.isdigit():
            return st, 'Не понял, к кому в гости 🤔'
        target_id = int(target_id)
        if target_id == user_id:
            return st, 'К себе в гости не сходишь 🙂'
        frow = await self.db.get_pet(target_id)
        if not frow:
            return st, 'У этого пользователя ещё нет питомца 🐣'
        key = 'vis_%d' % target_id
        last = st.cooldowns.get(key, 0)
        if now - last < FRIEND_VISIT_COOLDOWN_HOURS * 3600:
            wait_h = int((FRIEND_VISIT_COOLDOWN_HOURS * 3600
                          - (now - last) + 3599) // 3600)
            cool_name = PetState.from_json(frow['state']).name
            return st, ('К %s ты уже приходил — следующий визит через ~%d ч.'
                        % (cool_name, wait_h))
        fst = PetState.from_json(frow['state'])
        fname = fst.name
        st.cooldowns[key] = now
        st.friend_pts = min(999, st.friend_pts + FRIEND_POINTS_PER_VISIT)
        fst.satiety = min(100.0, fst.satiety + 3.0)
        fst.rev += 1
        messages = ['🚪 Ты в гостях у %s! +1 очко дружбы.' % fname]
        for acc_id, meta in FRIEND_ACC.items():
            if acc_id in st.acc:
                continue
            if st.friend_pts >= meta['need']:
                st.acc.append(acc_id)
                messages.append('🎉 Дружба крепка: получен %s!' % meta['title'])
        messages.append('🍖 %s подкрепился в гостях (+3 сытости).' % fname)
        await self.db.save_pet(user_id, row['chat_id'], row['message_id'],
                               st.to_json(), row['warn_ts'], row['sick_warn'], now)
        await self.db.save_pet(target_id, frow['chat_id'], frow['message_id'],
                               fst.to_json(), frow['warn_ts'], frow['sick_warn'], now)
        st.rev += 1
        return st, '\n'.join(messages)

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
