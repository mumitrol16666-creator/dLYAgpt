from aiogram.fsm.state import StatesGroup, State

class TestsFlow(StatesGroup):
    MENU = State()      # пользователь в меню тестов (reply-клава скрыта)
    RUNNING = State()   # идёт сам квиз
