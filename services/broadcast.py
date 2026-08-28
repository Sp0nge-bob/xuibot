"""Массовая рассылка: copy_message исходного сообщения админа всем пользователям."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from loguru import logger

ProgressCb = Callable[[int, int, int], Awaitable[None]]

_SEND_PAUSE_SEC = 0.05
_MAX_RETRIES = 4


async def _copy_one(
    bot: Bot,
    *,
    chat_id: int,
    from_chat_id: int,
    message_ids: list[int],
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            for message_id in message_ids:
                await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=from_chat_id,
                    message_id=message_id,
                )
            return
        except TelegramRetryAfter as e:
            last_error = e
            await asyncio.sleep(float(e.retry_after) + 0.15)
        except (TelegramForbiddenError, TelegramBadRequest):
            raise
        except Exception as e:
            last_error = e
            if attempt >= _MAX_RETRIES:
                raise
            await asyncio.sleep(0.4 * attempt)
    if last_error:
        raise last_error


async def copy_announcement_to_users(
    bot: Bot,
    *,
    from_chat_id: int,
    message_ids: list[int],
    user_ids: list[int],
    skip_ids: set[int] | None = None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Скопировать исходные сообщения каждому tg_id. Без «переслано от»."""
    skip = skip_ids or set()
    ids = [int(uid) for uid in user_ids if int(uid) not in skip]
    sent = 0
    failed = 0
    total = len(ids)

    for index, uid in enumerate(ids, start=1):
        try:
            await _copy_one(
                bot,
                chat_id=uid,
                from_chat_id=from_chat_id,
                message_ids=message_ids,
            )
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            failed += 1
            logger.debug("Broadcast skip tg_id={}: {}", uid, e)
        except Exception as e:
            failed += 1
            logger.warning("Broadcast failed tg_id={}: {}", uid, e)
        if on_progress and (index == total or index % 25 == 0):
            try:
                await on_progress(sent, failed, total)
            except Exception:
                pass
        await asyncio.sleep(_SEND_PAUSE_SEC)

    logger.info("Broadcast done sent={} failed={} total={}", sent, failed, total)
    return {"sent": sent, "failed": failed, "total": total}
