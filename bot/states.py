from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    waiting_promo_code = State()
    waiting_sub_display_name = State()
    waiting_sub_rename = State()
    waiting_sub_email_search = State()
    in_ticket_chat = State()


class AdminStates(StatesGroup):
    waiting_inbounds = State()
    waiting_user_search = State()
    in_ticket_chat = State()
    waiting_trial_reset = State()
    waiting_node_name = State()
    waiting_node_host = State()
    waiting_node_token = State()
    waiting_node_login = State()
    waiting_node_password = State()
    waiting_node_inbounds = State()
    waiting_start_announcement = State()
    waiting_start_greeting = State()
    waiting_faq_title = State()
    waiting_faq_body = State()
    waiting_faq_photos = State()
    waiting_faq_edit_title = State()
    waiting_faq_edit_body = State()
    waiting_faq_add_photos = State()
    waiting_trial_limit_ip = State()
    waiting_paid_limit_ip = State()
    waiting_privacy_policy_url = State()
    waiting_terms_of_service_url = State()
    waiting_backup_interval = State()
    waiting_lockdown_whitelist = State()
    in_order_user_message = State()


class AdminPricingStates(StatesGroup):
    waiting_plan_price = State()
    waiting_promo_code = State()
    waiting_promo_discount = State()
    waiting_promo_max_uses = State()
    waiting_promo_per_user = State()
    waiting_promo_valid_days = State()