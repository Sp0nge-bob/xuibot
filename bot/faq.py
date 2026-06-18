"""FAQ для клиентов."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db import faq as faq_db
from .faq_delivery import send_activation_setup_faq, send_faq_article
from .keyboards import faq_article_nav_kb, faq_list_kb
from .messages import faq_empty_text, faq_menu_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


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
    await safe_cb_answer(cb)
    articles = await faq_db.list_articles(published_only=True)
    if not articles:
        await send_or_edit(cb, faq_empty_text(), faq_list_kb([]))
        return
    await send_or_edit(cb, faq_menu_text(len(articles)), faq_list_kb(articles))


@router.callback_query(F.data.startswith("faq:article:"))
async def cb_faq_article(cb: CallbackQuery):
    article_id = int(cb.data.split(":", 2)[2])
    article = await faq_db.get_article(article_id)
    if not article or not article.get("is_published"):
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    photos = await faq_db.list_photos(article_id)
    await safe_cb_answer(cb)
    try:
        await cb.message.delete()
    except Exception:
        pass
    bot = cb.message.bot
    chat_id = cb.message.chat.id
    nav = faq_article_nav_kb()
    if faq_db.is_activation_faq_article(article):
        await send_activation_setup_faq(bot, chat_id, article, reply_markup=nav)
    else:
        await send_faq_article(bot, chat_id, article, photos, reply_markup=nav)