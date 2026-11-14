"""Thin async Telegram Bot API client (Bot API 10.4).

Written by hand against the official reference because widget methods
(sendWidget / editMessageWidgetData / answerWidgetQuery) are days old and
not yet supported by aiogram / python-telegram-bot.
"""
import logging
from typing import Any, List, Optional

import aiohttp

log = logging.getLogger('tg.api')


class ApiError(Exception):
    def __init__(self, description: str, error_code: Optional[int] = None,
                 retry_after: Optional[int] = None) -> None:
        super().__init__(description)
        self.description = description
        self.error_code = error_code
        self.retry_after = retry_after


class TelegramApi:
    def __init__(self, token: str, proxy: str = '') -> None:
        self._base = 'https://api.telegram.org/bot' + token
        self._session: Optional[aiohttp.ClientSession] = None
        self._socks_connector: Any = None
        # SOCKS proxies go into the connector, HTTP(S) proxies into per-request `proxy`.
        self._http_proxy = ''
        if proxy:
            if proxy.startswith(('socks4://', 'socks5://')):
                try:
                    from aiohttp_socks import ProxyConnector
                except ImportError:
                    raise RuntimeError(
                        'Для SOCKS-прокси нужен пакет aiohttp-socks: pip install aiohttp-socks')
                self._socks_connector = ProxyConnector.from_url(proxy)
            elif proxy.startswith(('http://', 'https://')):
                self._http_proxy = proxy
            else:
                raise RuntimeError('TAMAGOTCHI_PROXY: поддерживаются socks4/5, http, https — %r' % proxy)

    async def __aenter__(self) -> 'TelegramApi':
        # Long polling holds one request open for up to 50s.
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=75),
            connector=self._socks_connector,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session:
            await self._session.close()

    async def call(self, method: str, **params: Any) -> Any:
        if self._session is None:
            raise RuntimeError('TelegramApi must be used as an async context manager')
        extra: dict = {}
        if self._http_proxy:
            extra['proxy'] = self._http_proxy
        async with self._session.post(self._base + '/' + method, json=params, **extra) as resp:
            data = await resp.json(content_type=None)
        if not isinstance(data, dict) or not data.get('ok'):
            description = data.get('description', 'unknown error') if isinstance(data, dict) else str(data)
            extra = data.get('parameters') or {} if isinstance(data, dict) else {}
            raise ApiError(description, data.get('error_code') if isinstance(data, dict) else None,
                           extra.get('retry_after'))
        return data['result']

    # --- informational -------------------------------------------------

    async def get_me(self) -> dict:
        return await self.call('getMe')

    async def set_my_commands(self, commands: List[dict]) -> None:
        await self.call('setMyCommands', commands=commands)

    async def set_chat_menu_button(self, menu_button: dict) -> None:
        # without chat_id sets the default menu button for all chats
        await self.call('setChatMenuButton', menu_button=menu_button)

    # --- widgets (Bot API 10.4) ----------------------------------------

    async def send_widget(self, chat_id: int, html: str, chat_data: str, caption: str) -> dict:
        return await self.call(
            'sendWidget',
            chat_id=chat_id,
            html=html,
            chat_data=chat_data,
            caption=caption,
            allow_queries=True,
        )

    async def edit_widget_data(self, chat_id: int, message_id: int, chat_data: str) -> bool:
        try:
            await self.call('editMessageWidgetData', chat_id=chat_id,
                            message_id=message_id, chat_data=chat_data)
            return True
        except ApiError as err:
            if 'message is not modified' in err.description:
                return True
            raise

    async def answer_widget_query(self, query_id: str, data: Optional[str]) -> None:
        params: dict = {'widget_query_id': query_id}
        if data is not None:
            params['data'] = data
        await self.call('answerWidgetQuery', **params)

    # --- messages -------------------------------------------------------

    async def send_message(self, chat_id: int, text: str,
                           reply_markup: Optional[dict] = None) -> None:
        params: dict = {'chat_id': chat_id, 'text': text}
        if reply_markup is not None:
            params['reply_markup'] = reply_markup
        await self.call('sendMessage', **params)

    async def pin_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self.call('pinChatMessage', chat_id=chat_id, message_id=message_id,
                            disable_notification=True)
        except ApiError as err:
            log.warning('pinChatMessage failed: %s', err.description)

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self.call('deleteMessage', chat_id=chat_id, message_id=message_id)
        except ApiError as err:
            log.warning('deleteMessage failed: %s', err.description)
