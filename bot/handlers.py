from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from loguru import logger

from config.payments import get_payment_method_by_key
from config.plans import get_plan
from config.settings import settings
from db import database as db
from services import platega_simulator as platega_sim
from services.platega_client import (
    build_create_request,
    create_transaction,
    format_create_error_message,
    format_request_preview,
    get_return_urls,
    get_transaction_status,
    parse_create_response,
    parse_status_response,
    PlategaAPIError,
)
from services.payment_flow import (
    PendingTestOutcome,
    apply_pending_test_outcome,
    check_payment_status,
)
from services.payment_processor import handle_platega_status
from services.pricing import get_plan_quote, list_plans, validate_promo
from services.subscription_sync import get_primary_subscription_for_ui
from services.xui import build_sub_link
from .ui_helpers import safe_cb_answer, send_or_edit
from .keyboards import (
    main_menu_kb,
    plans_kb,
    payment_methods_kb,
    test_scenario_kb,
    payment_kb,
    subscription_manage_kb,
    refund_confirm_kb,
    refund_chat_kb,
    no_subscription_kb,
    back_to_main_kb,
)
from .messages import (
    main_menu_text,
    plans_menu_text,
    plan_card_text,
    payment_method_text,
    test_payment_text,
    test_scenario_result_text,
    subscription_manage_text,
    no_subscription_text,
    refund_confirm_text,
    refund_request_sent_text,
    refund_admin_text,
    pending_payment_text,
    promo_enter_text,
    promo_applied_text,
)
from .states import UserStates
from .refund_chat import format_refund_chat_history, store_and_deliver_refund_message

router = Router()


async def _checkout_quote(
    state: FSMContext,
    plan_id: str,
    tg_id: int,
) -> "PriceQuote | None":
    data = await state.get_data()
    promo = data.get("promo_code")
    return await get_plan_quote(plan_id, promo_code=promo, tg_id=tg_id)


async def _clear_promo_input_state(state: FSMContext) -> None:
    await state.set_state(None)
    await state.update_data(promo_plan_id=None, promo_extend=None)


def _message_command(text: str) -> str | None:
    raw = (text or "").strip().split()[0]
    if not raw.startswith("/"):
        return None
    return raw.split("@")[0].lower()


async def _show_main_menu(target: Message | CallbackQuery, *, edit: bool = False, state: FSMContext | None = None):
    user = target.from_user
    if isinstance(target, CallbackQuery):
        await safe_cb_answer(target)

    if state:
        await state.update_data(promo_code=None)

    await db.get_or_create_user(user.id, user.username, user.first_name)
    sub = await get_primary_subscription_for_ui(user.id)
    text = main_menu_text(user.first_name, user.username, sub)
    kb = main_menu_kb(sub is not None)

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


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext):
    await _clear_promo_input_state(state)
    await state.update_data(promo_code=None)
    await _show_main_menu(cb, edit=True, state=state)


@router.callback_query(F.data == "tariffs")
async def cb_tariffs(cb: CallbackQuery, state: FSMContext):
    await _clear_promo_input_state(state)
    await state.update_data(promo_code=None)
    sub = await get_primary_subscription_for_ui(cb.from_user.id)
    plans = await list_plans()
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        plans_menu_text(has_active_sub=sub is not None),
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
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        plan_card_text(quote.plan, has_active_sub=sub is not None, quote=quote),
        payment_methods_kb(plan_id, quote=quote),
    )


@router.callback_query(F.data.startswith("extend_plan:"))
async def cb_extend_plan(cb: CallbackQuery, state: FSMContext):
    plan_id = cb.data.split(":", 1)[1]
    quote = await _checkout_quote(state, plan_id, cb.from_user.id)
    if not quote:
        await safe_cb_answer(cb, "Тариф не найден", show_alert=True)
        return
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        plan_card_text(quote.plan, extend=True, quote=quote),
        payment_methods_kb(plan_id, extend=True, quote=quote),
    )


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(cb: CallbackQuery, state: FSMContext):
    _, plan_id, method_key = cb.data.split(":", 2)
    await _start_payment(cb, plan_id, method_key, order_type="new", state=state)


@router.callback_query(F.data.startswith("pay_extend:"))
async def cb_pay_extend(cb: CallbackQuery, state: FSMContext):
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
    method = get_payment_method_by_key(
        method_key,
        settings.PLATEGA_SBP_METHOD,
        settings.PLATEGA_CRYPTO_METHOD,
    )
    if not quote or not method:
        await safe_cb_answer(cb, "Неверные данные оплаты", show_alert=True)
        return

    plan = quote.plan

    await safe_cb_answer(cb)
    extend = order_type == "extend"
    existing_sub = await db.get_primary_subscription(cb.from_user.id)
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
    )

    await send_or_edit(
        cb,
        pending_payment_text(
            plan, method["name"],
            extend=extend, has_active_sub=has_active_sub, quote=quote,
            expires_in=parsed.get("expires_in"),
        ),
        payment_kb(redirect, tx_id),
    )


@router.callback_query(F.data.startswith("test_scenario:"))
async def cb_test_scenario(cb: CallbackQuery, state: FSMContext):
    _, plan_id, method_key, scenario, ext_flag = cb.data.split(":", 4)
    order_type = "extend" if ext_flag == "1" else "new"
    if order_type == "extend":
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
    method = get_payment_method_by_key(
        method_key,
        settings.PLATEGA_SBP_METHOD,
        settings.PLATEGA_CRYPTO_METHOD,
    )
    if not quote or not method:
        await safe_cb_answer(cb, "Неверные данные", show_alert=True)
        return

    plan = quote.plan
    extend = order_type == "extend"
    existing_sub = await db.get_primary_subscription(cb.from_user.id)
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
        await send_or_edit(cb, text, back_to_main_kb())
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
        await cb.message.answer_photo(
            result.photo,
            caption=result.user_message,
            reply_markup=back_to_main_kb(),
        )
        return

    text = result.user_message or test_scenario_result_text(scenario, tx_id)
    await send_or_edit(cb, text, back_to_main_kb())


PENDING_NOT_PAID_NOTE = "Оплата ещё не прошла"


async def _pending_payment_view(order: dict, tx_id: str, *, status_note: str | None = None):
    plan = get_plan(order["plan_id"])
    if not plan:
        return None, None
    method = get_payment_method_by_key(
        order.get("payment_method") or "",
        settings.PLATEGA_SBP_METHOD,
        settings.PLATEGA_CRYPTO_METHOD,
    )
    quote = await get_plan_quote(
        order["plan_id"],
        promo_code=order.get("promo_code"),
        tg_id=order["tg_id"],
    )
    extend = (order.get("order_type") or "new") == "extend"
    existing_sub = await db.get_primary_subscription(order["tg_id"])
    expires_in = None
    redirect = f"https://pay.platega.test/sim/{tx_id}"
    if settings.TEST_MODE and tx_id.startswith("test-"):
        try:
            sim_status = platega_sim.simulate_get_status(tx_id)
            expires_in = sim_status.get("expiresIn")
        except KeyError:
            pass
    is_test = settings.TEST_MODE and tx_id.startswith("test-")
    text = pending_payment_text(
        plan,
        method["name"] if method else "—",
        extend=extend,
        has_active_sub=existing_sub is not None and not extend,
        quote=quote,
        expires_in=expires_in,
        test_mode=is_test,
        status_note=status_note,
    )
    kb = payment_kb(redirect, tx_id, test_mode=is_test)
    return text, kb


async def _guard_payment_order(cb: CallbackQuery, tx_id: str) -> dict | None:
    order = await db.get_order_by_platega_tx(tx_id)
    if not order:
        await safe_cb_answer(cb, "Заказ не найден", show_alert=True)
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
        await cb.message.answer(result.user_message, reply_markup=back_to_main_kb())
        return
    if result.photo and result.user_message:
        await cb.message.answer_photo(
            result.photo,
            caption=result.user_message,
            reply_markup=back_to_main_kb(),
        )
        return
    if result.user_message:
        if status == "PENDING" and settings.TEST_MODE and tx_id.startswith("test-"):
            pending_text, pending_kb = await _pending_payment_view(
                order, tx_id, status_note=PENDING_NOT_PAID_NOTE,
            )
            if pending_text and pending_kb:
                await send_or_edit(cb, pending_text, pending_kb)
                return
        await cb.message.answer(result.user_message, reply_markup=back_to_main_kb())
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


@router.callback_query(F.data == "manage_sub")
async def cb_manage_sub(cb: CallbackQuery):
    await safe_cb_answer(cb)
    sub = await get_primary_subscription_for_ui(cb.from_user.id)
    if not sub:
        await send_or_edit(cb, no_subscription_text(), no_subscription_kb())
        return

    pending_refund = await db.get_pending_refund_for_user(cb.from_user.id)
    sub_link = build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
    await send_or_edit(
        cb,
        subscription_manage_text(sub, sub_link),
        subscription_manage_kb(
            sub["id"],
            refund_id=pending_refund["id"] if pending_refund else None,
        ),
    )


@router.callback_query(F.data == "extend_menu")
async def cb_extend_menu(cb: CallbackQuery, state: FSMContext):
    sub = await get_primary_subscription_for_ui(cb.from_user.id)
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


@router.callback_query(F.data.startswith("promo_enter:"))
async def cb_promo_enter(cb: CallbackQuery, state: FSMContext):
    _, plan_id, ext_flag = cb.data.split(":", 2)
    quote = await get_plan_quote(plan_id, tg_id=cb.from_user.id)
    if not quote:
        await safe_cb_answer(cb, "Тариф не найден", show_alert=True)
        return
    await state.set_state(UserStates.waiting_promo_code)
    await state.update_data(promo_plan_id=plan_id, promo_extend=ext_flag == "1")
    await safe_cb_answer(cb)
    await send_or_edit(cb, promo_enter_text(quote.plan["name"]), back_to_main_kb())


@router.callback_query(F.data.startswith("promo_clear:"))
async def cb_promo_clear(cb: CallbackQuery, state: FSMContext):
    _, plan_id, ext_flag = cb.data.split(":", 2)
    await state.update_data(promo_code=None)
    quote = await get_plan_quote(plan_id, tg_id=cb.from_user.id)
    if not quote:
        await safe_cb_answer(cb, "Тариф не найден", show_alert=True)
        return
    extend = ext_flag == "1"
    sub = await get_primary_subscription_for_ui(cb.from_user.id)
    await safe_cb_answer(cb, "Промокод убран")
    await send_or_edit(
        cb,
        plan_card_text(
            quote.plan,
            extend=extend,
            has_active_sub=sub is not None and not extend,
            quote=quote,
        ),
        payment_methods_kb(plan_id, extend=extend, quote=quote),
    )


@router.message(UserStates.waiting_promo_code)
async def msg_promo_code(message: Message, state: FSMContext):
    data = await state.get_data()
    plan_id = data.get("promo_plan_id")
    extend = data.get("promo_extend", False)

    # Одноразовый ввод: любое следующее сообщение снимает режим ожидания.
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
    if cmd:
        await message.answer("Ввод промокода отменён.")
        return

    if not plan_id:
        await message.answer("Сессия истекла. Выберите тариф заново.", reply_markup=back_to_main_kb())
        return

    code = (message.text or "").strip()
    if not code:
        await message.answer("Промокод не введён. Выберите тариф и нажмите «Промокод» снова.")
        return

    promo, err = await validate_promo(code, plan_id=plan_id, tg_id=message.from_user.id)
    if err:
        await message.answer(
            f"❌ {err}\n\nВыберите тариф и нажмите «Промокод», чтобы попробовать снова.",
        )
        return

    quote = await get_plan_quote(plan_id, promo_code=code, tg_id=message.from_user.id)
    if not quote:
        await message.answer("Тариф не найден.")
        return

    await state.update_data(promo_code=code.upper())

    sub = await get_primary_subscription_for_ui(message.from_user.id)
    await message.answer(promo_applied_text(code.upper(), quote.discount_amount, quote.final_price))
    await message.answer(
        plan_card_text(
            quote.plan,
            extend=extend,
            has_active_sub=sub is not None and not extend,
            quote=quote,
        ),
        reply_markup=payment_methods_kb(plan_id, extend=extend, quote=quote),
    )


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

    link = build_sub_link(sub["sub_id"]) if sub.get("sub_id") else None
    if not link:
        await safe_cb_answer(cb, "Ссылка недоступна", show_alert=True)
        return

    from services.fulfillment import make_qr_photo
    photo = make_qr_photo(link, "vpn_link.png")
    await safe_cb_answer(cb)
    await cb.message.answer_photo(
        photo,
        caption=f"🔗 <b>Ваша подписка</b>\n\n<code>{link}</code>",
        reply_markup=back_to_main_kb(),
    )


@router.callback_query(F.data.startswith("refund:"))
async def cb_refund(cb: CallbackQuery):
    sub_id = int(cb.data.split(":", 1)[1])
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or sub["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return

    if not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка неактивна", show_alert=True)
        return

    await safe_cb_answer(cb)
    await send_or_edit(cb, refund_confirm_text(), refund_confirm_kb(sub_id))


@router.callback_query(F.data.startswith("refund_confirm:"))
async def cb_refund_confirm(cb: CallbackQuery):
    sub_id = int(cb.data.split(":", 1)[1])
    sub = await db.get_subscription_by_id(sub_id)
    if not sub or sub["tg_id"] != cb.from_user.id:
        await safe_cb_answer(cb, "Подписка не найдена", show_alert=True)
        return

    if not sub.get("is_active"):
        await safe_cb_answer(cb, "Подписка неактивна", show_alert=True)
        return

    refund_id = await db.create_refund_request(cb.from_user.id, sub_id)
    await _notify_admins(
        refund_admin_text(
            cb.from_user.id,
            cb.from_user.username,
            cb.from_user.first_name,
            sub,
        )
        + f"\n\n💬 Переписка: /admin → Возвраты → #{refund_id}"
    )
    await safe_cb_answer(cb, "Запрос отправлен")
    await send_or_edit(cb, refund_request_sent_text(), back_to_main_kb())


@router.callback_query(F.data.startswith("refund_chat:"))
async def cb_refund_chat(cb: CallbackQuery, state: FSMContext):
    refund_id = int(cb.data.split(":", 1)[1])
    row = await db.get_refund_request_by_id(refund_id)
    if not row or row["tg_id"] != cb.from_user.id or row.get("status") != "pending":
        await safe_cb_answer(cb, "Переписка недоступна", show_alert=True)
        return

    await state.set_state(None)
    messages = await db.get_refund_messages(refund_id)
    text = format_refund_chat_history(messages, refund_id=refund_id, for_admin=False)
    await safe_cb_answer(cb)
    await send_or_edit(cb, text, refund_chat_kb(refund_id))


@router.callback_query(F.data.startswith("refund_reply:"))
async def cb_refund_reply_start(cb: CallbackQuery, state: FSMContext):
    refund_id = int(cb.data.split(":", 1)[1])
    row = await db.get_refund_request_by_id(refund_id)
    if not row or row["tg_id"] != cb.from_user.id or row.get("status") != "pending":
        await safe_cb_answer(cb, "Переписка недоступна", show_alert=True)
        return

    await state.set_state(UserStates.waiting_refund_reply)
    await state.update_data(refund_chat_id=refund_id)
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        f"✏️ <b>Сообщение по возврату #{refund_id}</b>\n\n"
        "Опишите ситуацию или ответьте администратору.\n"
        "Для отмены: /start",
        refund_chat_kb(refund_id),
    )


@router.message(UserStates.waiting_refund_reply)
async def msg_refund_reply(message: Message, state: FSMContext):
    data = await state.get_data()
    refund_id = data.get("refund_chat_id")
    if not refund_id:
        await state.clear()
        await message.answer("Сессия истекла. Откройте «Управление подпиской».")
        return

    body = (message.text or "").strip()
    if not body:
        await message.answer("❌ Введите текст сообщения.")
        return

    cmd = _message_command(body)
    if cmd == "/start":
        await state.clear()
        await _show_main_menu(message, state=state)
        return
    if cmd:
        await message.answer("Ввод отменён. Откройте переписку снова из меню подписки.")
        await state.clear()
        return

    from bot import bot as tg_bot
    saved = await store_and_deliver_refund_message(
        refund_id=refund_id,
        sender_tg_id=message.from_user.id,
        is_admin=False,
        body=body,
        bot=tg_bot,
    )
    if not saved:
        await state.clear()
        await message.answer("❌ Запрос на возврат уже закрыт.")
        return

    messages = await db.get_refund_messages(refund_id)
    text = format_refund_chat_history(messages, refund_id=refund_id, for_admin=False)
    await message.answer(
        "✅ Сообщение отправлено.\n\n" + text,
        reply_markup=refund_chat_kb(refund_id),
    )