"""Политика проекта: ссылки на юридические документы."""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from .keyboards import project_policy_kb
from .messages import project_policy_text
from .ui_helpers import safe_cb_answer, send_or_edit

router = Router()


@router.callback_query(F.data == "project_policy")
async def cb_project_policy(cb: CallbackQuery):
    await safe_cb_answer(cb)
    await send_or_edit(cb, project_policy_text(), project_policy_kb())