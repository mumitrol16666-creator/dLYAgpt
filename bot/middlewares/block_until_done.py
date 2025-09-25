# bot/middlewares/block_until_done.py
from aiogram.types import Message
from aiogram.dispatcher.middlewares.base import BaseMiddleware  # aiogram v3
from typing import Callable, Dict, Any, Awaitable
from bot.services.db import get_db
from aiogram.fsm.context import FSMContext


# Кнопки, которые всегда пропускаем
ALLOWED_TEXTS = {
    "🆘 Помощь", "SOS", "СОС",
    "🏅 Мой ранг", "🥇 Мой ранг", "Мой ранг",
    "🏆 Мой прогресс", "Мой прогресс",
    "ℹ️ О курсе", "О курсе",
    "💳 Оплатить", "Оплатить",
    "✅ Сдать урок", "Сдать урок",
    "📚 Новый урок",
}

class BlockUntilDoneMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        msg: Message = event

        # 0) Если мы в состоянии ожидания сдачи (FSM SubmitForm.waiting_work) — ничего не блокируем
        state: FSMContext | None = data.get("state")
        if state is not None:
            try:
                cur_state = await state.get_state()
                # Проверяем по имени состояния, чтобы не тянуть класс SubmitForm (без циклических импортов)
                if cur_state and cur_state.endswith("SubmitForm:waiting_work"):
                    return await handler(event, data)
            except Exception:
                pass

        state: FSMContext | None = data.get("state")
        if state:
            cur = await state.get_state()
            if cur:
                return await handler(event, data)

        # 1) Команды пропускаем
        if msg.text and msg.text.startswith(("/", ".")):
            return await handler(event, data)

        # 2) Разрешённые кнопки пропускаем
        if msg.text and msg.text.strip() in ALLOWED_TEXTS:
            return await handler(event, data)

        # 3) Если есть активный незавершённый урок — блокируем всё, кроме разрешённого
        async with get_db() as db:
            cur = await db.execute(
                """
                SELECT p.id, p.task_code
                FROM progress p
                JOIN students s ON s.id = p.student_id
                WHERE s.tg_id=? AND p.status IN ('sent','returned')
                ORDER BY p.id DESC
                LIMIT 1
                """,
                (msg.from_user.id,),
            )
            prow = await cur.fetchone()

        # Нет активного — пропускаем
        if not prow:
            return await handler(event, data)

        # Активный есть и он не завершён (не DONE) — блокируем
        if (prow["task_code"] or "") != "DONE":
            await msg.answer(
                "Я понимаю, что не терпится, но пожалуйста закончи все разделы текущего урока и нажми «✅ Сдать урок». "
                "Если нужна помощь — жми «🆘 Помощь»."
            )
            return

        # Урок помечен как DONE (завершён) — пропускаем дальше
        return await handler(event, data)
