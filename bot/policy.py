"""Политика проекта: ссылки на юридические документы."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from db import bot_settings as settings_db

from .keyboards import project_policy_kb
from .messages import project_policy_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


@router.callback_query(F.data == "project_policy")
async def cb_project_policy(cb: CallbackQuery):
    await safe_cb_answer(cb)
    privacy_url = await settings_db.get_privacy_policy_url()
    terms_url = await settings_db.get_terms_of_service_url()
    await send_or_edit(
        cb,
        project_policy_text(),
        project_policy_kb(privacy_url=privacy_url, terms_url=terms_url),
    )