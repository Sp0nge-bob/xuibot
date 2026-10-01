"""FAQ для клиентов."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import faq as faq_db
from .faq_view import dismiss_faq_view, set_faq_view_message_ids
from .faq_delivery import send_activation_setup_faq, send_faq_article
from .keyboards import (
    faq_activation_choice_kb,
    faq_activation_client_nav_kb,
    faq_article_nav_kb,
    faq_list_kb,
    help_hub_kb,
)
from .messages import faq_empty_text, faq_menu_text, help_hub_text
from .ui_helpers import safe_cb_answer, send_or_edit, user_answer, user_cb_message_answer

router = Router()


async def _open_faq_article(
    bot,
    chat_id: int,
    article: dict,
    *,
    from_faq: bool = True,
    fallback_delete_msg: Message | None = None,
) -> None:
    photos = await faq_db.list_photos(article["id"])
    had_view = await dismiss_faq_view(bot, chat_id)
    if not had_view and fallback_delete_msg is not None:
        try:
            await fallback_delete_msg.delete()
        except Exception:
            pass
    if faq_db.is_activation_faq_article(article):
        nav = faq_activation_choice_kb(from_faq=from_faq)
        view_ids = await send_activation_setup_faq(
            bot, chat_id, article, reply_markup=nav, client=None,
        )
    else:
        nav = faq_article_nav_kb()
        view_ids = await send_faq_article(
            bot, chat_id, article, photos, reply_markup=nav,
        )
    set_faq_view_message_ids(chat_id, view_ids)


async def show_faq_menu_message(message: Message) -> None:
    articles = await faq_db.list_articles(published_only=True)
    if not articles:
        await user_answer(message, faq_empty_text(), reply_markup=faq_list_kb([]))
        return
    await user_answer(message, faq_menu_text(len(articles)), reply_markup=faq_list_kb(articles))


@router.message(Command("faq"))
async def cmd_faq(message: Message, state: FSMContext):
    await dismiss_faq_view(message.bot, message.chat.id)
    await state.set_state(None)
    await show_faq_menu_message(message)


@router.callback_query(F.data == "help_hub")
async def cb_help_hub(cb: CallbackQuery, state: FSMContext):
    await safe_cb_answer(cb)
    await state.set_state(None)
    had_view = await dismiss_faq_view(cb.message.bot, cb.message.chat.id)
    if had_view:
        await user_cb_message_answer(cb, help_hub_text(), reply_markup=help_hub_kb())
    else:
        await send_or_edit(cb, help_hub_text(), help_hub_kb())


@router.callback_query(F.data == "faq_menu")
async def cb_faq_menu(cb: CallbackQuery):
    await safe_cb_answer(cb)
    had_view = await dismiss_faq_view(cb.message.bot, cb.message.chat.id)
    articles = await faq_db.list_articles(published_only=True)
    text = faq_empty_text() if not articles else faq_menu_text(len(articles))
    kb = faq_list_kb(articles if articles else [])
    if had_view:
        await user_cb_message_answer(cb, text, reply_markup=kb)
    else:
        await send_or_edit(cb, text, kb)


@router.callback_query(F.data == "faq:builtin:activation")
async def cb_faq_builtin_activation(cb: CallbackQuery):
    article = await faq_db.get_article_by_builtin(faq_db.BUILTIN_ACTIVATION_KEY)
    if not article:
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    await safe_cb_answer(cb, "Выберите приложение")
    await _open_faq_article(
        cb.message.bot,
        cb.message.chat.id,
        article,
        from_faq=True,
        fallback_delete_msg=cb.message,
    )


@router.callback_query(F.data.in_({"faq:activation:happ", "faq:activation:incy"}))
async def cb_faq_activation_client(cb: CallbackQuery):
    client = cb.data.rsplit(":", 1)[1]
    await safe_cb_answer(cb)
    had_view = await dismiss_faq_view(cb.message.bot, cb.message.chat.id)
    if not had_view:
        try:
            await cb.message.delete()
        except Exception:
            pass
    nav = faq_activation_client_nav_kb(client=client)
    view_ids = await send_activation_setup_faq(
        cb.message.bot,
        cb.message.chat.id,
        None,
        reply_markup=nav,
        client=client,
    )
    set_faq_view_message_ids(cb.message.chat.id, view_ids)


@router.callback_query(F.data.startswith("faq:article:"))
async def cb_faq_article(cb: CallbackQuery):
    article_id = int(cb.data.split(":", 2)[2])
    article = await faq_db.get_article(article_id)
    if not article or not article.get("is_published"):
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    await safe_cb_answer(cb)
    await _open_faq_article(
        cb.message.bot,
        cb.message.chat.id,
        article,
        from_faq=True,
        fallback_delete_msg=cb.message,
    )