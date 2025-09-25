from aiogram import Router, F, types
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from bot.config import get_settings, now_utc_str
from bot.services.db import get_db

router = Router(name="admin_reply")

from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
)


class ReplyForm(StatesGroup):
    waiting_text = State()


@router.callback_query(F.data.startswith("adm_reply:"))
async def adm_reply_start(cb: types.CallbackQuery, state: FSMContext):
    # мгновенно гасим крутилку
    try:
        await cb.answer()
    except Exception:
        pass

    # парсим tg_id из callback_data
    try:
        tg_id = int(cb.data.split("adm_reply:", 1)[1])
    except Exception:
        await cb.message.answer("Ошибка кнопки.")
        return

    await state.set_state(ReplyForm.waiting_text)
    await state.update_data(tg_id=tg_id)
    await cb.message.answer(f"Напиши ответ для пользователя (tg_id {tg_id}).")

    # отмечаем открытый запрос как 'answered'
    async with get_db() as db:
        await db.execute(
            """
            UPDATE help_requests
            SET status='answered', answered_at=?
            WHERE student_id = (SELECT id FROM students WHERE tg_id=?)
              AND status='open'
            """,
            (now_utc_str(), tg_id),
        )
        await db.commit()


@router.message(ReplyForm.waiting_text, F.text)
async def adm_reply_send(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tg_id = data.get("tg_id")
    if not tg_id:
        await message.answer("Студент не найден."); await state.clear(); return

    try:
        await message.bot.send_message(tg_id, f"✉️ Ответ от куратора:\n\n{message.text}")
        await message.answer("✅ Ответ отправлен.")
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить: {e}")
    finally:
        await state.clear()