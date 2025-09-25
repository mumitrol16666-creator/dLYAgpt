from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def _b(n: int) -> str:
    return f" ({n})" if n else ""

def admin_main_reply_kb(queue: int = 0, pay_pending: int = 0, onb_pending: int = 0, students_total: int = 0) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text=f"🗂 Очередь{_b(queue)}")],
            [KeyboardButton(text=f"👥 Ученики{_b(students_total)}")],  # ← добавили счётчик здесь
            [KeyboardButton(text="💳 Платежи")],
            [KeyboardButton(text=f"🧾 Заявки на оплату{_b(pay_pending)}")],
            [KeyboardButton(text=f"📝 Анкеты (модерация){_b(onb_pending)}")],
            [KeyboardButton(text="📣 Рассылка")],
            [KeyboardButton(text="🚪 Выйти из админ-режима")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Админ-меню",
        selective=True,
    )
