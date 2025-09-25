from __future__ import annotations

import os
import random

from pathlib import Path

from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from bot.routers.lesson_flow import send_next_t_block

from bot.keyboards.student import student_main_kb, payment_inline, next_t_inline
from bot.config import get_settings, now_utc_str, local_dt_str
from bot.services.lessons import (
    list_l_lessons,
    next_l_after,
    list_t_blocks,
    sort_materials,
    parse_l_num,
)

from bot.services.lessons import list_l_lessons
from bot.config import get_course
from bot.services.admin_cards import render_submission_card
from bot.services import points
from bot.services.ranks import get_rank_by_points
from bot.routers.forms import HelpForm, SubmitForm, LessonCodeForm # <<< ИЗМЕНЕНИЕ

from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from bot.services.admin_cards import help_reply_kb
from aiogram import Router , types, F, Bot
from bot.services.db import get_db
from aiogram.types import FSInputFile
from aiogram.filters import StateFilter
from bot.keyboards.student import student_main_kb
from bot.config import COURSES

router = Router(name="student")


def _cancel_kb() -> types.ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="Отмена")
    return kb.as_markup(resize_keyboard=True)


KNOWN_BUTTONS = {
    "📚 Новый урок", "🔑 Урок по коду", "✅ Сдать урок", "🆘 Помощь",
    "🏅 Мой ранг", "🏆 Мой прогресс", "ℹ️ О курсе", "💳 Оплатить",
}


async def _submit_active(message: types.Message) -> bool:
    """Пометить активное задание как submitted и разослать карточку админам + копию сообщения."""
    # 1) найти активное задание
    async with get_db() as db:
        cur = await db.execute(
            "SELECT s.id as sid, p.id as pid FROM students s "
            "LEFT JOIN progress p ON p.student_id=s.id AND p.status IN ('sent','returned','submitted') "
            "WHERE s.tg_id=?",
            (message.from_user.id,),
        )
        row = await cur.fetchone()
        if not row or row["pid"] is None:
            return False  # нет активного задания — игнор

        pid = row["pid"]

        # 2) отметить submitted
        now = now_utc_str()
        await db.execute(
            "UPDATE progress SET status='submitted', submitted_at=?, updated_at=? WHERE id=?",
            (now, now, pid),
        )
        await db.commit()

        # 3) взять данные для карточки
    async with get_db() as db:
        cur = await db.execute(
            "SELECT lesson_code, task_code, submitted_at FROM progress WHERE id=?",
            (pid,),
        )
        prow = await cur.fetchone()

    from bot.services.admin_cards import render_submission_card
    settings = get_settings()

    card_text, kb = render_submission_card(
        pid,
        message.from_user,
        lesson_code=prow["lesson_code"],
        task_code=prow["task_code"],
        submitted_at_utc=prow["submitted_at"],
    )

    # Карточка + копия сообщения каждому админу
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(admin_id, card_text, reply_markup=kb)
            await message.copy_to(admin_id)
        except Exception:
            pass

    # 5) ответ ученику
    await message.answer("Работа отправлена ✅ Маестрофф пошел проверять")
    return True

# bot/routers/student.py

# ... (импорты в начале файла) ...
# Убедись, что есть этот импорт:


# <<< НОВЫЙ ОБРАБОТЧИК ДЛЯ МЕНЮ КУРСОВ >>>
@router.message(F.text == "🎓 Программа обучения")
async def training_program_menu(message: types.Message):
    """Показывает Inline-кнопки с выбором курса."""
    await message.answer("Выбери программу обучения:")

    kb = InlineKeyboardBuilder()
    # Проходим по нашему каталогу курсов из config.py
    for course_code, course in COURSES.items():
        # Для каждого курса создаем кнопку
        kb.button(text=course.title, callback_data=f"show_course:{course_code}")

    kb.adjust(1) # Располагаем кнопки вертикально

    await message.answer(
        "Доступные курсы:",
        reply_markup=kb.as_markup()
    )

# --- сдача МЕДИА (вне FSM помощи и без конфликтов с кнопками) ---
@router.message(
    StateFilter(None),
    F.content_type.in_({"photo", "video", "document"})
)
async def handle_submission_media(message: types.Message):
    await _submit_active(message)



@router.callback_query(F.data == "tests:back")
async def tests_back(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()  # выходим из режима тестов
    kb = student_main_kb() if callable(student_main_kb) else student_main_kb
    await cb.message.answer("Возвращаю в главное меню:", reply_markup=kb)
    await cb.answer()



@router.message(Command("myid", "my_id"))
async def cmd_myid(message: types.Message):
    await _get_or_create_student(message.from_user.id, message.from_user.username)
    await message.answer(f"Твой tg_id: <code>{message.from_user.id}</code>")


# ====== Main menu buttons ======
@router.message(F.text == "ℹ️ О курсе")
async def about_course(message: types.Message):
    txt = (
        "🎶 <b>О курсе</b>\n\n"
        "У тебя впереди <b>16 уроков 1- ого модуля</b>, где ты шаг за шагом освоишь:\n"
        "— как играть песни с аккордами,\n— читать табулатуры,\n— играть мелодии,\n"
        "— как соединять аккорды, голос и бой,\n— понимать основы теории музыки.\n\n"
        "А ещё тебя ждут <b>уроки по коду</b> — разборы хитов 🎸\n\n"
        "👉 Пройди первые 3 урока бесплатно и убедись, что гитара проще, чем кажется!\n\n"
        "📞 Если есть вопросы — звони: <b>+7 777 505 5788</b>"
    )
    await message.answer(txt)

@router.message(F.text == "🆘 Помощь")
async def btn_help(message: types.Message, state: FSMContext):
    await state.set_state(HelpForm.waiting_text)
    await message.answer("🆘 Ты нажал SOS\n"
    "Расскажи коротко, что случилось и я постараюсь быстро дать ответ"
)

@router.message(HelpForm.waiting_text, F.text)
async def handle_help_text(message: types.Message, state: FSMContext):
    settings = get_settings()

    # 1) находим студента (без колонки full_name)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, first_name, last_name, username FROM students WHERE tg_id=?",
            (message.from_user.id,)
        )
        srow = await cur.fetchone()

    if not srow:
        await state.clear()
        await message.answer("Упс, не нашли тебя в списке, Нажми /start")
        return

    student_id = srow["id"]
    # Аккуратно собираем отображаемое имя
    fn = (srow["first_name"] or "").strip()
    ln = (srow["last_name"] or "").strip()
    display_name = (f"{fn} {ln}".strip()
                    or (f"@{srow['username']}" if srow["username"] else "")
                    or message.from_user.full_name
                    or f"id {message.from_user.id}")

    # 2) проверяем, нет ли уже ОТКРЫТОЙ заявки
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id FROM help_requests WHERE student_id=? AND status='open' LIMIT 1",
            (student_id,),
        )
        exists = await cur.fetchone()

    if exists:
        await state.clear()
        await message.answer("Так-с такс-, давай по очереди, как только отвечу - сможешь еще раз написать 🙌")
        return

    # 3) создаём заявку в help_requests
    now = now_utc_str()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO help_requests (student_id, status, created_at) VALUES (?,?,?)",
            (student_id, "open", now),
        )
        await db.commit()

    # 4) уведомление админам
    username = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
    card = (
        "🆘 Запрос помощи\n"
        f"{display_name} ({username})\n\n"
        f"{message.text}"
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="✉️ Ответить", callback_data=f"adm_reply:{message.from_user.id}")
    kb.adjust(1)
    for admin_id in settings.admin_ids:
        try:
            await message.bot.send_message(admin_id, card, reply_markup=kb.as_markup())
        except Exception:
            pass

    await state.clear()
    await message.answer("Передал твоё сообщение маестроффам, как только освободятся сразу ответят ( обычно 1-5 минуты 👌")

@router.message(F.text == "🏆 Мой прогресс")
async def my_progress(message: types.Message):
    # находим студента
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM students WHERE tg_id=?", (message.from_user.id,))
        row = await cur.fetchone()
    if not row:
        await message.answer("Не нашел тебя в списке. Нажми /start")
        return
    sid = row["id"]

    # очки и ранг
    total = await points.total(sid)
    rank_name, next_thr = get_rank_by_points(total)

    # сколько уроков принято
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM progress WHERE student_id=? AND status='approved'",
            (sid,),
        )
        lessons = (await cur.fetchone())["c"]

    txt = (
        f"📊 Твой прогресс\n"
        f"• Уроков принято: <b>{lessons}</b>\n"
        f"• Баллы: <b>{total}</b>\n"
        f"• Ранг: <b>{rank_name}</b>"
    )
    if next_thr is not None:
        txt += f"\n• 🔥 До следующего ранга осталось: <b>{next_thr - total}</b> очков!"

    await message.answer(txt)

@router.message(F.text == "🏅 Мой ранг")
async def my_rank(message: types.Message):
    # находим студента по tg_id
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM students WHERE tg_id=?", (message.from_user.id,))
        row = await cur.fetchone()

    if not row:
        await message.answer("Профиль не найден. Нажми /start")
        return

    sid = row["id"]

    # суммарные баллы и ранг
    total = await points.total(sid)
    rank_name, next_thr = get_rank_by_points(total)

    txt = f"🏅 Твой ранг: <b>{rank_name}</b>\n🎯 Баллы: <b>{total}</b>"
    if next_thr is not None:
        txt += f"\n⬆️ До следующего: <b>{next_thr - total}</b>"

    await message.answer(txt)

@router.message(F.text == "💳 Оплатить")
async def pay(message: types.Message):
    settings = get_settings()
    await _get_or_create_student(message.from_user.id, message.from_user.username)
    txt = (
        "🎶 🎶 <b>Оплата</b>\n\n"
        f"Маестрофф тоже хочет кушать 😅\n"
        "Поддержи проект и продолжи обучение всего за <b>4999</b> (это почти как пара кружек кофе ☕️)"
    )
    # Check if already has confirmed payment
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM payments p JOIN students s ON s.id=p.student_id WHERE s.tg_id=?",
            (message.from_user.id,),
        )
        r = await cur.fetchone()
        if r and r["c"] > 0:
            await message.answer("Уговорил, можно было не платить ✅", reply_markup=student_main_kb())
            return

        # Check pending request
        cur = await db.execute(
            "SELECT pr.id FROM payment_requests pr JOIN students s ON s.id=pr.student_id "
            "WHERE s.tg_id=? AND pr.status='pending'",
            (message.from_user.id,),
        )
        pend = await cur.fetchone()
        include_button = True
        if pend:
            include_button = False
            txt += "\n\nВау, спасибо, как только я дойду до твоей оплаты сразу пришлю сообщение ✅"

    await message.answer(
        txt,
        reply_markup=payment_inline(
            settings.payment_link, include_i_paid=include_button, student_id=message.from_user.id
        ),
    )


@router.callback_query(F.data.startswith("paid_ipaid:"))
async def cb_paid_paid(cb: types.CallbackQuery):
    try:
        # <<< ИЗМЕНЕНИЕ: Парсим новые данные с кодом курса >>>
        _, course_code, tg_id_str = cb.data.split(":")
        tg_id = int(tg_id_str)
    except (ValueError, IndexError):
        await cb.answer("Ошибка в данных кнопки.", show_alert=True)
        return

    if cb.from_user.id != tg_id:
        await cb.answer("Это не твоя кнопка", show_alert=True)
        return

    course = get_course(course_code)
    if not course:
        await cb.answer("Курс не найден.", show_alert=True)
        return

    settings = get_settings()
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM students WHERE tg_id=?", (tg_id,))
        r = await cur.fetchone()
        if not r:
            await cb.answer("Профиль не найден", show_alert=True)
            return
        sid = r["id"]

        # Проверяем, не оплачен ли уже ЭТОТ курс
        cur = await db.execute("SELECT 1 FROM payments WHERE student_id=? AND course_code=?", (sid, course_code))
        if await cur.fetchone():
            await cb.answer("Этот курс уже оплачен ✅", show_alert=True)
            return

        # Создаем заявку на оплату с указанием курса
        await db.execute(
            "INSERT INTO payment_requests(student_id, amount, status, course_code, created_at) VALUES(?,?,?,?,?)",
            (sid, course.price, 'pending', course.code, now_utc_str()),
        )
        await db.commit()

    # Уведомляем админов
    card = (
        f"💳 <b>Заявка об оплате курса «{course.title}»</b>\n"
        f"Ученик: @{cb.from_user.username or 'no_username'} (id {cb.from_user.id})\n"
        f"Сумма: {course.price} ₸"
    )
    ik = InlineKeyboardBuilder()
    # <<< ИЗМЕНЕНИЕ: В кнопки для админа тоже передаем tg_id и course_code >>>
    ik.button(text="✅ Подтвердить", callback_data=f"adm_pay_ok:{course.code}:{tg_id}")
    ik.button(text="❌ Отклонить", callback_data=f"adm_pay_no:{course.code}:{tg_id}")
    ik.adjust(1)
    for admin_id in settings.admin_ids:
        try:
            await cb.bot.send_message(admin_id, card, reply_markup=ik.as_markup())
        except Exception:
            pass

    await cb.message.edit_text(cb.message.text + "\n\n✅ Заявка отправлена на проверку!")
    await cb.answer()

    await cb.message.edit_text(cb.message.text + "\n\nДа-Да, вот это я понимаю щедрый человек, секунду, мне надо сначала проверить  ✅")
    await cb.answer()


# ⬇️ КНОПКА МЕНЮ «📚 Новый урок» — тонкая обёртка
async def _issue_new_lesson(bot: Bot, tg_id: int, chat_id: int, course_code: str) -> None:
    settings = get_settings()
    course = get_course(course_code)
    if not course:
        await bot.send_message(chat_id, "Такой курс не найден.")
        return

    async with get_db() as db:
        # 1. Находим студента
        cur = await db.execute("SELECT id, approved FROM students WHERE tg_id=?", (tg_id,))
        s = await cur.fetchone()
        if not s or not s["approved"]:
            await bot.send_message(chat_id, "⏳ Твоя анкета еще на проверке. Доступ к урокам откроется после одобрения.")
            return
        sid = s["id"]

        # 2. Проверяем, есть ли уже активное задание (любое)
        cur = await db.execute(
            "SELECT id FROM progress WHERE student_id=? AND status IN ('sent','returned','submitted')", (sid,))
        if await cur.fetchone():
            await bot.send_message(chat_id, "У тебя уже есть активное задание. Сначала сдай его.")
            return

        # 3. Проверяем лимит бесплатных уроков и оплату для ЭТОГО курса
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM progress WHERE student_id=? AND status='approved' AND lesson_code LIKE ?",
            (sid, f"{course.code}:%")
        )
        approved_cnt = (await cur.fetchone())["c"]

        cur = await db.execute("SELECT 1 FROM payments WHERE student_id=? AND course_code=?", (sid, course_code))
        is_paid = await cur.fetchone()

        if approved_cnt >= course.free_lessons and not is_paid:
            payment_text = (
                f"🚫 Доступ к следующим урокам курса «{course.title}» платный.\n"
                f"Стоимость доступа: {course.price} ₸.\n\n"
                "Чтобы продолжить, нажми кнопку ниже."
            )
            await bot.send_message(
                chat_id,
                payment_text,
                reply_markup=payment_inline(
                    payment_link=settings.payment_link,
                    course_code_to_pay=course_code,
                    student_id=tg_id
                ),
            )
            return

        # 4. Выбираем следующий урок для этого курса
        course_path = settings.lessons_path / course.code
        cur = await db.execute(
            "SELECT lesson_code FROM progress WHERE student_id=? AND status='approved' AND lesson_code LIKE ?",
            (sid, f"{course.code}:L%")
        )
        rows = await cur.fetchall()
        last_num = 0
        for r in rows:
            l_code = (r["lesson_code"] or "").split(":")[-1]
            n = parse_l_num(l_code)
            if n and n > last_num:
                last_num = n

        next_lesson_folder = next_l_after(course_path, last_num)

        if not next_lesson_folder:
            await bot.send_message(chat_id,
                                   f"Новых уроков в курсе «{course.title}» пока нет. Я сообщу, когда они появятся 👌")
            return

        # 5. Создаем progress в БД с полным кодом урока
        full_lesson_code = f"{course.code}:{next_lesson_folder}"

        from datetime import datetime, timedelta, timezone
        sent_at = now_utc_str()
        deadline = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat().replace("+00:00",
                                                                                                               "Z")
        remind = (datetime.now(timezone.utc) + timedelta(hours=24)).replace(microsecond=0).isoformat().replace("+00:00",
                                                                                                               "Z")

        await db.execute(
            "INSERT INTO progress(student_id, lesson_code, status, sent_at, deadline_at, remind_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (sid, full_lesson_code, "sent", sent_at, deadline, remind, sent_at),
        )
        cur = await db.execute("SELECT last_insert_rowid() AS id")
        pid = (await cur.fetchone())["id"]
        await db.commit()

    # 6. Выдаем первый блок урока
    await bot.send_message(chat_id, f"Начинаем урок «{next_lesson_folder}» из курса «{course.title}»...")
    await send_next_t_block(bot, chat_id, pid, first=True)

# ===== Урок по коду (FSM вместо message.conf) =====
@router.message(F.text == "🎵 Уроки по коду") # <<< Изменили текст кнопки для соответствия
async def btn_lesson_by_code(message: types.Message, state: FSMContext):
    # Теперь мы переводим пользователя в состояние ожидания ввода кода
    await state.set_state(LessonCodeForm.waiting_code)
    await message.answer(
        "Введи код урока, чтобы получить к нему доступ.",
        reply_markup=_cancel_kb() # Используем существующую клавиатуру "Отмена"
    )

@router.message(LessonCodeForm.waiting_code, F.text.regexp(r"^[A-Za-z0-9_\-]{3,}$"))
async def lesson_code_entered(message: types.Message, state: FSMContext):
    # принимаем код ТОЛЬКО когда мы в состоянии ожидания
    code = message.text.strip()
    await _process_lesson_code(message, code)
    await state.clear()



    # --- сдача ТЕКСТОМ (не команды/кнопки, вне FSM помощи) ---


# ===== Utilities =====
async def _get_or_create_student(tg_id: int, username: str | None):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO students(tg_id, username, created_at, last_seen) VALUES(?,?,?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, last_seen=excluded.last_seen",
            (tg_id, username or "", now_utc_str(), now_utc_str()),
        )
        await db.commit()


# bot/routers/student.py
# ...
# <<< ВСТАВЬ ЭТОТ КОД В ФАЙЛ student.py >>>

async def _process_lesson_code(message: types.Message, code: str):
    settings = get_settings()
    # Ищем урок в специальной папке by_code_path
    path = settings.by_code_path / code

    if not path.exists() or not path.is_dir():
        await message.answer("Такой код урока не найден. Попробуй еще раз.")
        return

    async with get_db() as db:
        cur = await db.execute("SELECT id, approved FROM students WHERE tg_id=?", (message.from_user.id,))
        s_row = await cur.fetchone()
        if not s_row or not s_row["approved"]:
            await message.answer("Твой профиль еще не одобрен, доступ к урокам по коду откроется позже.")
            return
        sid = s_row["id"]

        # Проверяем, есть ли уже активное задание (любое)
        cur = await db.execute(
            "SELECT id FROM progress WHERE student_id=? AND status IN ('sent','returned','submitted')", (sid,))
        if await cur.fetchone():
            await message.answer("У тебя уже есть активное задание. Сначала сдай его.")
            return

        # Создаем полный код урока с префиксом "by_code"
        full_lesson_code = f"by_code:{code}"

        # Проверяем, не был ли этот урок уже пройден
        cur = await db.execute(
            "SELECT 1 FROM progress WHERE student_id=? AND lesson_code=? AND status='approved'",
            (sid, full_lesson_code)
        )
        if await cur.fetchone():
            await message.answer("Ты уже прошел этот урок по коду.")
            return

        # Создаем новую запись о прогрессе
        from datetime import datetime, timedelta
        sent_at = now_utc_str()

        await db.execute(
            "INSERT INTO progress(student_id, lesson_code, status, sent_at, updated_at) VALUES(?,?,?,?,?)",
            (sid, full_lesson_code, "sent", sent_at, sent_at),
        )
        cur = await db.execute("SELECT last_insert_rowid() AS id")
        pid = (await cur.fetchone())["id"]
        await db.commit()

    # Выдаем первый блок урока
    await message.answer(f"Открываю урок по коду «{code}»...")
    await send_next_t_block(message.bot, message.chat.id, pid, first=True)

# <<< ИЗМЕНЕНИЕ: Добавили StateFilter(None)
@router.message(StateFilter(None), F.photo)
async def handle_unhandled_photo(m: types.Message):
    """Отвечает, если пользователь отправляет фото, когда это не ожидается."""
    await m.answer(
        "Извини, я пока не умею работать с фотографиями в этом режиме. "
        "Пожалуйста, используй кнопки или текстовые команды."
    )

# ... остальные обработчики

@router.callback_query(F.data.startswith("show_course:"))
async def show_course_lessons(cb: types.CallbackQuery):
    """
    Показывает список уроков для выбранного курса со статусами
    ✅ - пройден
    ▶️ - следующий доступный
    🔒 - закрыт
    """
    course_code = cb.data.split(":")[1]
    course = get_course(course_code)

    if not course:
        await cb.answer("Курс не найден.", show_alert=True)
        return

    await cb.answer(f"Загружаю уроки курса «{course.title}»...")

    settings = get_settings()
    sid = None

    # 1. Находим ID студента
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM students WHERE tg_id=?", (cb.from_user.id,))
        s_row = await cur.fetchone()
        if s_row:
            sid = s_row["id"]

    if not sid:
        await cb.message.answer("Не нашел твой профиль. Нажми /start")
        return

    # 2. Получаем список ВСЕХ уроков курса из папок
    course_path = settings.lessons_path / course.code
    all_lessons = list_l_lessons(course_path)

    # 3. Получаем список ПРОЙДЕННЫХ уроков из БД
    async with get_db() as db:
        cur = await db.execute(
            "SELECT lesson_code FROM progress WHERE student_id=? AND status='approved' AND lesson_code LIKE ?",
            (sid, f"{course.code}:%")
        )
        rows = await cur.fetchall()
        # Убираем префикс курса, оставляем только L-код, например "L01"
        passed_lessons = {row["lesson_code"].split(":")[-1] for row in rows}

    # 4. Формируем клавиатуру
    kb = InlineKeyboardBuilder()
    next_lesson_unlocked = True

    for lesson_folder_name in all_lessons:
        status_icon = ""
        callback_data = ""

        if lesson_folder_name in passed_lessons:
            status_icon = "✅"
            callback_data = f"lesson:review:{course.code}:{lesson_folder_name}" # Возможность повторить урок
        elif next_lesson_unlocked:
            status_icon = "▶️"
            callback_data = f"lesson:start:{course.code}:{lesson_folder_name}" # Начать новый урок
            next_lesson_unlocked = False # Следующий после этого будет заблокирован
        else:
            status_icon = "🔒"
            callback_data = "lesson:locked" # Кнопка для заблокированных уроков

        # Добавляем кнопку в клавиатуру
        kb.button(text=f"{status_icon} {lesson_folder_name}", callback_data=callback_data)

    kb.adjust(1) # Все кнопки в один столбец

    await cb.message.edit_text(
        f"Уроки курса «{course.title}»:",
        reply_markup=kb.as_markup()
    )

# <<< НОВЫЙ ОБРАБОТЧИК ДЛЯ КНОПКИ "✅ ПОВТОРИТЬ УРОК" >>>
@router.callback_query(F.data.startswith("lesson:review:"))
async def lesson_review(cb: types.CallbackQuery):
    """Заглушка для повтора урока (пока не реализовано)."""
    try:
        _, _, course_code, lesson_folder = cb.data.split(":")
    except (ValueError, IndexError):
        await cb.answer("Ошибка в данных урока.", show_alert=True)
        return

    # TODO: В будущем здесь можно реализовать логику повторного просмотра урока
    await cb.answer(f"Повтор урока «{lesson_folder}» еще в разработке.", show_alert=True)


# <<< НОВЫЙ ОБРАБОТЧИК ДЛЯ КНОПКИ "🔒 УРОК ЗАБЛОКИРОВАН" >>>
@router.callback_query(F.data == "lesson:locked")
async def lesson_locked(cb: types.CallbackQuery):
    """Сообщает пользователю, что урок пока недоступен."""
    await cb.answer("Этот урок пока заблокирован. Пройди предыдущие, чтобы открыть его.", show_alert=True)