"""Параметры пробной подписки."""

TRIAL_PLAN_ID = "tgfree"
TRIAL_DAYS = 3
TRIAL_TRAFFIC_GB = 15
TRIAL_COOLDOWN_DAYS = 90


def trial_client_email(tg_id: int) -> str:
    return f"tgfree{tg_id}"


def is_trial_email(email: str | None) -> bool:
    return bool(email) and email.startswith("tgfree")