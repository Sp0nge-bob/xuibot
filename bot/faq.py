"""FAQ для клиентов."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import faq as faq_db
from .faq_album import clear_faq_album, set_faq_album_message_ids
from .faq_delivery import send_activation_setup_faq, send_faq_article
from .keyboards import faq_article_nav_kb, faq_list_kb
from .messages import faq_empty_text, faq_menu_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


async def _open_faq_article(
    bot,
    chat_id: int,
    article: dict,
) -> None:
    photos = await faq_db.list_photos(article["id"])
    await clear_faq_album(bot, chat_id)
    nav = faq_article_nav_kb()
    if faq_db.is_activation_faq_article(article):
        album_ids = await send_activation_setup_faq(
            bot, chat_id, article, reply_markup=nav,
        )
    else:
        album_ids = await send_faq_article(
            bot, chat_id, article, photos, reply_markup=nav,
        )
    set_faq_album_message_ids(chat_id, album_ids)


async def show_faq_menu_message(message: Message) -> None:
    articles = await faq_db.list_articles(published_only=True)
    if not articles:
        await message.answer(faq_empty_text(), reply_markup=faq_list_kb([]))
        return
    await message.answer(faq_menu_text(len(articles)), reply_markup=faq_list_kb(articles))


@router.message(Command("faq"))
async def cmd_faq(message: Message, state: FSMContext):
    await state.set_state(None)
    await show_faq_menu_message(message)


@router.callback_query(F.data == "faq_menu")
async def cb_faq_menu(cb: CallbackQuery):
    await clear_faq_album(cb.bot, cb.message.chat.id)
    await safe_cb_answer(cb)
    articles = await faq_db.list_articles(published_only=True)
    if not articles:
        await send_or_edit(cb, faq_empty_text(), faq_list_kb([]))
        return
    await send_or_edit(cb, faq_menu_text(len(articles)), faq_list_kb(articles))


@router.callback_query(F.data == "faq:builtin:activation")
async def cb_faq_builtin_activation(cb: CallbackQuery):
    article = await faq_db.get_article_by_builtin(faq_db.BUILTIN_ACTIVATION_KEY)
    if not article:
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    await safe_cb_answer(cb)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await _open_faq_article(cb.message.bot, cb.message.chat.id, article)


@router.callback_query(F.data.startswith("faq:article:"))
async def cb_faq_article(cb: CallbackQuery):
    article_id = int(cb.data.split(":", 2)[2])
    article = await faq_db.get_article(article_id)
    if not article or not article.get("is_published"):
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    await safe_cb_answer(cb)
    try:
        await cb.message.delete()
    except Exception:
        pass
    await _open_faq_article(cb.message.bot, cb.message.chat.id, article)