# bot/routers/tests/entry.py
from aiogram import Router, F, types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from bot.routers.tests.state import TestsFlow

from bot.keyboards.student import student_main_kb
from bot.services.tests.registry import get_tests, get_test
from bot.services.tests.progress import is_unlocked, user_passed_codes
from bot.routers.tests.engine import start_test_quiz

router = Router(name="tests_entry")


@router.message(F.text == "🧠 Тесты по теории")
async def tests_menu(m: types.Message, state: FSMContext):
    await state.set_state(TestsFlow.MENU)
    await m.answer("Выбери тест:", reply_markup=ReplyKeyboardRemove())

    kb = InlineKeyboardBuilder()
    all_tests = get_tests()
    passed_codes = await user_passed_codes(m.from_user.id)

    for t in all_tests:
        unlocked = is_unlocked(passed_codes, t.depends_on)
        passed = t.code in passed_codes

        if passed:
            text = f"✅ {t.title}"
        elif unlocked:
            text = f"▶️ {t.title}"
        else:
            text = f"🔒 {t.title}"

        if unlocked:
            kb.button(text=text, callback_data=f"tests:start:{t.code}")
        else:
            kb.button(text=text, callback_data=f"tests:locked:{t.code}")

    kb.adjust(1)

    kb.button(text="⏪ В главное меню", callback_data="tests:back")

    await m.answer("Список доступных тестов:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tests:start:"))
async def tests_start(cb: types.CallbackQuery, state: FSMContext):
    test_code = cb.data.split(":")[2]
    meta = get_test(test_code)

    if not meta:
        await cb.answer("Тест не найден.", show_alert=True)
        return

    passed_codes = await user_passed_codes(cb.from_user.id)
    unlocked = is_unlocked(passed_codes, meta.depends_on)

    if not unlocked:
        await cb.answer("Этот тест ещё не разблокирован!", show_alert=True)
        return

    await cb.answer()
    await start_test_quiz(cb.message, cb.from_user.id, meta, state)


@router.callback_query(F.data.startswith("tests:locked:"))
async def tests_locked(cb: types.CallbackQuery):
    await cb.answer("Сначала пройди предыдущий тест, чтобы открыть этот.", show_alert=True)


@router.callback_query(F.data == "tests:back")
async def tests_back(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Возвращаю в главное меню:", reply_markup=student_main_kb())
    await cb.answer()