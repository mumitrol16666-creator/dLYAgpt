from __future__ import annotations

from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.student import student_main_kb
from bot.config import get_settings, now_utc_str
from bot.services.db import get_db
from bot.services import points

from bot.keyboards.admin import admin_main_reply_kb
from aiogram.types import ReplyKeyboardRemove
from logging import getLogger
logger = getLogger("maestro")



router = Router(name="onboarding")


class Onb(StatesGroup):
    waiting_start = State()
    first_name = State()
    last_name = State()
    birth_or_age = State()
    has_guitar = State()
    experience = State()
    goal = State()
    phone = State()
    rules = State()
    confirm = State()


WELCOME_TEXT = (
     "🦝 <b>Привет! Я — Маестрофф</b>, енот-наставник по гитаре.\n"
    "Здесь короткие уроки, задания и баллы за прогресс.\n"
    "А мои помощники — маестроффы — проверяют домашки и отвечают на вопросы.\n\n"
    "Чтобы начать, заполним короткую анкету. Готов?\n"
    "Жми «Погнали»!"
)


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    settings = get_settings()

    # upsert student
    async with get_db() as db:
        await db.execute(
            "INSERT INTO students(tg_id, username, created_at, last_seen) "
            "VALUES(?,?,?,?) "
            "ON CONFLICT(tg_id) DO UPDATE SET "
            "username=excluded.username, last_seen=excluded.last_seen",
            (
                message.from_user.id,
                (message.from_user.username or ""),
                now_utc_str(),
                now_utc_str(),
            ),
        )
        await db.commit()


        # check admin
        if message.from_user.id in settings.admin_ids:
            await message.answer("Админ-панель", reply_markup=admin_main_reply_kb())
            return

        # check onboarding_done
        cur = await db.execute(
            "SELECT onboarding_done, approved FROM students WHERE tg_id=?",
            (message.from_user.id,),
        )
        row = await cur.fetchone()
        if row and row["onboarding_done"]:
            if row["approved"]:
                await message.answer("Снова привет! Открываю меню 👇", reply_markup=student_main_kb())
            else:
                await message.answer("Анкета на проверке, Мои маестроффы уже ее тщательно проверяют, подождди немного")
            return

    # start onboarding
    ib = InlineKeyboardBuilder()
    ib.button(text="👉 Погнали", callback_data="onb_go")
    ib.button(text="ℹ️ Кто такие маестроффы?", callback_data="about_maestroffs")
    await message.answer(WELCOME_TEXT, reply_markup=ib.as_markup())
    await state.set_state(Onb.waiting_start)

@router.callback_query(F.data == "about_maestroffs")
async def cb_about_maestroffs(cb: types.CallbackQuery):
    txt = (
        "🦝 Маестроффы — это команда помощников Маестроффа.\n"
        "Они:\n"
        "• проверяют твою домашку и дают рекомендации;\n"
        "• отвечают на вопросы в «Помощи»;\n"
        "• иногда присылают подсказки и мотивашки.\n\n"
        "Если запутаешься — жми «🆘 Помощь» в уроке, один из маестроффов откликнется."
    )
    ib = InlineKeyboardBuilder()
    ib.button(text="👉 Погнали", callback_data="onb_go")
    await cb.answer()
    await cb.message.answer(txt)


@router.callback_query(F.data == "onb_go")
async def onb_go(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Давай знакомиться! Как тебя зовут? (только имя)")
    await state.set_state(Onb.first_name)
    await cb.answer()


@router.message(Onb.first_name)
async def onb_first_name(message: types.Message, state: FSMContext):
    await state.update_data(first_name=(message.text or "").strip())
    await message.answer("Класс! Хочешь — добавь фамилию (можно пропустить и написать «-»)")
    await state.set_state(Onb.last_name)


@router.message(Onb.last_name)
async def onb_last_name(message: types.Message, state: FSMContext):
    await state.update_data(last_name=(message.text or "").strip())
    await message.answer("Сколько тебе лет? Напиши цифрой (например: 12)")
    await state.set_state(Onb.birth_or_age)


@router.message(Onb.birth_or_age)
async def onb_birth(message: types.Message, state: FSMContext):
    await state.update_data(birth_or_age=(message.text or "").strip())
    kb = InlineKeyboardBuilder()
    kb.button(text="🎸 Есть", callback_data="g_has:1")
    kb.button(text="Пока нет, планирую", callback_data="g_has:0")
    kb.adjust(1)
    await message.answer("Есть ли у тебя гитара? 🎸", reply_markup=kb.as_markup())
    await state.set_state(Onb.has_guitar)


@router.callback_query(Onb.has_guitar, F.data.startswith("g_has:"))
async def onb_has_guitar(cb: types.CallbackQuery, state: FSMContext):
    has = int(cb.data.split(":")[1])
    await state.update_data(has_guitar=has)
    await cb.message.answer("Сколько месяцев уже играешь? (можно 0)")
    await state.set_state(Onb.experience)
    await cb.answer()


@router.message(Onb.experience)
async def onb_experience(message: types.Message, state: FSMContext):
    txt = (message.text or "").strip()
    try:
        exp = int("".join(ch for ch in txt if (ch.isdigit() or ch == "-")))
    except Exception:
        exp = 0
    await state.update_data(experience_months=max(0, exp))
    await message.answer("Что бы ты хотел научиться играть за 1-3 месяца ")
    await state.set_state(Onb.goal)


@router.message(Onb.goal)
async def onb_goal(message: types.Message, state: FSMContext):
    await state.update_data(goal=(message.text or "").strip())
    await message.answer("Введи номер телефона (+7 …)")
    await state.set_state(Onb.phone)


@router.message(Onb.phone)
async def onb_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=(message.text or "").strip())
    rules = (
        "📜 Короткие правила:\n"
        "— выполняем задания в срок;\n"
        "— уважительно общаемся;\n"
        "— кайфуем от музыки 🎶\n\n"
        "Подтверди, и полетели!\n"
        "_ Нам нужно немного времени чтобы проверить твою анкету, буквально 2-5 минут и откроем доступ"
    )

    ib = InlineKeyboardBuilder()
    ib.button(text="✅ Принимаю", callback_data="rules_ok")
    await message.answer(rules, reply_markup=ib.as_markup())
    await state.set_state(Onb.rules)


@router.callback_query(Onb.rules, F.data == "rules_ok")
async def onb_rules_ok(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    # persist
    async with get_db() as db:
        # parse age / birth_date
        age = None
        birth_date = None
        txt = (data.get("birth_or_age") or "").strip()
        if txt.isdigit():
            age = int(txt)
        else:
            birth_date = txt or None

        await db.execute(
            "UPDATE students SET first_name=?, last_name=?, birth_date=?, age=?, has_guitar=?, "
            "experience_months=?, goal=?, phone=?, onboarding_done=1, consent=1, last_seen=? "
            "WHERE tg_id=?",
            (
                data.get("first_name"),
                data.get("last_name"),
                birth_date,
                age,
                int(data.get("has_guitar") or 0),
                int(data.get("experience_months") or 0),
                data.get("goal"),
                data.get("phone"),
                now_utc_str(),
                cb.from_user.id,
            ),
        )
        await db.commit()

        # Fetch student id
        cur = await db.execute(
            "SELECT id FROM students WHERE tg_id=?", (cb.from_user.id,)
        )
        row = await cur.fetchone()
        student_id = row["id"] if row else None

        # award onboarding bonus (+50), idempotent via UNIQUE(student_id, source)
        # +50 за онбординг (идемпотентно)
        if student_id:
            try:
                await points.add(student_id, "onboarding_bonus", 50)
            except Exception:
                pass

        # --- Рассчёт ранга после онбординга --- #
        #total = await points.total(student_id)
        #rank_name, next_thr = get_rank_by_points(total)

        #async with get_db() as db:
         #   await db.execute(
          #      "UPDATE students SET rank=?, rank_points=?, updated_at=? WHERE id=?",
           #     (rank_name, total, now_utc_str(), student_id),
            #)
            #await db.commit()

            # сообщение про ранг
            #msg = f"🏅 Твой стартовый ранг: <b>{rank_name}</b>\nБаллы: <b>{total}</b>"
           # if next_thr is not None:
           #     msg += f"\n⬆️ До следующего: <b>{next_thr - total}</b>"
          #  await cb.message.answer(msg)



    await cb.message.answer(
        "Анкета отправлена на модерацию. Мы дадим доступ после одобрения администратором.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.clear()
    # (уведомление админам с кнопками onb_ok/onb_rej — оставить как есть)

    # Notify admins
    settings = get_settings()
    if settings.admin_ids:
        card = (
            "🆕 Новая анкета\n"
            f"Имя: {data.get('first_name','')} {data.get('last_name','')}\n"
            f"Возраст/рожд.: {data.get('birth_or_age','')}\n"
            f"Телефон: {data.get('phone','')}\n"
            f"Гитара: {'есть' if int(data.get('has_guitar') or 0) else 'нет'}\n"
            f"Опыт: {int(data.get('experience_months') or 0)} мес\n"
            f"Цель: {data.get('goal','')}\n"
            f"@{cb.from_user.username or 'no_username'} • tg_id: {cb.from_user.id}\n"
        )
        # используем уже существующий инстанс бота
        for admin_id in settings.admin_ids:
            try:
                ik = InlineKeyboardBuilder()

                ik.button(text="✅ Одобрить", callback_data=f"onb_ok:{student_id}")
                ik.button(text="❌ Отклонить", callback_data=f"onb_rej:{student_id}")
                ik.adjust(2)
                await cb.bot.send_message(admin_id, card, reply_markup=ik.as_markup())
            except Exception:
                pass