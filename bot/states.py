from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    waiting_promo_code = State()
    waiting_refund_reply = State()


class AdminStates(StatesGroup):
    waiting_inbounds = State()
    waiting_user_search = State()
    waiting_refund_reply = State()
    waiting_trial_reset = State()


class AdminPricingStates(StatesGroup):
    waiting_plan_price = State()
    waiting_promo_code = State()
    waiting_promo_discount = State()
    waiting_promo_max_uses = State()
    waiting_promo_per_user = State()
    waiting_promo_valid_days = State()