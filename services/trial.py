"""Выдача и админский сброс пробной подписки."""
from loguru import logger

from config.trial import (
    TRIAL_COOLDOWN_DAYS,
    TRIAL_DAYS,
    TRIAL_TRAFFIC_GB,
    trial_client_email,
)
from db import database as db
from db import trial_grants as trial_db
from db.bot_settings import get_subscription_inbound_count
from services.fulfillment import (
    FulfillmentResult,
    load_happ_setup_photos,
    make_qr_photo,
    make_qr_photo_async,
)
from services.fulfillment_text import (
    happ_setup_text,
    qr_and_sync_footer,
    sub_link_caption_lines,
    sub_link_standalone_message,
)
from services.limit_ip import format_connections_limit_line, get_trial_limit_ip
from services.node_sync import schedule_secondary_sync
from services.subscription_admin import admin_reset_all_trials, admin_reset_trial_for_user
from services.xui import provision_client
from utils.utc import days_from_now_ms, ms_to_utc_iso, parse_utc


async def get_trial_button_visible(tg_id: int) -> bool:
    ok, _ = await trial_db.can_claim_trial(tg_id)
    return ok


import asyncio

_trial_locks: dict[int, asyncio.Lock] = {}


def _get_trial_lock(tg_id: int) -> asyncio.Lock:
    lock = _trial_locks.get(tg_id)
    if lock is None:
        if len(_trial_locks) > 5000:
            _trial_locks.clear()
        lock = asyncio.Lock()
        _trial_locks[tg_id] = lock
    return lock


async def claim_trial(tg_id: int) -> FulfillmentResult:
    async with _get_trial_lock(tg_id):
        ok, reason = await trial_db.can_claim_trial(tg_id)
        if not ok:
            raise ValueError(reason)

        email = trial_client_email(tg_id)
        end_ms = days_from_now_ms(TRIAL_DAYS)
        end_iso = ms_to_utc_iso(end_ms)
        import uuid
        new_client_uuid = str(uuid.uuid4())
        email, sub_id, sub_link = await provision_client(
            tg_id=tg_id,
            plan_days=TRIAL_DAYS,
            traffic_gb=TRIAL_TRAFFIC_GB,
            client_email=email,
            client_uuid=new_client_uuid,
            target_expiry_ms=end_ms,
        )

        sub_db_id = await db.create_subscription(
            tg_id=tg_id,
            order_id=None,
            inbound_id=0,
            client_email=email,
            client_uuid=new_client_uuid,
            sub_id=sub_id,
            days=TRIAL_DAYS,
            traffic_gb=TRIAL_TRAFFIC_GB,
            end_date=end_iso,
        )
        await trial_db.record_trial_grant(tg_id, sub_db_id)
        schedule_secondary_sync(sub_db_id)

    inbound_count = await get_subscription_inbound_count()
    limit_ip = await get_trial_limit_ip()
    end_date = parse_utc(end_iso).strftime("%d.%m.%Y")
    lines = [
        "✅ <b>Пробный период активирован!</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"⏱ Срок: <b>{TRIAL_DAYS} дн.</b> (до {end_date})",
        f"📊 Трафик: <b>{TRIAL_TRAFFIC_GB} ГБ</b>",
        format_connections_limit_line(limit_ip),
        f"👤 Клиент: <code>{email}</code>",
        qr_and_sync_footer(inbound_count),
        "",
        f"<i>Повторно — не раньше чем через {TRIAL_COOLDOWN_DAYS} дн.</i>",
    ]

    logger.info("Trial granted for tg_id={} sub_id={}", tg_id, sub_db_id)
    from services.happ_crypto import build_happ_redirect_url
    from services.incy_crypto import build_incy_redirect_url
    sub_key = sub_id or sub_db_id
    happ_url = build_happ_redirect_url(sub_key)
    incy_url = build_incy_redirect_url(sub_key)
    return FulfillmentResult(
        text="\n".join(lines),
        photo=None,
        link_message=None,
        setup_text=None,
        setup_photos=[],
        subscription_id=sub_db_id,
        sub_id=sub_id,
        happ_url=happ_url,
        incy_url=incy_url,
    )


async def admin_reset_trial(tg_id: int) -> dict:
    return await admin_reset_trial_for_user(tg_id)


async def admin_reset_all_trial_subscriptions() -> dict:
    return await admin_reset_all_trials()