from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardMarkup,InlineKeyboardMarkup



def student_main_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    # <<< НОВОЕ ГЛАВНОЕ МЕНЮ >>>
    kb.button(text="🎓 Программа обучения")
    kb.button(text="🎵 Уроки по коду")
    kb.button(text="📈 Мой прогресс")
    kb.button(text="🆘 Помощь")
    kb.button(text="ℹ️ О курсе")
    kb.button(text="💳 Оплатить") # Оставляем для оплаты курсов
    kb.adjust(2, 2, 2) # Новая раскладка
    return kb.as_markup(resize_keyboard=True)

# <<< ИЗМЕНЕНИЕ: Добавляем course_code_to_pay >>>
def payment_inline(payment_link: str, course_code_to_pay: str, include_i_paid: bool = True, student_id: int | None = None) -> InlineKeyboardMarkup:
    ib = InlineKeyboardBuilder()
    if payment_link:
        ib.button(text="Перейти к оплате", url=payment_link)
    if include_i_paid and student_id is not None:
        # <<< ИЗМЕНЕНИЕ: Вшиваем код курса в callback_data >>>
        ib.button(text="Я оплатил", callback_data=f"paid_ipaid:{course_code_to_pay}:{student_id}")
    ib.adjust(1)
    return ib.as_markup()

def next_t_inline(progress_id: int, has_next: bool):
    kb = InlineKeyboardBuilder()
    if has_next:
        kb.button(text="▶️ Следующий раздел", callback_data=f"next_t:{progress_id}")
    else:
        kb.button(text="✅ Сдать урок", callback_data=f"submit_start:{progress_id}")
    kb.adjust(1)
    return kb.as_markup()


