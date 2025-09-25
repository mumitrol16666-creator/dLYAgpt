# bot/routers/debug.py
from __future__ import annotations
import logging, json
from aiogram import Router, types

router = Router(name="debug")

# 1) Ловим ЛЮБЫЕ сообщения, которые не перехватили твои хендлеры
@router.message()
async def debug_unhandled_message(message: types.Message):
    try:
        logging.warning("UNHANDLED MESSAGE: %s", message.model_dump_json())
    except Exception:
        logging.warning("UNHANDLED MESSAGE (fallback): %s", message)

# 2) Ловим ЛЮБЫЕ callback_query (кнопки), не перехваченные раньше
@router.callback_query()
async def debug_unhandled_callback(cb: types.CallbackQuery):
    logging.warning("UNHANDLED CALLBACK: data=%r chat=%s from=%s",
                    cb.data, getattr(cb.message, 'chat', None), cb.from_user.id)
    await cb.answer("Команда не распознана. Сообщение записано в журнал.", show_alert=False)

# 3) Ловим ошибки из любых хендлеров (если внутри что-то упало)
try:
    from aiogram.types.error_event import ErrorEvent

    @router.errors()
    async def debug_errors(event: ErrorEvent):
        logging.exception("HANDLER ERROR on update=%s", event.update, exc_info=event.exception)
        # Мягко уведомим пользователя, если это сообщение, а не, например, callback без message
        msg = getattr(event.update, "message", None)
        if isinstance(msg, types.Message):
            await msg.answer("Упс, что-то сломалось. Уже чиним 🔧")
        # вернуть True/None — чтобы ошибка считалась обработанной
        return True
except Exception:
    # Если в твоей версии aiogram нет ErrorEvent — просто пропустим этот блок.
    pass
