# bot/routers/forms.py
from aiogram.fsm.state import StatesGroup, State

class HelpForm(StatesGroup):
    waiting_text = State()

class SubmitForm(StatesGroup):
    waiting_work = State()

# <<< ИЗМЕНЕНИЕ: Добавляем класс сюда
class LessonCodeForm(StatesGroup):
    waiting_code = State()