"""Long polling loop: no public HTTPS endpoint required for local runs."""
import asyncio
import logging

from bot.api import ApiError

log = logging.getLogger('tg.polling')

ALLOWED_UPDATES = ['message', 'widget_query']
POLL_TIMEOUT = 50
ERROR_BACKOFF = 3


async def run_polling(app) -> None:
    offset = 0
    log.info('long polling started')
    while True:
        try:
            updates = await app.api.call(
                'getUpdates',
                offset=offset,
                timeout=POLL_TIMEOUT,
                allowed_updates=ALLOWED_UPDATES,
            )
        except asyncio.CancelledError:
            raise
        except ApiError as err:
            log.warning('getUpdates ApiError: %s', err.description)
            await asyncio.sleep(ERROR_BACKOFF)
            continue
        except Exception as err:
            log.warning('getUpdates network error: %s', err)
            await asyncio.sleep(ERROR_BACKOFF)
            continue
        for update in updates:
            offset = update['update_id'] + 1
            try:
                await app.handle_update(update)
            except Exception:
                log.exception('failed to handle update')
