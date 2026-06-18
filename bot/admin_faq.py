"""Админка: FAQ-статьи (заголовок, текст, фото)."""
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from db import faq as faq_db
from .admin_auth import is_admin
from .admin_keyboards import (
    admin_faq_delete_confirm_kb,
    admin_faq_detail_kb,
    admin_faq_menu_kb,
    admin_faq_photos_kb,
    admin_faq_photos_manage_kb,
)
from .faq_delivery import send_faq_article
from .keyboards import faq_article_nav_kb
from .messages import (
    admin_faq_body_prompt_text,
    admin_faq_detail_text,
    admin_faq_edit_body_prompt_text,
    admin_faq_edit_title_prompt_text,
    admin_faq_menu_text,
    admin_faq_photos_prompt_text,
    admin_faq_title_prompt_text,
)
from .states import AdminStates
from .telegram_html import validate_telegram_html
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()

FAQ_TITLE_MAX = 80
FAQ_BODY_MAX = 4000
FAQ_PHOTOS_MAX = 10


async def _show_faq_admin_menu(target: CallbackQuery | Message) -> None:
    articles = await faq_db.list_articles()
    text = admin_faq_menu_text(articles)
    kb = admin_faq_menu_kb(articles)
    if isinstance(target, CallbackQuery):
        await send_or_edit(target, text, kb)
    else:
        await target.answer(text, reply_markup=kb)


async def _show_faq_detail(cb: CallbackQuery, article_id: int) -> None:
    article = await faq_db.get_article(article_id)
    if not article:
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    photos = await faq_db.list_photos(article_id)
    await send_or_edit(
        cb,
        admin_faq_detail_text(article, photo_count=len(photos)),
        admin_faq_detail_kb(article_id, is_published=bool(article.get("is_published"))),
    )


async def _cancel_to_admin(message: Message, state: FSMContext) -> bool:
    raw = message.text or ""
    if not raw.strip().startswith("/"):
        return False
    cmd = raw.strip().split()[0].split("@")[0].lower()
    if cmd != "/admin":
        await message.answer("Ввод отменён.")
        await state.set_state(None)
        return True
    await state.set_state(None)
    from bot.admin import _admin_menu_text, admin_menu_kb
    await message.answer(await _admin_menu_text(), reply_markup=admin_menu_kb())
    return True


async def _persist_draft_photos(article_id: int, file_ids: list[str]) -> int:
    added = 0
    existing = len(await faq_db.list_photos(article_id))
    for fid in file_ids:
        if existing + added >= FAQ_PHOTOS_MAX:
            break
        await faq_db.add_photo(article_id, fid)
        added += 1
    return added


@router.callback_query(F.data == "adm:faq")
async def cb_admin_faq_menu(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    await safe_cb_answer(cb)
    await _show_faq_admin_menu(cb)


@router.callback_query(F.data == "adm:faq:create")
async def cb_admin_faq_create(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(AdminStates.waiting_faq_title)
    await state.update_data(faq_photo_ids=[], faq_edit_article_id=None)
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_faq_title_prompt_text(), admin_faq_menu_kb([]))


@router.message(AdminStates.waiting_faq_title)
async def msg_admin_faq_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    title = (message.text or "").strip()
    if not title:
        await message.answer("Заголовок не может быть пустым.")
        return
    if len(title) > FAQ_TITLE_MAX:
        await message.answer(f"Слишком длинный заголовок (макс. {FAQ_TITLE_MAX} символов).")
        return
    await state.update_data(faq_draft_title=title)
    await state.set_state(AdminStates.waiting_faq_body)
    await message.answer(admin_faq_body_prompt_text(title=title))


@router.message(AdminStates.waiting_faq_body)
async def msg_admin_faq_body(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    body = (message.text or "").strip()
    if not body:
        await message.answer("Текст не может быть пустым.")
        return
    if len(body) > FAQ_BODY_MAX:
        await message.answer(f"Слишком длинный текст (макс. {FAQ_BODY_MAX} символов).")
        return
    err = validate_telegram_html(body)
    if err:
        await message.answer(f"❌ HTML: {err}")
        return
    await state.update_data(faq_draft_body=body, faq_photo_ids=[])
    await state.set_state(AdminStates.waiting_faq_photos)
    await message.answer(
        admin_faq_photos_prompt_text(count=0),
        reply_markup=admin_faq_photos_kb(create_mode=True),
    )


@router.message(AdminStates.waiting_faq_photos, F.photo)
@router.message(AdminStates.waiting_faq_add_photos, F.photo)
async def msg_admin_faq_photo(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    ids: list[str] = list(data.get("faq_photo_ids") or [])
    if len(ids) >= FAQ_PHOTOS_MAX:
        await message.answer(f"Максимум {FAQ_PHOTOS_MAX} фото.")
        return
    file_id = message.photo[-1].file_id
    ids.append(file_id)
    await state.update_data(faq_photo_ids=ids)
    create_mode = await state.get_state() == AdminStates.waiting_faq_photos.state
    await message.answer(
        admin_faq_photos_prompt_text(count=len(ids)),
        reply_markup=admin_faq_photos_kb(create_mode=create_mode),
    )


@router.message(AdminStates.waiting_faq_photos)
@router.message(AdminStates.waiting_faq_add_photos)
async def msg_admin_faq_photo_other(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    await message.answer("Отправьте фото или нажмите «Готово» / «Пропустить».")


@router.callback_query(F.data == "adm:faq:photos:skip")
@router.callback_query(F.data == "adm:faq:photos:done")
async def cb_admin_faq_photos_finish(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    data = await state.get_data()
    photo_ids: list[str] = list(data.get("faq_photo_ids") or [])
    article_id = data.get("faq_edit_article_id")

    if article_id:
        await state.set_state(None)
        added = await _persist_draft_photos(int(article_id), photo_ids)
        await safe_cb_answer(cb, f"Добавлено фото: {added}" if added else "Без изменений")
        photos = await faq_db.list_photos(int(article_id))
        if photos:
            await send_or_edit(
                cb,
                admin_faq_detail_text(
                    await faq_db.get_article(int(article_id)),
                    photo_count=len(photos),
                ),
                admin_faq_photos_manage_kb(int(article_id), photos),
            )
        else:
            await _show_faq_detail(cb, int(article_id))
        return

    title = (data.get("faq_draft_title") or "").strip()
    body = (data.get("faq_draft_body") or "").strip()
    if not title or not body:
        await safe_cb_answer(cb, "Черновик потерян — создайте заново", show_alert=True)
        await state.set_state(None)
        await _show_faq_admin_menu(cb)
        return

    new_id = await faq_db.create_article(title=title, body=body, is_published=True)
    await _persist_draft_photos(new_id, photo_ids)
    await state.set_state(None)
    await safe_cb_answer(cb, "Статья создана")
    await _show_faq_detail(cb, new_id)


@router.callback_query(F.data == "adm:faq:photos:cancel")
async def cb_admin_faq_photos_cancel(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    data = await state.get_data()
    article_id = data.get("faq_edit_article_id")
    await state.set_state(None)
    await safe_cb_answer(cb)
    if article_id:
        await _show_faq_detail(cb, int(article_id))
    else:
        await _show_faq_admin_menu(cb)


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:preview$"))
async def cb_admin_faq_preview(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    article_id = int(cb.data.split(":")[2])
    article = await faq_db.get_article(article_id)
    if not article:
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    photos = await faq_db.list_photos(article_id)
    await safe_cb_answer(cb, "Превью отправлено")
    await send_faq_article(
        cb.message.bot,
        cb.message.chat.id,
        article,
        photos,
        reply_markup=faq_article_nav_kb(),
    )


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:toggle$"))
async def cb_admin_faq_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    article_id = int(cb.data.split(":")[2])
    article = await faq_db.get_article(article_id)
    if not article:
        await safe_cb_answer(cb, "Статья не найдена", show_alert=True)
        return
    new_val = not bool(article.get("is_published"))
    await faq_db.update_article(article_id, is_published=new_val)
    await safe_cb_answer(cb, "Опубликована" if new_val else "Скрыта")
    await _show_faq_detail(cb, article_id)


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:del$"))
async def cb_admin_faq_delete(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    article_id = int(cb.data.split(":")[2])
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        f"⚠️ Удалить FAQ #{article_id}?",
        admin_faq_delete_confirm_kb(article_id),
    )


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:del:confirm$"))
async def cb_admin_faq_delete_confirm(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    article_id = int(cb.data.split(":")[2])
    await faq_db.delete_article(article_id)
    await state.set_state(None)
    await safe_cb_answer(cb, "Удалено")
    await _show_faq_admin_menu(cb)


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:photo_del:\d+$"))
async def cb_admin_faq_photo_delete(cb: CallbackQuery):
    if not is_admin(cb.from_user.id):
        return
    parts = cb.data.split(":")
    article_id = int(parts[2])
    photo_id = int(parts[4])
    await faq_db.delete_photo(photo_id)
    await safe_cb_answer(cb, "Фото удалено")
    photos = await faq_db.list_photos(article_id)
    article = await faq_db.get_article(article_id)
    if photos:
        await send_or_edit(
            cb,
            admin_faq_detail_text(article, photo_count=len(photos)),
            admin_faq_photos_manage_kb(article_id, photos),
        )
    elif article:
        await _show_faq_detail(cb, article_id)


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:photos$"))
async def cb_admin_faq_add_photos(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    article_id = int(cb.data.split(":")[2])
    photos = await faq_db.list_photos(article_id)
    if len(photos) >= FAQ_PHOTOS_MAX:
        await safe_cb_answer(cb, f"Уже {FAQ_PHOTOS_MAX} фото", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_faq_add_photos)
    await state.update_data(faq_edit_article_id=article_id, faq_photo_ids=[])
    await safe_cb_answer(cb)
    await send_or_edit(
        cb,
        admin_faq_photos_prompt_text(count=len(photos)),
        admin_faq_photos_kb(create_mode=False),
    )


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:title$"))
async def cb_admin_faq_edit_title(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    article_id = int(cb.data.split(":")[2])
    await state.set_state(AdminStates.waiting_faq_edit_title)
    await state.update_data(faq_edit_article_id=article_id)
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_faq_edit_title_prompt_text(), admin_faq_detail_kb(article_id, is_published=True))


@router.message(AdminStates.waiting_faq_edit_title)
async def msg_admin_faq_edit_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    title = (message.text or "").strip()
    if not title or len(title) > FAQ_TITLE_MAX:
        await message.answer(f"Нужен заголовок до {FAQ_TITLE_MAX} символов.")
        return
    data = await state.get_data()
    article_id = int(data["faq_edit_article_id"])
    await faq_db.update_article(article_id, title=title)
    await state.set_state(None)
    await message.answer("✅ Заголовок обновлён")
    article = await faq_db.get_article(article_id)
    photos = await faq_db.list_photos(article_id)
    await message.answer(
        admin_faq_detail_text(article, photo_count=len(photos)),
        reply_markup=admin_faq_detail_kb(article_id, is_published=bool(article.get("is_published"))),
    )


@router.callback_query(F.data.regexp(r"^adm:faq:\d+:body$"))
async def cb_admin_faq_edit_body(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    article_id = int(cb.data.split(":")[2])
    await state.set_state(AdminStates.waiting_faq_edit_body)
    await state.update_data(faq_edit_article_id=article_id)
    await safe_cb_answer(cb)
    await send_or_edit(cb, admin_faq_edit_body_prompt_text(), admin_faq_detail_kb(article_id, is_published=True))


@router.message(AdminStates.waiting_faq_edit_body)
async def msg_admin_faq_edit_body(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if await _cancel_to_admin(message, state):
        return
    body = (message.text or "").strip()
    if not body or len(body) > FAQ_BODY_MAX:
        await message.answer(f"Нужен текст до {FAQ_BODY_MAX} символов.")
        return
    err = validate_telegram_html(body)
    if err:
        await message.answer(f"❌ HTML: {err}")
        return
    data = await state.get_data()
    article_id = int(data["faq_edit_article_id"])
    await faq_db.update_article(article_id, body=body)
    await state.set_state(None)
    await message.answer("✅ Текст обновлён")
    article = await faq_db.get_article(article_id)
    photos = await faq_db.list_photos(article_id)
    await message.answer(
        admin_faq_detail_text(article, photo_count=len(photos)),
        reply_markup=admin_faq_detail_kb(article_id, is_published=bool(article.get("is_published"))),
    )


@router.callback_query(F.data.regexp(r"^adm:faq:\d+$"))
async def cb_admin_faq_detail(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        return
    await state.set_state(None)
    article_id = int(cb.data.split(":")[2])
    await safe_cb_answer(cb)
    await _show_faq_detail(cb, article_id)