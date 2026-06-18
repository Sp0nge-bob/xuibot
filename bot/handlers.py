from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from loguru import logger

from config.payments import get_payment_method_by_key
from db import payment_methods as pay_methods_db
from config.plans import get_plan
from config.settings import settings
from config.trial import is_trial_email
from db import database as db
from db import promo_codes as promo_db
from db import promo_pending as pending_db
from db import trial_grants as trial_db
from db import bot_settings as settings_db
from db import tickets as tickets_db
from .telegram_html import safe_html_fragment
from services import platega_simulator as platega_sim
from services.payment_pending import (
    expires_in_from_order_created,
    fetch_pending_expires_in,
    get_resumable_pending_order,
    is_payment_window_expired,
)
from services.platega_client import (
    build_create_request,
    create_transaction,
    format_create_error_message,
    format_request_preview,
    get_return_urls,
    parse_create_response,
    PlategaAPIError,
)
from services.payment_flow import (
    PendingTestOutcome,
    apply_pending_test_outcome,
    check_payment_status,
)
from services.payment_processor import handle_platega_status
from services.pricing import get_plan_quote, list_plans, quote_from_order
from services.subscription_sync import (
    get_active_subscriptions_for_ui,
    get_primary_paid_subscription_for_ui,
    get_primary_subscription_for_ui,
)
from services.promo_redeem import redeem_promo_code
from services.trial import claim_trial, get_trial_button_visible
from services.xui import build_sub_link
from .fulfillment_delivery import deliver_fulfillment
from .ui_helpers import safe_cb_answer, send_or_edit
from .keyboards import (
    main_menu_kb,
    plans_kb,
    payment_methods_kb,
    test_scenario_kb,
    payment_kb,
    subscription_manage_kb,
    subscriptions_manage_kb,
    no_subscription_kb,
    back_to_main_kb,
    payment_failed_kb,
    trial_confirm_kb,
)
from .messages import (
    EXTEND_BLOCKED_REFUND_PENDING_MSG,
    main_menu_text,
    plans_menu_text,
    plan_card_text,
    payment_method_text,
    test_payment_text,
    test_scenario_result_text,
    subscription_manage_text,
    subscriptions_manage_text,
    no_subscription_text,
    pending_payment_text,
    promo_enter_text,
    trial_offer_text,
)
from .states import UserStates

router = Router()


def _payment_failure_kb(order: dict, result) -> "InlineKeyboardMarkup":
    from aiogram.types import InlineKeyboardMarkup
    if result.amount_mismatch or order.get("status") == "failed":
        return payment_failed_kb(order["id"])
    return back_to_main_kb()


async def _checkout_quote(
    state: FSMContext,
    plan_id: str,
    tg_id: int,
) -> "PriceQuote | None":
    return await get_plan_quote(plan_id, tg_id=tg_id)


async def _clear_promo_input_state(state: FSMContext) -> None:
    await state.set_state(None)


def _message_command(text: str) -> str | None:
    raw = (text or "").strip().split()[0]
    if not raw.startswith("/"):
        return None
    return raw.split("@")[0].lower()


async def _show_main_menu(target: Message | CallbackQuery, *, edit: bool = False, state: FSMContext | None = None):
    user = target.from_user
    if isinstance(target, CallbackQuery):
        await safe_cb_answer(target)

    await db.get_or_create_user(user.id, user.username, user.first_name)
    subs = await get_active_subscriptions_for_ui(user.id)
    trial_available = await get_trial_button_visible(user.id)
    pending_promo = None
    pending_expires = None
    pending = await pending_db.get_active_pending_discount(user.id)
    if pending:
        promo = await promo_db.get_promo_by_id(pending["promo_id"])
        if promo:
            pending_promo = promo
            pending_expires = pending["expires_at"]
    greeting_template = await settings_db.get_start_greeting()
    announcement = await settings_db.get_start_announcement()
    if announcement:
        announcement = safe_html_fragment(announcement)
    refund_pending = await tickets_db.get_approved_refunds_pending_chargeback(user.id)
    pending_order = await get_resumable_pending_order(user.id)
    text = main_menu_text(
        user.first_name,
        user.username,
        subs,
        greeting_template=greeting_template,
        announcement=announcement,
        refund_pending_chargeback=bool(refund_pending),
        pending_discount_promo=pending_promo,
        pending_discount_expires_at=pending_expires,
        pending_payment_plan_name=pending_order.get("plan_name") if pending_order else None,
    )
    kb = main_menu_kb(
        trial_available=trial_available,
        pending_tx_id=pending_order.get("platega_tx_id") if pending_order else None,
    )

    if isinstance(target, CallbackQuery):
        if edit:
            await send_or_edit(target, text, kb)
        else:
            await target.message.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


async def _notify_admins(text: str):
    from bot import bot as tg_bot
    for admin_id in settings.BOT_ADMINS:
        try:
            await tg_bot.send_message(admin_id, text)
        except Exception as e:
            logger.error("Failed to notify admin {}: {}", admin_id, e)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await _show_main_menu(message, state=state)


@router.message(Command("subscription"))
async def cmd_subscription(message: Message, state: FSMContext):
    await _clear_promo_input_state(state)
    from .tickets import show_subscriptions_manage

    await show_subscriptions_manage(message, message.from_user.id)


@router.callback_query(F.data == "promo_enter")
async def cb_promo_enter(cb: CallbackQuery, state: FSMContext):
    await _clear_promo_input_state(state)
    await state.set_state(UserStates.waiting_promo_code)
    await safe_cb_answer(cb)
    await send_or_edit(cb, promo_enter_text(), back_to_main_kb())


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext):
    await _clear_promo_input_state(state)
    await _show_main_menu(cb, edit=True, state=state)


@router.callback_query(F.data.startswith("resume_pay:"))
async def cb_resume_pay(cb: CallbackQuery, state: FSMContext):
    await _clear_promo_input_state(state)
    tx_id = cb.data.split(":", 1)[1]
    order = await _guard_payment_order(cb, tx_id)
    if not order:
        return
    expires_in = await fetch_pending_expires_in(tx_id, order)
    if is_payment_window_expired(expires_in):
        await safe_cb_answer(
            cb,
            "Время оплаты истекло — выберите тариф заново",
            show_alert=True,
        )
        await _show_main_menu(cb, edit=True, state=state)
        return
    pending_text, pending_kb = await _pending_payment_view(order, tx_id)
    if not pending_text or not pending_kb:
        await safe_cb_answer(cb, "Не удалось восстановить оплату", show_alert=True)
        return
    await safe_cb_answer(cb)
    await send_or_edit(cb, pending_text, pending_kb)


@router.callback_query(F.data == "trial_offer")
async def cb_trial_offer(cb: CallbackQuery):
    ok, reason = await trial_db.can_claim_trial(cb.from_user.id)
    if not ok:
        await safe_cb_answer(cb, reason, show_alert=True)
        return
    await safe_cb_answer(cb)
    from services.limit_ip import get_trial_limit_ip

    limit_ip = await get_trial_limit_ip()
    await send_or_edit(cb, trial_offer_text(limit_ip=limit_ip), trial_confirm_kb())


@router.callback_query(F.data == "trial_confirm")
async def cb_trial_confirm(cb: CallbackQuery):
    await safe_cb_answer(cb, "Активируем пробный период…")
    await send_or_edit(cb, "⏳ Создаём пробную подписку…")
    try:
        result = await claim_trial(cb.from_user.id)
    except ValueError as e:
        await send_or_edit(cb, f"❌ {e}", back_to_main_kb())
        return
    except Exception as e:
        logger.exception("Trial claim error: {}", e)
        await send_or_edit(cb, "❌ Не удалось активировать пробный период. Попробуйте позже.", back_to_main_kb())
        return

    try:
        await cb.message.delete()
    except Exception:
        pass
    await deliver_fulfillment(
        cb.message.bot,
        cb.message.chat.id,
        text=result.text,
        photo=result.photo,
        link_message=result.link_message,
        setup_text=result.setup_text,
        setup_photos=result.setup_photos or None,
        reply_markup=back_to_main_kb(),
    )


@router.callback_query(F.data == "tariffs")
async def cb_tariffs(cb: CallbackQuery, state: FSMContext):
    await _clear_promo_input_state(state)
    sub = await get_primary_subscription_for_ui(cb.from_user.id)
    extend_blocked = await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id)
    plans = await list_plans()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        plans_menu_text(has_active_sub=sub is not None and not extend_blocked),
        plans_kb(plans),
    )


@router.callback_query(F.data.startswith("select_plan:"))
async def cb_select_plan(cb: CallbackQuery, state: FSMContext):
    plan_id = cb.data.split(":", 1)[1]
    quote = await _checkout_quote(state, plan_id, cb.from_user.id)
    if not quote:
        await safe_cb_answer(cb, "Тариф не найден", show_alert=True)
        return
    sub = await get_primary_subscription_for_ui(cb.from_user.id)
    extend_blocked = await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id)
    methods = await pay_methods_db.get_enabled_payment_methods()
    if not methods:
        await safe_cb_answer(cb, "Способы оплаты временно недоступны", show_alert=True)
        return
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        plan_card_text(
            quote.plan,
            has_active_sub=sub is not None and not extend_blocked,
            quote=quote,
        ),
        payment_methods_kb(plan_id, methods=methods, quote=quote),
    )


@router.callback_query(F.data.startswith("extend_plan:"))
async def cb_extend_plan(cb: CallbackQuery, state: FSMContext):
    if await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id):
        await safe_cb_answer(cb, EXTEND_BLOCKED_REFUND_PENDING_MSG, show_alert=True)
        return
    plan_id = cb.data.split(":", 1)[1]
    quote = await _checkout_quote(state, plan_id, cb.from_user.id)
    if not quote:
        await safe_cb_answer(cb, "Тариф не найден", show_alert=True)
        return
    methods = await pay_methods_db.get_enabled_payment_methods()
    if not methods:
        await safe_cb_answer(cb, "Способы оплаты временно недоступны", show_alert=True)
        return
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        plan_card_text(quote.plan, extend=True, quote=quote),
        payment_methods_kb(plan_id, methods=methods, extend=True, quote=quote),
    )


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(cb: CallbackQuery, state: FSMContext):
    _, plan_id, method_key = cb.data.split(":", 2)
    await _start_payment(cb, plan_id, method_key, order_type="new", state=state)


@router.callback_query(F.data.startswith("pay_extend:"))
async def cb_pay_extend(cb: CallbackQuery, state: FSMContext):
    if await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id):
        await safe_cb_answer(cb, EXTEND_BLOCKED_REFUND_PENDING_MSG, show_alert=True)
        return
    _, plan_id, method_key = cb.data.split(":", 2)
    sub = await get_primary_subscription_for_ui(cb.from_user.id)
    if not sub:
        await safe_cb_answer(cb, "Нет активной подписки", show_alert=True)
        return
    await _start_payment(cb, plan_id, method_key, order_type="extend", state=state)


def _payment_metadata(cb: CallbackQuery, plan_id: str, order_type: str) -> dict:
    user_name = cb.from_user.username or cb.from_user.first_name or str(cb.from_user.id)
    return {
        "userId": str(cb.from_user.id),
        "userName": user_name,
        "planId": plan_id,
        "orderType": order_type,
    }


def _payment_description(plan_name: str, *, extend: bool) -> str:
    return f"VPN {'продление' if extend else 'подписка'}: {plan_name}"


async def _start_payment(
    cb: CallbackQuery,
    plan_id: str,
    method_key: str,
    *,
    order_type: str,
    state: FSMContext,
):
    quote = await _checkout_quote(state, plan_id, cb.from_user.id)
    method = get_payment_method_by_key(method_key)
    if not quote or not method:
        await safe_cb_answer(cb, "Неверные данные оплаты", show_alert=True)
        return
    if not await pay_methods_db.is_payment_method_enabled(method_key):
        await safe_cb_answer(cb, "Этот способ оплаты отключён", show_alert=True)
        return

    plan = quote.plan

    extend = order_type == "extend"
    existing_sub = await db.get_primary_subscription(cb.from_user.id)
    if extend or (
        existing_sub and not is_trial_email(existing_sub.get("client_email"))
    ):
        if await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id):
            await safe_cb_answer(cb, EXTEND_BLOCKED_REFUND_PENDING_MSG, show_alert=True)
            return

    await safe_cb_answer(cb)
    has_active_sub = existing_sub is not None and not extend

    bot_username = (await cb.bot.get_me()).username
    return_url, failed_url = get_return_urls(bot_username)
    metadata = _payment_metadata(cb, plan_id, order_type)
    description = _payment_description(plan["name"], extend=extend)
    payload = f"tg:{cb.from_user.id}:{plan_id}:{order_type}"
    req = build_create_request(
        quote.final_price,
        description=description,
        return_url=return_url,
        failed_url=failed_url,
        payload=payload,
        metadata=metadata,
        payment_method=method["platega_id"],
    )
    preview = format_request_preview(req["path"], req["body"])

    if settings.TEST_MODE:
        await send_or_edit(
            cb,
            test_payment_text(
                plan, method["name"], method["emoji"],
                extend=extend, has_active_sub=has_active_sub, quote=quote,
                request_preview=preview,
            ),
            test_scenario_kb(plan_id, method_key, extend=extend),
        )
        return

    await send_or_edit(cb, "⏳ Создаём счёт на оплату...")
    try:
        tx = await create_transaction(
            amount=quote.final_price,
            description=description,
            return_url=return_url,
            failed_url=failed_url,
            payload=payload,
            metadata=metadata,
            payment_method=method["platega_id"],
        )
    except PlategaAPIError as e:
        logger.exception("Platega error: {}", e)
        await send_or_edit(cb, format_create_error_message(e), back_to_main_kb())
        return
    except Exception as e:
        logger.exception("Platega error: {}", e)
        await send_or_edit(cb, format_create_error_message(e), back_to_main_kb())
        return

    parsed = parse_create_response(tx)
    tx_id = parsed["tx_id"]
    redirect = parsed["redirect"]
    if not tx_id or not redirect:
        await send_or_edit(
            cb,
            "❌ Не удалось получить ссылку на оплату.",
            back_to_main_kb(),
        )
        return

    await db.create_order(
        tg_id=cb.from_user.id,
        plan_id=plan_id,
        plan_name=plan["name"],
        amount=quote.final_price,
        platega_tx_id=tx_id,
        payment_method=method_key,
        order_type=order_type,
        promo_code=quote.promo_code,
        original_amount=quote.base_price,
        discount_amount=quote.discount_amount,
        payment_redirect=redirect,
    )
    order = await db.get_order_by_platega_tx(tx_id) or {
        "created_at": None,
        "payment_redirect": redirect,
    }
    expires_in = parsed.get("expires_in") or expires_in_from_order_created(order.get("created_at"))

    await send_or_edit(
        cb,
        pending_payment_text(
            plan, method["name"],
            extend=extend, has_active_sub=has_active_sub, quote=quote,
            expires_in=expires_in,
        ),
        payment_kb(redirect, tx_id),
    )


@router.callback_query(F.data.startswith("test_scenario:"))
async def cb_test_scenario(cb: CallbackQuery, state: FSMContext):
    _, plan_id, method_key, scenario, ext_flag = cb.data.split(":", 4)
    order_type = "extend" if ext_flag == "1" else "new"
    if order_type == "extend":
        if await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id):
            await safe_cb_answer(cb, EXTEND_BLOCKED_REFUND_PENDING_MSG, show_alert=True)
            return
        sub = await get_primary_subscription_for_ui(cb.from_user.id)
        if not sub:
            await safe_cb_answer(cb, "Нет активной подписки", show_alert=True)
            return
    await _apply_test_scenario(cb, plan_id, method_key, scenario, order_type=order_type, state=state)


async def _apply_test_scenario(
    cb: CallbackQuery,
    plan_id: str,
    method_key: str,
    scenario: str,
    *,
    order_type: str,
    state: FSMContext,
):
    quote = await _checkout_quote(state, plan_id, cb.from_user.id)
    method = get_payment_method_by_key(method_key)
    if not quote or not method:
        await safe_cb_answer(cb, "Неверные данные", show_alert=True)
        return
    if not await pay_methods_db.is_payment_method_enabled(method_key):
        await safe_cb_answer(cb, "Этот способ оплаты отключён", show_alert=True)
        return

    plan = quote.plan
    extend = order_type == "extend"
    existing_sub = await db.get_primary_subscription(cb.from_user.id)
    if extend or (
        existing_sub and not is_trial_email(existing_sub.get("client_email"))
    ):
        if await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id):
            await safe_cb_answer(cb, EXTEND_BLOCKED_REFUND_PENDING_MSG, show_alert=True)
            return
    has_active_sub = existing_sub is not None and not extend

    if scenario == platega_sim.SCENARIO_CREATE_ERROR:
        await safe_cb_answer(cb)
        await send_or_edit(
            cb,
            test_scenario_result_text(scenario)
            + "\n\n"
            + format_create_error_message(
                PlategaAPIError("Unauthorized", status_code=401, detail="Invalid credentials")
            ),
            back_to_main_kb(),
        )
        return

    scenario_labels = {
        "CONFIRMED": "Симулируем оплату…",
        "CANCELED": "Симулируем отмену…",
        "PENDING": "Симулируем ожидание…",
        "CHARGEBACKED": "Симулируем возврат…",
        "CREATE_ERROR": "Симулируем ошибку…",
    }
    await safe_cb_answer(cb, scenario_labels.get(scenario, "Симулируем…"))
    bot_username = (await cb.bot.get_me()).username
    return_url, failed_url = get_return_urls(bot_username)
    metadata = _payment_metadata(cb, plan_id, order_type)
    description = _payment_description(plan["name"], extend=extend)
    payload = f"tg:{cb.from_user.id}:{plan_id}:{order_type}"

    try:
        tx = await create_transaction(
            amount=quote.final_price,
            description=description,
            return_url=return_url,
            failed_url=failed_url,
            payload=payload,
            metadata=metadata,
            payment_method=method["platega_id"],
        )
    except Exception as e:
        logger.exception("Test create error: {}", e)
        await send_or_edit(cb, format_create_error_message(e), back_to_main_kb())
        return

    parsed = parse_create_response(tx)
    tx_id = parsed["tx_id"]
    redirect = parsed["redirect"]
    if not tx_id:
        await send_or_edit(cb, "❌ Симулятор не вернул transactionId.", back_to_main_kb())
        return

    if scenario == platega_sim.SCENARIO_PENDING:
        platega_sim.set_scenario(tx_id, scenario, check_status=platega_sim.SCENARIO_PENDING)
    elif scenario == platega_sim.SCENARIO_CONFIRMED:
        platega_sim.set_scenario(tx_id, scenario, check_status=platega_sim.SCENARIO_CONFIRMED)
    elif scenario == platega_sim.SCENARIO_CANCELED:
        platega_sim.set_scenario(tx_id, scenario, check_status=platega_sim.SCENARIO_CANCELED)
    elif scenario == platega_sim.SCENARIO_CHARGEBACKED:
        platega_sim.set_scenario(tx_id, platega_sim.SCENARIO_CONFIRMED, check_status=platega_sim.SCENARIO_CHARGEBACKED)
    else:
        platega_sim.set_scenario(tx_id, scenario)

    await db.create_order(
        tg_id=cb.from_user.id,
        plan_id=plan_id,
        plan_name=plan["name"],
        amount=quote.final_price,
        platega_tx_id=tx_id,
        payment_method=method_key,
        order_type=order_type,
        promo_code=quote.promo_code,
        original_amount=quote.base_price,
        discount_amount=quote.discount_amount,
        payment_redirect=redirect or "",
    )

    if scenario == platega_sim.SCENARIO_PENDING:
        await send_or_edit(
            cb,
            pending_payment_text(
                plan, method["name"],
                extend=extend, has_active_sub=has_active_sub, quote=quote,
                expires_in=parsed.get("expires_in"),
                test_mode=True,
            ),
            payment_kb(redirect or "https://pay.platega.test/", tx_id, test_mode=True),
        )
        return

    if scenario == platega_sim.SCENARIO_CHARGEBACKED:
        confirm_body = platega_sim.build_callback_payload(tx_id, platega_sim.SCENARIO_CONFIRMED)
        await handle_platega_status(
            tx_id,
            platega_sim.SCENARIO_CONFIRMED,
            source="test_chargeback_step1",
            callback_body=confirm_body,
            notify=False,
        )
        chargeback_body = platega_sim.build_callback_payload(tx_id, platega_sim.SCENARIO_CHARGEBACKED)
        chargeback_result = await handle_platega_status(
            tx_id,
            platega_sim.SCENARIO_CHARGEBACKED,
            source="test_chargeback",
            callback_body=chargeback_body,
            notify=True,
        )
        text = chargeback_result.user_message or test_scenario_result_text(scenario, tx_id)
        failed_order = await db.get_order_by_platega_tx(tx_id) or order
        await send_or_edit(cb, text, _payment_failure_kb(failed_order, chargeback_result))
        return

    callback_body = platega_sim.build_callback_payload(tx_id, scenario)
    result = await handle_platega_status(
        tx_id,
        scenario,
        source="test_callback",
        callback_body=callback_body,
        notify=True,
    )

    if result.photo and result.user_message:
        await cb.message.delete()
        await deliver_fulfillment(
            cb.message.bot,
            cb.message.chat.id,
            text=result.user_message,
            photo=result.photo,
            link_message=result.link_message,
            setup_text=result.setup_text,
            setup_photos=result.setup_photos or None,
            reply_markup=back_to_main_kb(),
        )
        return

    text = result.user_message or test_scenario_result_text(scenario, tx_id)
    await send_or_edit(cb, text, back_to_main_kb())


PENDING_RECHECK_NOTE = "Оплата ещё не поступила — можно проверить снова или перейти к оплате"


async def _pending_payment_view(
    order: dict,
    tx_id: str,
    *,
    status_note: str | None = None,
    rechecked: bool = False,
):
    plan = get_plan(order["plan_id"])
    if not plan:
        return None, None
    method = get_payment_method_by_key(order.get("payment_method") or "")
    quote = quote_from_order(order, plan)
    extend = (order.get("order_type") or "new") == "extend"
    existing_sub = await db.get_primary_subscription(order["tg_id"])
    expires_in = await fetch_pending_expires_in(tx_id, order)
    redirect = (order.get("payment_redirect") or "").strip()
    if not redirect and settings.TEST_MODE and tx_id.startswith("test-"):
        redirect = f"https://pay.platega.test/sim/{tx_id}"
    is_test = settings.TEST_MODE and tx_id.startswith("test-")
    note = status_note
    if rechecked and not note and not is_payment_window_expired(expires_in):
        note = PENDING_RECHECK_NOTE
    text = pending_payment_text(
        plan,
        method["name"] if method else "—",
        extend=extend,
        has_active_sub=existing_sub is not None and not extend,
        quote=quote,
        expires_in=expires_in,
        test_mode=is_test,
        status_note=note,
    )
    kb = payment_kb(redirect, tx_id, test_mode=is_test)
    return text, kb


async def _guard_payment_order(cb: CallbackQuery, tx_id: str) -> dict | None:
    order = await db.get_order_by_platega_tx(tx_id)
    if not order:
        await safe_cb_answer(cb, "Заказ не найден", show_alert=True)
        return None
    if order["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Нет доступа к этому заказу", show_alert=True)
        return None
    if order["status"] == "paid":
        await safe_cb_answer(cb, "Оплата уже обработана!", show_alert=True)
        return None
    if order["status"] == "failed":
        await safe_cb_answer(cb, "Платёж отменён или истёк", show_alert=True)
        return None
    return order


async def _respond_payment_flow(cb: CallbackQuery, order: dict, tx_id: str, flow) -> None:
    result = flow.result
    status = flow.status

    if not result.handled and not result.user_message:
        await cb.message.answer("Не удалось обработать статус. Попробуйте позже.")
        return
    if result.already_paid:
        await cb.message.answer("Оплата уже обработана!", reply_markup=back_to_main_kb())
        return
    if result.amount_mismatch and result.user_message:
        await cb.message.answer(
            result.user_message,
            reply_markup=_payment_failure_kb(order, result),
        )
        return
    if result.photo and result.user_message:
        await deliver_fulfillment(
            cb.message.bot,
            cb.message.chat.id,
            text=result.user_message,
            photo=result.photo,
            link_message=result.link_message,
            setup_text=result.setup_text,
            setup_photos=result.setup_photos or None,
            reply_markup=back_to_main_kb(),
        )
        return
    if status == "PENDING":
        pending_text, pending_kb = await _pending_payment_view(
            order,
            tx_id,
            rechecked=bool(result.user_message),
        )
        if pending_text and pending_kb:
            await send_or_edit(cb, pending_text, pending_kb)
            return
    if result.user_message:
        fresh_order = await db.get_order_by_platega_tx(tx_id) or order
        await cb.message.answer(
            result.user_message,
            reply_markup=_payment_failure_kb(fresh_order, result),
        )
        return
    await cb.message.answer("Не удалось обработать статус. Попробуйте позже.")


async def _process_payment_check(
    cb: CallbackQuery,
    tx_id: str,
    *,
    simulate_success: bool,
    source: str,
) -> None:
    order = await _guard_payment_order(cb, tx_id)
    if not order:
        return

    if simulate_success:
        await safe_cb_answer(cb, "Симулируем оплату…")
    else:
        await safe_cb_answer(cb, "Проверяем…")

    try:
        flow = await check_payment_status(
            tx_id, simulate_confirm=simulate_success, source=source,
        )
    except Exception as e:
        logger.exception("Check payment error: {}", e)
        await cb.message.answer("Не удалось проверить оплату. Попробуйте позже.")
        return

    if simulate_success and not flow.result.handled and not flow.status:
        await safe_cb_answer(cb, "Счёт уже обработан", show_alert=True)
        return

    await _respond_payment_flow(cb, order, tx_id, flow)


async def _process_pending_test_outcome(cb: CallbackQuery, tx_id: str, outcome: PendingTestOutcome) -> None:
    if not settings.TEST_MODE:
        await safe_cb_answer(cb, "Доступно только в тестовом режиме", show_alert=True)
        return

    order = await _guard_payment_order(cb, tx_id)
    if not order:
        return

    labels = {
        PendingTestOutcome.CHECK_STILL_PENDING: "Проверяем…",
        PendingTestOutcome.SIM_CONFIRM: "Симулируем оплату…",
        PendingTestOutcome.SIM_CANCEL: "Симулируем отмену…",
        PendingTestOutcome.SIM_EXPIRED: "Симулируем истечение…",
        PendingTestOutcome.WEBHOOK_CONFIRM: "Симулируем webhook…",
        PendingTestOutcome.WEBHOOK_MISMATCH: "Симулируем неверную сумму…",
    }
    await safe_cb_answer(cb, labels.get(outcome, "Обработка…"))

    try:
        flow = await apply_pending_test_outcome(tx_id, outcome)
    except (ValueError, KeyError) as e:
        await safe_cb_answer(cb, str(e), show_alert=True)
        return
    except Exception as e:
        logger.exception("Pending test outcome error: {}", e)
        await cb.message.answer("Ошибка симуляции. Попробуйте позже.")
        return

    if outcome == PendingTestOutcome.SIM_CONFIRM and not flow.result.handled and not flow.status:
        await safe_cb_answer(cb, "Счёт уже обработан", show_alert=True)
        return

    await _respond_payment_flow(cb, order, tx_id, flow)


@router.callback_query(F.data.startswith("check_pay:"))
async def cb_check_payment(cb: CallbackQuery):
    tx_id = cb.data.split(":", 1)[1]
    await _process_payment_check(cb, tx_id, simulate_success=False, source="check_pay")


@router.callback_query(F.data.startswith("test_check_pay:"))
async def cb_test_check_payment(cb: CallbackQuery):
    tx_id = cb.data.split(":", 1)[1]
    await _process_pending_test_outcome(cb, tx_id, PendingTestOutcome.CHECK_STILL_PENDING)


@router.callback_query(F.data.startswith("test_sim_pay:"))
async def cb_test_sim_payment(cb: CallbackQuery):
    tx_id = cb.data.split(":", 1)[1]
    await _process_pending_test_outcome(cb, tx_id, PendingTestOutcome.SIM_CONFIRM)


@router.callback_query(F.data.startswith("test_sim_webhook:"))
async def cb_test_sim_webhook(cb: CallbackQuery):
    tx_id = cb.data.split(":", 1)[1]
    await _process_pending_test_outcome(cb, tx_id, PendingTestOutcome.WEBHOOK_CONFIRM)


@router.callback_query(F.data.startswith("test_sim_cancel:"))
async def cb_test_sim_cancel(cb: CallbackQuery):
    tx_id = cb.data.split(":", 1)[1]
    await _process_pending_test_outcome(cb, tx_id, PendingTestOutcome.SIM_CANCEL)


@router.callback_query(F.data.startswith("test_sim_expired:"))
async def cb_test_sim_expired(cb: CallbackQuery):
    tx_id = cb.data.split(":", 1)[1]
    await _process_pending_test_outcome(cb, tx_id, PendingTestOutcome.SIM_EXPIRED)


@router.callback_query(F.data.startswith("test_sim_mismatch:"))
async def cb_test_sim_mismatch(cb: CallbackQuery):
    tx_id = cb.data.split(":", 1)[1]
    await _process_pending_test_outcome(cb, tx_id, PendingTestOutcome.WEBHOOK_MISMATCH)


async def _show_subscriptions_manage(cb: CallbackQuery, tg_id: int) -> None:
    from .tickets import show_subscriptions_manage
    await show_subscriptions_manage(cb, tg_id)


@router.callback_query(F.data == "manage_sub")
async def cb_manage_sub(cb: CallbackQuery):
    await safe_cb_answer(cb)
    await _show_subscriptions_manage(cb, cb.from_user.id)


@router.callback_query(F.data == "extend_menu")
async def cb_extend_menu(cb: CallbackQuery, state: FSMContext):
    if await tickets_db.is_extend_blocked_by_pending_refund(cb.from_user.id):
        await safe_cb_answer(cb, EXTEND_BLOCKED_REFUND_PENDING_MSG, show_alert=True)
        return
    sub = await get_primary_paid_subscription_for_ui(cb.from_user.id)
    if not sub:
        await safe_cb_answer(cb, "Нет активной подписки", show_alert=True)
        return
    plans = await list_plans()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        "🔄 <b>Продление подписки</b>\n\nВыберите срок продления:",
        plans_kb(plans, extend=True),
    )


@router.message(UserStates.waiting_promo_code)
async def msg_promo_code(message: Message, state: FSMContext):
    await _clear_promo_input_state(state)

    cmd = _message_command(message.text or "")
    if cmd == "/admin":
        from bot.admin import cmd_admin
        await cmd_admin(message, state)
        return
    if cmd == "/start":
        await state.clear()
        await _show_main_menu(message, state=state)
        return
    if cmd == "/subscription":
        await _clear_promo_input_state(state)
        from .tickets import show_subscriptions_manage

        await show_subscriptions_manage(message, message.from_user.id)
        return
    if cmd == "/faq":
        await _clear_promo_input_state(state)
        from .faq import show_faq_menu_message

        await show_faq_menu_message(message)
        return
    if cmd:
        await message.answer("Ввод промокода отменён.", reply_markup=back_to_main_kb())
        return

    code = (message.text or "").strip()
    if not code:
        await message.answer(
            "Промокод не введён. Нажмите «Промокоды» в главном меню и попробуйте снова.",
            reply_markup=back_to_main_kb(),
        )
        return

    await message.answer("⏳ Проверяем промокод…")
    try:
        result = await redeem_promo_code(message.from_user.id, code)
    except ValueError as e:
        await message.answer(f"❌ {e}", reply_markup=back_to_main_kb())
        return
    except Exception as e:
        logger.exception("Promo redeem error: {}", e)
        await message.answer(
            "❌ Не удалось активировать промокод. Попробуйте позже.",
            reply_markup=back_to_main_kb(),
        )
        return

    if result.kind == "grant" and result.fulfillment:
        await deliver_fulfillment(
            message.bot,
            message.chat.id,
            text=result.fulfillment.text,
            photo=result.fulfillment.photo,
            link_message=result.fulfillment.link_message,
            setup_text=result.fulfillment.setup_text,
            setup_photos=result.fulfillment.setup_photos or None,
            reply_markup=back_to_main_kb(),
        )
        return

    if result.message:
        await message.answer(result.message, reply_markup=back_to_main_kb())


@router.callback_query(F.data.startswith("sub_link:"))
async def cb_sub_link(cb: CallbackQuery):
    sub_id = int(cb.data.split(":", 1)[1])
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or sub["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return

    if not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка неактивна", show_alert=True)
        return

    link = await build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
    if not link:
        await safe_cb_answer(cb, "Ссылка недоступна", show_alert=True)
        return

    from services.fulfillment import make_qr_photo
    from services.fulfillment_text import (
        sub_link_needs_separate_message,
        sub_link_standalone_message,
    )

    kind = "🎁 Пробная" if is_trial_email(sub.get("client_email")) else "✅ Платная"
    photo = make_qr_photo(link, "vpn_link.png")
    await safe_cb_answer(cb)
    kb = back_to_main_kb()
    if sub_link_needs_separate_message(link):
        await cb.message.answer_photo(
            photo,
            caption=f"🔗 <b>{kind} подписка</b>\n\nОтсканируйте QR или скопируйте ссылку ниже 👇",
        )
        followup = sub_link_standalone_message(link)
        if followup:
            await cb.message.answer(followup, reply_markup=kb)
    else:
        await cb.message.answer_photo(
            photo,
            caption=f"🔗 <b>{kind} подписка</b>\n\n<code>{link}</code>",
            reply_markup=kb,
        )


