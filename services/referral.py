"""Реферальная программа: скидки при оплате и бонусные дни."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from config.referral import (
    REFERRAL_PAYMENT_BONUS_DAYS,
    REFERRAL_START_PREFIX,
    REFERRAL_WELCOME_BONUS_DAYS,
    REFERRAL_WELCOME_DISCOUNT_PERCENT,
)
from config.trial import is_trial_email
from db import database as db
from db import referrals as ref_db
from services.xui import extend_client, get_unified_panel_client


def parse_referral_start_arg(raw: str | None) -> int | None:
    if not raw:
        return None
    token = raw.strip()
    if token.lower().startswith(REFERRAL_START_PREFIX):
        token = token[len(REFERRAL_START_PREFIX):]
    if not token.isdigit():
        return None
    referrer_id = int(token)
    return referrer_id if referrer_id > 0 else None


async def try_bind_referrer(referred_tg_id: int, referrer_tg_id: int | None) -> bool:
    if not referrer_tg_id or referrer_tg_id == referred_tg_id:
        return False
    await db.get_or_create_user(referred_tg_id)
    return await ref_db.set_referrer_if_empty(referred_tg_id, referrer_tg_id)


async def calc_referral_discount_amount(tg_id: int, base_price: int) -> int:
    """Скидка рефералки в ₽ (max из welcome и tier для этого пользователя)."""
    if base_price <= 0:
        return 0
    welcome = 0
    flags = await ref_db.get_user_referral_flags(tg_id)
    paid_before = await ref_db.count_paid_orders(tg_id)
    if (
        paid_before == 0
        and not flags["referral_welcome_used"]
        and flags["referred_by_tg_id"]
    ):
        welcome = base_price * REFERRAL_WELCOME_DISCOUNT_PERCENT // 100

    tier_pct = await ref_db.get_referrer_tier_discount_percent(tg_id)
    tier = base_price * tier_pct // 100
    return max(welcome, tier)


async def should_apply_welcome_bonus_days(tg_id: int) -> bool:
    flags = await ref_db.get_user_referral_flags(tg_id)
    return bool(flags["referred_by_tg_id"]) and not flags["referral_welcome_used"]


async def credit_referrer_days(referrer_tg_id: int, days: int) -> None:
    extra = int(days)
    if extra <= 0:
        return
    target = await db.get_primary_paid_subscription(referrer_tg_id)
    if not target or is_trial_email(target.get("client_email")):
        await ref_db.add_pending_referral_days(referrer_tg_id, extra)
        logger.info("Referral: +{} дн. в очередь для tg_id={}", extra, referrer_tg_id)
        return

    new_end = await db.extend_subscription_record(target["id"], extra)
    email = target["client_email"]
    if await get_unified_panel_client(email):
        new_expiry_ms = int(datetime.fromisoformat(new_end.replace("Z", "")).timestamp() * 1000)
        await extend_client(email, extra, target_expiry_ms=new_expiry_ms)
    logger.info("Referral: +{} дн. рефереру tg_id={} sub #{}", extra, referrer_tg_id, target["id"])


async def apply_pending_referral_days_for_user(tg_id: int, subscription_id: int) -> int:
    pending = await ref_db.take_pending_referral_days(tg_id)
    if pending <= 0:
        return 0
    new_end = await db.add_subscription_bonus_days(subscription_id, pending)
    sub = await db.get_subscription_by_id(subscription_id)
    if sub and await get_unified_panel_client(sub["client_email"]):
        expiry_ms = int(datetime.fromisoformat(new_end.replace("Z", "")).timestamp() * 1000)
        await extend_client(sub["client_email"], pending, target_expiry_ms=expiry_ms)
    logger.info("Referral: применено {} дн. из очереди tg_id={}", pending, tg_id)
    return pending


async def process_referral_rewards_for_order(order: dict[str, Any], *, subscription_id: int) -> None:
    """После успешной выдачи по оплаченному заказу."""
    order_id = order.get("id")
    referred_tg_id = order.get("tg_id")
    if not order_id or not referred_tg_id:
        return

    if await ref_db.get_reward_log_by_order(order_id):
        return

    referrer_tg_id = await ref_db.get_referrer_tg_id(referred_tg_id)
    referred_bonus = 0
    welcome_applied = False

    if await should_apply_welcome_bonus_days(referred_tg_id):
        referred_bonus = REFERRAL_WELCOME_BONUS_DAYS
        welcome_applied = True
        new_end = await db.add_subscription_bonus_days(subscription_id, referred_bonus)
        sub = await db.get_subscription_by_id(subscription_id)
        if sub and await get_unified_panel_client(sub["client_email"]):
            expiry_ms = int(datetime.fromisoformat(new_end.replace("Z", "")).timestamp() * 1000)
            await extend_client(sub["client_email"], referred_bonus, target_expiry_ms=expiry_ms)
        await ref_db.mark_welcome_used(referred_tg_id)

    referrer_bonus = 0
    if referrer_tg_id and referrer_tg_id != referred_tg_id:
        referrer_bonus = REFERRAL_PAYMENT_BONUS_DAYS
        await credit_referrer_days(referrer_tg_id, referrer_bonus)

    if referrer_tg_id or referred_bonus:
        await ref_db.insert_reward_log(
            order_id=order_id,
            referred_tg_id=referred_tg_id,
            referrer_tg_id=referrer_tg_id or 0,
            referrer_bonus_days=referrer_bonus,
            referred_bonus_days=referred_bonus,
            welcome_applied=welcome_applied,
        )


async def reverse_referral_rewards_for_order(order: dict[str, Any]) -> None:
    log = await ref_db.get_reward_log_by_order(order.get("id") or 0)
    if not log:
        return

    referrer_tg_id = int(log["referrer_tg_id"] or 0)
    referred_tg_id = int(log["referred_tg_id"])
    ref_days = int(log["referrer_bonus_days"] or 0)
    friend_days = int(log["referred_bonus_days"] or 0)

    if ref_days > 0 and referrer_tg_id:
        sub = await db.get_primary_paid_subscription(referrer_tg_id)
        if sub:
            await db.shrink_subscription_record(sub["id"], ref_days)

    if friend_days > 0:
        sub = None
        if order.get("subscription_id"):
            sub = await db.get_subscription_by_id(order["subscription_id"])
        if not sub:
            sub = await db.get_subscription_by_order_id(order["id"])
        if sub:
            await db.shrink_subscription_record(sub["id"], friend_days)

    if log.get("welcome_applied"):
        await ref_db.clear_welcome_used(referred_tg_id)

    await ref_db.delete_reward_log(order["id"])


def build_referral_link(bot_username: str, tg_id: int) -> str:
    username = (bot_username or "").lstrip("@")
    return f"https://t.me/{username}?start={REFERRAL_START_PREFIX}{tg_id}"


async def get_referral_dashboard(tg_id: int) -> dict[str, Any]:
    stats = await ref_db.count_referrals(tg_id)
    flags = await ref_db.get_user_referral_flags(tg_id)
    tier_pct = ref_db.tier_discount_percent(stats["active"])
    return {
        **stats,
        "tier_percent": tier_pct,
        "pending_days": flags["pending_referral_days"],
        "friends": await ref_db.list_referred_users(tg_id),
    }