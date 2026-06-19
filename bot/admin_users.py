"""Хелперы списка подключённых пользователей в админке."""
from typing import Any

from config.trial import is_trial_email
from services.subscription_labels import subscription_short_label


def group_subscriptions_by_tg(users: list[dict[str, Any]]) -> dict[int, list[dict]]:
    by_tg: dict[int, list[dict]] = {}
    for u in users:
        by_tg.setdefault(u["tg_id"], []).append(u)
    return by_tg


def unique_tg_users_from_subs(users: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tg = group_subscriptions_by_tg(users)
    result: list[dict[str, Any]] = []
    for tg_id, subs in by_tg.items():
        subs_sorted = sorted(subs, key=lambda s: s.get("end_date") or "", reverse=True)
        top = subs_sorted[0]
        result.append({
            "tg_id": tg_id,
            "username": top.get("username"),
            "first_name": top.get("first_name"),
            "end_date": top["end_date"],
            "sub_count": len(subs),
        })
    result.sort(key=lambda u: u.get("end_date") or "", reverse=True)
    return result


def split_connected_users(users: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    paid: list[dict] = []
    trial: list[dict] = []
    for u in users:
        if is_trial_email(u.get("client_email")):
            trial.append(u)
        else:
            paid.append(u)
    return paid, trial


def tg_user_label(u: dict[str, Any]) -> str:
    label = u.get("username") or u.get("first_name") or str(u["tg_id"])
    if u.get("username"):
        label = f"@{u['username']}"
    return label


def admin_users_menu_text(*, paid_count: int, trial_count: int) -> str:
    return (
        "👥 <b>Подключённые клиенты</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"✅ Платные: <b>{paid_count}</b> польз.\n"
        f"🎁 Пробные: <b>{trial_count}</b> польз.\n\n"
        "Выберите категорию или воспользуйтесь поиском."
    )


def admin_users_category_text(
    *,
    category: str,
    users: list[dict],
    limit: int,
) -> str:
    title = "✅ Платные клиенты" if category == "paid" else "🎁 Пробные клиенты"
    lines = [title, "━━━━━━━━━━━━━━━━", ""]
    if not users:
        lines.append("В этой категории активных клиентов нет.")
    else:
        lines.append(f"Показано: <b>{len(users)}</b> (до {limit} последних по сроку)")
    return "\n".join(lines)


def admin_user_subs_text(*, label: str, tg_id: int, subs: list[dict]) -> str:
    lines = [
        "👤 <b>Выбор подписки</b>",
        "━━━━━━━━━━━━━━━━",
        "",
        f"Клиент: {label}",
        f"TG ID: <code>{tg_id}</code>",
        "",
        f"Активных подписок: <b>{len(subs)}</b>",
        "",
        "Выберите подписку:",
    ]
    return "\n".join(lines)


def admin_users_search_text(query: str, users: list[dict]) -> str:
    lines = [
        f"🔍 <b>Найдено: {len(users)}</b>",
        f"Запрос: <code>{query}</code>",
        "",
    ]
    if not users:
        lines.append("Активных клиентов не найдено.")
    else:
        lines.append("Выберите клиента:")
    return "\n".join(lines)


def subscription_picker_button_label(sub: dict[str, Any]) -> str:
    end = (sub.get("end_date") or "")[:10]
    name = subscription_short_label(sub)
    email = sub.get("client_email") or ""
    if len(email) > 14:
        email = email[:11] + "..."
    return f"{name} · {email} · {end}"


def subscription_kind_label(client_email: str | None) -> str:
    return "🎁 Пробная" if is_trial_email(client_email) else "✅ Платная"