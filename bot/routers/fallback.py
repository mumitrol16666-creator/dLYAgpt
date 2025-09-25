# bot/routers/fallback.py
import random
from aiogram import Router, types, F
from aiogram.filters import StateFilter
from bot.keyboards.student import student_main_kb

router = Router(name="fallback")

_fun_replies = [
    "Это конечно сильно... но давай по делу 😅",
    "Я музыкант - енот, а не психотерапевт 🙃",
    "Сначала урок сдай, потом поговорим 🎸",
    "Если это аккорд — я его не знаю 😂",
    "Ну ты понял... жми кнопки, а не сюда пиши 👇",
    "Маестрофф уронил медиатор, подожди, я его найду...",
    "Я же бот, а не твоя бабушка 🤨",
]

# --- ЕДИНЫЙ ОБРАБОТЧИК ДЛЯ НЕПОНЯТНОГО ТЕКСТА ---
@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def unified_fallback_text(m: types.Message):
    # Отвечаем шуткой с вероятностью 35%
    if random.random() < 0.35:
        await m.answer(random.choice(_fun_replies))
    else:
        # В остальных случаях отвечаем стандартно
        await m.answer("Не понял. Нажми /start или выбери пункт меню.", reply_markup=student_main_kb())

# --- ЕДИНЫЙ ОБРАБОТЧИК ДЛЯ НЕАКТИВНЫХ КНОПОК ---
@router.callback_query(StateFilter(None))
async def fallback_cb_unified(cb: types.CallbackQuery):
    # Мы можем просто ловить ВСЕ колбэки без состояния,
    # так как все "рабочие" колбэки должны быть в других роутерах,
    # которые стоят раньше в main.py.
    # Это надежнее, чем перечислять все префиксы.
    await cb.answer("Эта кнопка больше не активна.", show_alert=False)