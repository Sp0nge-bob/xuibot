"""Хелперы списка подключённых подписок в админке."""
from typing import Any

from config.trial import is_trial_email


def split_connected_users(users: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    paid: list[dict] = []
    trial: list[dict] = []
    for u in users:
        if is_trial_email(u.get("client_email")):
            trial.append(u)
        else:
            paid.append(u)
    return paid, trial


def admin_users_menu_text(*, paid_count: int, trial_count: int) -> str:
    return (
        "👥 <b>Подключённые подписки</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"✅ Платные: <b>{paid_count}</b>\n"
        f"🎁 Пробные: <b>{trial_count}</b>\n\n"
        "Выберите категорию или воспользуйтесь поиском."
    )


def admin_users_category_text(
    *,
    category: str,
    users: list[dict],
    limit: int,
) -> str:
    title = "✅ Платные подписки" if category == "paid" else "🎁 Пробные подписки"
    lines = [title, "━━━━━━━━━━━━━━━━", ""]
    if not users:
        lines.append("В этой категории активных подписок нет.")
    else:
        lines.append(f"Показано: <b>{len(users)}</b> (до {limit} последних по сроку)")
    return "\n".join(lines)


def admin_users_search_text(
    query: str,
    paid: list[dict],
    trial: list[dict],
) -> str:
    total = len(paid) + len(trial)
    lines = [
        f"🔍 <b>Найдено: {total}</b>",
        f"Запрос: <code>{query}</code>",
        "",
    ]
    if paid:
        lines += [f"✅ <b>Платные</b> — {len(paid)}:", ""]
        for u in paid:
            lines.append(_user_search_line(u))
        lines.append("")
    if trial:
        lines += [f"🎁 <b>Пробные</b> — {len(trial)}:", ""]
        for u in trial:
            lines.append(_user_search_line(u))
        lines.append("")
    if not paid and not trial:
        lines.append("Активных подписок не найдено.")
    else:
        lines.append("Выберите подписку:")
    return "\n".join(lines).rstrip()


def _user_search_line(u: dict) -> str:
    label = u.get("username") or u.get("first_name") or str(u["tg_id"])
    if u.get("username"):
        label = f"@{u['username']}"
    return f"• {label} · <code>{u['client_email']}</code> · до {u['end_date'][:10]}"


def subscription_kind_label(client_email: str | None) -> str:
    return "🎁 Пробная" if is_trial_email(client_email) else "✅ Платная"