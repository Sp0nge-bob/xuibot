from config.settings import settings


def is_admin(user_id: int) -> bool:
    return user_id in settings.BOT_ADMINS


def is_debug_admin(user_id: int) -> bool:
    return is_admin(user_id) and settings.ALLOW_DEBUG_ADMIN