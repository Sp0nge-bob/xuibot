"""Тесты для просмотра истории сообщений и вложений в тикетах (админ и пользователь)."""
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import db.connection as db_conn
import db.database as db_mod
import db.tickets as tickets_db
import db.xui_nodes as xui_nodes_mod
from bot.admin_keyboards import (
    admin_ticket_detail_kb,
    admin_ticket_history_kb,
    admin_ticket_session_kb,
    admin_tickets_filter_kb,
)
from bot.keyboards import ticket_history_kb, ticket_session_kb, ticket_view_kb
from bot.ticket_chat import (
    format_ticket_message_snippet,
    format_ticket_message_time,
    render_ticket_history_text,
)


@pytest.fixture(autouse=True)
async def _setup_isolated_bot_db(monkeypatch):
    tmp_dir = Path(__file__).resolve().parent.parent / ".test_tmp"
    tmp_dir.mkdir(exist_ok=True)
    db_file = tmp_dir / f"tickets_test_{uuid.uuid4().hex}.db"
    await db_conn.close_connection()
    monkeypatch.setattr(db_conn, "DB_PATH", str(db_file))
    monkeypatch.setattr(db_mod, "DB_PATH", str(db_file))
    monkeypatch.setattr(xui_nodes_mod, "_INIT_DONE", False)
    monkeypatch.setattr(xui_nodes_mod, "_INIT_IN_PROGRESS", False)
    import services.crypto as crypto_mod
    from config.settings import settings
    monkeypatch.setattr(crypto_mod, "_cached_fernet", None)
    monkeypatch.setattr(crypto_mod, "_cached_candidates", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "pentest_test_secret_key_32chars_long_123456")
    await db_mod.init_db()
    await tickets_db.init_tickets_tables()
    try:
        yield
    finally:
        await db_conn.close_connection()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_file}{suffix}").unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_tickets_db_message_counting_and_retrieval():
    """Тест подсчёта сообщений, медиавложений и постраничной выборки."""
    tg_id = 999001
    ticket_id = await tickets_db.create_ticket(tg_id=tg_id, category=tickets_db.CATEGORY_SUPPORT)

    assert await tickets_db.count_messages_for_ticket(ticket_id) == 0
    assert await tickets_db.count_media_messages_for_ticket(ticket_id) == 0

    # Добавляем 5 сообщений: 4 текстовых и 1 фото
    await tickets_db.add_ticket_message(
        ticket_id=ticket_id,
        sender_tg_id=tg_id,
        is_admin=False,
        content_type="text",
        body="Привет, есть вопрос",
    )
    await tickets_db.add_ticket_message(
        ticket_id=ticket_id,
        sender_tg_id=1001,
        is_admin=True,
        content_type="text",
        body="Здравствуйте, слушаю вас",
    )
    await tickets_db.add_ticket_message(
        ticket_id=ticket_id,
        sender_tg_id=tg_id,
        is_admin=False,
        content_type="photo",
        body="Скриншот проблемы",
        file_id="photo_file_123",
    )
    await tickets_db.add_ticket_message(
        ticket_id=ticket_id,
        sender_tg_id=1001,
        is_admin=True,
        content_type="text",
        body="Понял, сейчас проверю",
    )
    await tickets_db.add_ticket_message(
        ticket_id=ticket_id,
        sender_tg_id=tg_id,
        is_admin=False,
        content_type="text",
        body="Спасибо!",
    )

    assert await tickets_db.count_messages_for_ticket(ticket_id) == 5
    assert await tickets_db.count_media_messages_for_ticket(ticket_id) == 1

    # Проверка получения последних 3 сообщений
    recent = await tickets_db.get_recent_ticket_messages(ticket_id, limit=3)
    assert len(recent) == 3
    assert recent[0]["content_type"] == "photo"
    assert recent[1]["body"] == "Понял, сейчас проверю"
    assert recent[2]["body"] == "Спасибо!"

    # Проверка пагинации get_ticket_messages
    page1 = await tickets_db.get_ticket_messages(ticket_id, limit=2, offset=0, descending=False)
    assert len(page1) == 2
    assert page1[0]["body"] == "Привет, есть вопрос"
    assert page1[1]["body"] == "Здравствуйте, слушаю вас"

    page2 = await tickets_db.get_ticket_messages(ticket_id, limit=2, offset=2, descending=False)
    assert len(page2) == 2
    assert page2[0]["content_type"] == "photo"
    assert page2[1]["body"] == "Понял, сейчас проверю"

    # Проверка получения только медиа
    media = await tickets_db.get_ticket_media_messages(ticket_id)
    assert len(media) == 1
    assert media[0]["file_id"] == "photo_file_123"
    assert media[0]["content_type"] == "photo"


@pytest.mark.asyncio
async def test_tickets_db_closed_tickets_listing():
    """Тест списка закрытых тикетов."""
    tg_id = 999002
    t1 = await tickets_db.create_ticket(tg_id=tg_id, category=tickets_db.CATEGORY_OTHER)
    t2 = await tickets_db.create_ticket(tg_id=tg_id, category=tickets_db.CATEGORY_SUPPORT)

    open_rows = await tickets_db.get_open_tickets()
    open_ids = [r["id"] for r in open_rows]
    assert t1 in open_ids and t2 in open_ids

    # Закрываем t1
    await tickets_db.close_ticket(t1)
    closed_rows = await tickets_db.get_closed_tickets()
    closed_ids = [r["id"] for r in closed_rows]
    assert t1 in closed_ids
    assert t2 not in closed_ids


def test_format_ticket_message_time():
    assert format_ticket_message_time(None) == "—"
    assert format_ticket_message_time("2026-11-06 04:55:12") == "06.11 04:55"
    assert format_ticket_message_time("2026-11-06T04:55:12") == "06.11 04:55"


def test_format_ticket_message_snippet_html_escaping_and_types():
    # Текстовое сообщение с XSS-нагрузкой
    msg_xss = {
        "is_admin": 0,
        "content_type": "text",
        "body": "<script>alert('xss')</script> & <b>жирный</b>",
        "created_at": "2026-11-06 04:55:00",
    }
    snippet_user = format_ticket_message_snippet(msg_xss, viewer_is_admin=True, ticket_user_label="@test_user")
    assert "<script>" not in snippet_user
    assert "&lt;script&gt;" in snippet_user
    assert "<b>жирный</b>" not in snippet_user
    assert "&lt;b&gt;жирный&lt;/b&gt;" in snippet_user
    assert "@test_user" in snippet_user

    # Сообщение администратора
    msg_admin = {
        "is_admin": 1,
        "content_type": "text",
        "body": "Ответ поддержки",
        "created_at": "2026-11-06 04:56:00",
    }
    snippet_adm = format_ticket_message_snippet(msg_admin, viewer_is_admin=False)
    assert "Администратор" in snippet_adm
    assert "Ответ поддержки" in snippet_adm

    # Вложение (фото)
    msg_photo = {
        "is_admin": 0,
        "content_type": "photo",
        "body": "Скрин <em>ошибки</em>",
        "created_at": "2026-11-06 04:57:00",
    }
    snippet_photo = format_ticket_message_snippet(msg_photo, viewer_is_admin=True, ticket_user_label="@client")
    assert "📷 Фото" in snippet_photo
    assert "<em>" not in snippet_photo
    assert "&lt;em&gt;" in snippet_photo


def test_render_ticket_history_text_pagination_and_escaping():
    ticket = {
        "id": 4,
        "category": "other",
        "status": "open",
        "tg_id": 8613999894,
    }
    # Пустая история
    empty_res = render_ticket_history_text(
        ticket, [], page=1, total_pages=1, total_count=0, viewer_is_admin=True
    )
    assert "В этом тикете пока нет сообщений" in empty_res

    # История с сообщениями
    messages = [
        {
            "is_admin": 0,
            "content_type": "text",
            "body": "<script>alert(1)</script> Ошибка подключения",
            "created_at": "2026-11-06 04:55:00",
        },
        {
            "is_admin": 1,
            "content_type": "text",
            "body": "Проверьте профиль",
            "created_at": "2026-11-06 04:56:00",
        },
    ]
    res = render_ticket_history_text(
        ticket,
        messages,
        page=1,
        total_pages=2,
        total_count=10,
        viewer_is_admin=True,
        ticket_user_label="@xoxo_kissed_hugs",
    )
    assert "Тикет #4" in res
    assert "Страница <b>1 из 2</b>" in res
    assert "сообщений: <b>10</b>" in res
    assert "<script>" not in res
    assert "&lt;script&gt;" in res
    assert "@xoxo_kissed_hugs" in res
    assert "Администратор" in res


def test_keyboards_include_history_buttons():
    # Admin detail keyboard: без сообщений
    kb_no_msg = admin_ticket_detail_kb(4, category="other", is_open=True, msg_count=0)
    texts_no_msg = [btn.text for row in kb_no_msg.inline_keyboard for btn in row]
    assert not any("Вся переписка" in t for t in texts_no_msg)

    # Admin detail keyboard: с сообщениями и медиа
    kb_with_msg = admin_ticket_detail_kb(4, category="other", is_open=True, msg_count=5, has_media=True)
    texts_with_msg = [btn.text for row in kb_with_msg.inline_keyboard for btn in row]
    assert any("Вся переписка (5)" in t for t in texts_with_msg)
    assert any("Медиафайлы" in t for t in texts_with_msg)

    # Admin history keyboard
    hist_kb = admin_ticket_history_kb(4, page=2, total_pages=3, is_open=True, has_media=True)
    hist_callbacks = [btn.callback_data for row in hist_kb.inline_keyboard for btn in row]
    assert "adm:ticket:hist:4:1" in hist_callbacks  # Ранее
    assert "adm:ticket:hist:4:3" in hist_callbacks  # Позже
    assert "adm:ticket:media:4" in hist_callbacks
    assert "adm:ticket:session:4" in hist_callbacks

    # Admin session keyboard
    sess_kb = admin_ticket_session_kb(4)
    sess_callbacks = [btn.callback_data for row in sess_kb.inline_keyboard for btn in row]
    assert "adm:ticket:hist:4:1" in sess_callbacks

    # Admin tickets filter keyboard
    filt_kb = admin_tickets_filter_kb()
    filt_callbacks = [btn.callback_data for row in filt_kb.inline_keyboard for btn in row]
    assert "adm:tickets:closed" in filt_callbacks

    # User keyboards
    u_view_kb = ticket_view_kb(4, is_open=True, msg_count=3)
    u_view_texts = [btn.text for row in u_view_kb.inline_keyboard for btn in row]
    assert any("Вся переписка" in t for t in u_view_texts)

    u_hist_kb = ticket_history_kb(4, page=1, total_pages=2, is_open=True)
    u_hist_callbacks = [btn.callback_data for row in u_hist_kb.inline_keyboard for btn in row]
    assert "ticket_history:4:2" in u_hist_callbacks

    u_sess_kb = ticket_session_kb(4)
    u_sess_callbacks = [btn.callback_data for row in u_sess_kb.inline_keyboard for btn in row]
    assert "ticket_history:4:1" in u_sess_callbacks


@pytest.mark.asyncio
async def test_admin_and_user_ticket_history_callbacks(monkeypatch):
    """Интеграционный тест вызова хендлеров cb_admin_ticket_history и cb_ticket_history."""
    import bot.admin as admin_mod
    from bot.admin_tickets import cb_admin_ticket_detail, cb_admin_ticket_history
    from bot.tickets import cb_ticket_history, cb_ticket_view

    admin_id = 1001
    user_id = 999003
    monkeypatch.setattr(admin_mod, "is_admin", lambda uid: uid == admin_id)

    ticket_id = await tickets_db.create_ticket(tg_id=user_id, category=tickets_db.CATEGORY_OTHER)
    await tickets_db.add_ticket_message(
        ticket_id=ticket_id,
        sender_tg_id=user_id,
        is_admin=False,
        content_type="text",
        body="Здравствуйте, помогите настроить VPN",
    )

    # 1. Admin ticket detail
    cb_msg = AsyncMock()
    cb_adm = SimpleNamespace(
        from_user=SimpleNamespace(id=admin_id, username="adm", first_name="Admin"),
        data=f"adm:ticket:{ticket_id}",
        message=cb_msg,
        answer=AsyncMock(),
    )
    state = AsyncMock()
    await cb_admin_ticket_detail(cb_adm, state)
    assert cb_msg.edit_text.called or cb_msg.answer.called
    sent_text = (cb_msg.edit_text.call_args or cb_msg.answer.call_args)[0][0]
    assert "Здравствуйте, помогите настроить VPN" in sent_text
    assert "Сообщение:" in sent_text

    # 2. Admin ticket history
    cb_msg.reset_mock()
    cb_hist = SimpleNamespace(
        from_user=SimpleNamespace(id=admin_id, username="adm", first_name="Admin"),
        data=f"adm:ticket:hist:{ticket_id}:1",
        message=cb_msg,
        answer=AsyncMock(),
    )
    await cb_admin_ticket_history(cb_hist)
    assert cb_msg.edit_text.called or cb_msg.answer.called
    sent_hist = (cb_msg.edit_text.call_args or cb_msg.answer.call_args)[0][0]
    assert "История переписки: Тикет #" in sent_hist
    assert "Здравствуйте, помогите настроить VPN" in sent_hist

    # 3. User ticket view
    cb_user_msg = AsyncMock()
    cb_u_view = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username="usr", first_name="User"),
        data=f"ticket_view:{ticket_id}",
        message=cb_user_msg,
        answer=AsyncMock(),
    )
    await cb_ticket_view(cb_u_view, state)
    assert cb_user_msg.edit_text.called or cb_user_msg.answer.called
    user_sent_text = (cb_user_msg.edit_text.call_args or cb_user_msg.answer.call_args)[0][0]
    assert "Здравствуйте, помогите настроить VPN" in user_sent_text

    # 4. User ticket history
    cb_user_msg.reset_mock()
    cb_u_hist = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id, username="usr", first_name="User"),
        data=f"ticket_history:{ticket_id}:1",
        message=cb_user_msg,
        answer=AsyncMock(),
    )
    await cb_ticket_history(cb_u_hist)
    assert cb_user_msg.edit_text.called or cb_user_msg.answer.called
    user_hist_text = (cb_user_msg.edit_text.call_args or cb_user_msg.answer.call_args)[0][0]
    assert "История переписки: Тикет #" in user_hist_text
    assert "Здравствуйте, помогите настроить VPN" in user_hist_text
