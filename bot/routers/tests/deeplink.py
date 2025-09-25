# bot/routers/tests/deeplink.py
from aiogram import Router, types
from aiogram.fsm.context import FSMContext  # <-- Добавлен импорт
from bot.services.tests.registry import get_test
from bot.routers.tests.engine import start_test_quiz

router = Router(name="deeplink")

@router.message(lambda m: m.text and m.text.startswith("/start"))
async def start_with_payload(m: types.Message, state: FSMContext):  # <-- Добавлен параметр state
    parts = m.text.split(maxsplit=1)
    payload = parts[1] if len(parts) > 1 else ""
    meta = get_test(payload)
    if meta:
        await start_test_quiz(m, m.from_user.id, meta, state)  # <-- Передача state
    else:
        await m.answer("Жми «🧠 Тесты по теории», чтобы начать.")