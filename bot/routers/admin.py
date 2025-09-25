from __future__ import annotations

import random
import asyncio
import re
from typing import List

from aiogram import Router, types, F, Bot
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings, now_utc_str, local_dt_str
from bot.keyboards.admin import admin_main_reply_kb
from bot.services import points
from bot.services.db import get_db
from bot.services.ranks import get_rank_by_points
from bot.config import get_course
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from bot.keyboards.student import student_main_kb
from bot.services.db import get_db, DB_PATH
from aiogram import Router, types, F
from aiogram.filters import StateFilter, Command


class BroadcastForm(StatesGroup):
    waiting_text = State()


router = Router(name="admin")


_admins = set(get_settings().admin_ids or [])
router.message.filter(F.from_user.id.in_(_admins), StateFilter("*"))
router.callback_query.filter(F.from_user.id.in_(_admins), StateFilter("*"))


# Диагностика (оставь временно)
@router.message(Command("ping"))
async def admin_ping(m: types.Message):
    await m.answer("admin ok")

# Пример ловли кнопки по эмодзи/префиксу, чтобы не зависеть от точного текста
@router.message(F.text.func(lambda t: t and t.startswith("📊")))
async def admin_stats(m: types.Message):
    await m.answer("Статистика: ок")  # тут твоя логика

MOTIVATION_TEXTS = [
    "Красавчик! Держим темп 💪",
    "С каждым уроком ты сильнее 🎸",
    "Отличный прогресс — едем дальше! 🚀",
]

# ----------------- общие утилиты -----------------

def render_broadcast(tpl: str, srow) -> str:
    first = (srow["first_name"] or "").strip()
    last = (srow["last_name"] or "").strip()
    username = (srow["username"] or "").strip()
    name = first or (username and f"@{username}") or "друг"

    vars = {
        "id": srow["id"],
        "tg_id": srow["tg_id"],
        "username": username,
        "first_name": first,
        "last_name": last,
        "name": name,
    }
    def repl(m: re.Match):
        key = m.group(1)
        return str(vars.get(key, ""))
    # заменяем {key} на значения; неизвестные ключи → пусто
    return re.sub(r"\{(\w+)\}", repl, tpl)

def _is_admin(uid: int) -> bool:
    return uid in get_settings().admin_ids

async def _send_chunked(bot: Bot, chat_id: int, lines: List[str], limit: int = 4000):
    """Отправка длинного списка сообщениями ≤ limit (TG ~4096)."""
    if not lines:
        return
    chunk, total = [], 0
    for line in lines:
        add = len(line) + 1
        if total + add > limit:
            await bot.send_message(chat_id, "\n".join(chunk))
            chunk, total = [line], add
        else:
            chunk.append(line); total += add
    if chunk:
        await bot.send_message(chat_id, "\n".join(chunk))

# Счётчики для бейджей на кнопках
async def _admin_counts():
    """
    queue=submitted работ, pay_pending=ожидающих оплат,
    onb_pending=анкет на модерации, students_total=всего учеников
    """
    async with get_db() as db:
        # очередь работ
        cur = await db.execute("SELECT COUNT(*) AS c FROM progress WHERE status='submitted'")
        queue = (await cur.fetchone())["c"]

        # заявки на оплату (pending)
        cur = await db.execute("SELECT COUNT(*) AS c FROM payment_requests WHERE status='pending'")
        pay_pending = (await cur.fetchone())["c"]

        # анкеты на модерации
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM students WHERE onboarding_done=1 AND COALESCE(approved,0)=0"
        )
        onb_pending = (await cur.fetchone())["c"]

        # всего учеников
        cur = await db.execute("SELECT COUNT(*) AS c FROM students")
        students_total = (await cur.fetchone())["c"]

    return queue, pay_pending, onb_pending, students_total


# ----------------- вход/выход админ-режима -----------------
@router.message(Command("admin"))
async def admin_mode_on(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    queue, pay_pending, onb_pending, students_total = await _admin_counts()
    await m.answer(
        "🔧 Админ-режим включён.",
        reply_markup=admin_main_reply_kb(queue, pay_pending, onb_pending, students_total),
    )

@router.message(F.text == "🚪 Выйти из админ-режима")
async def admin_mode_off(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    await m.answer("Готово. Клава скрыта.", reply_markup=ReplyKeyboardRemove())

# ----------------- ReplyKeyboard: верхний уровень -----------------
@router.message(F.text == "📊 Статистика")
async def msg_adm_stats(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(*) AS c FROM students"); students = (await cur.fetchone())["c"]
        cur = await db.execute("SELECT COUNT(*) AS c FROM progress WHERE status IN ('sent','returned','submitted')"); active = (await cur.fetchone())["c"]
        cur = await db.execute("SELECT COUNT(*) AS c FROM progress WHERE status='submitted'"); queued = (await cur.fetchone())["c"]
        cur = await db.execute("SELECT COUNT(*) AS c FROM progress WHERE status='approved' AND approved_at >= datetime('now','-7 day') || 'Z'"); approved7 = (await cur.fetchone())["c"]
        cur = await db.execute("SELECT COALESCE(SUM(amount),0) AS s FROM payments WHERE paid_at >= datetime('now','-30 day') || 'Z'"); sum30 = (await cur.fetchone())["s"]
    txt = ("📊 Статистика\n"
           f"— Ученики: {students}\n"
           f"— Активных заданий: {active}\n"
           f"— В очереди (submitted): {queued}\n"
           f"— Одобрено за 7д: {approved7}\n"
           f"— Платежи за 30д: {sum30} ₸")
    await m.answer(txt)

@router.message(F.text.startswith("🗂 Очередь"))
async def msg_adm_queue(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    async with get_db() as db:
        cur = await db.execute("""
            SELECT p.id, p.lesson_code, p.task_code, p.submitted_at, s.tg_id, s.username
            FROM progress p JOIN students s ON s.id = p.student_id
            WHERE p.status='submitted' ORDER BY p.submitted_at DESC
        """)
        rows = await cur.fetchall()
    if not rows:
        await m.answer("Очередь пустая.")
        return
    await m.answer("Очередь работ (submitted):")
    for r in rows:
        card = (f"PID: {r['id']}\n"
                f"Ученик: @{r['username'] or 'no_username'} (id {r['tg_id']})\n"
                f"Урок/раздел: {r['lesson_code']}/{r['task_code']}\n"
                f"Сдано: {r['submitted_at']}")
        ik = InlineKeyboardBuilder()
        ik.button(text="✅ Принять", callback_data=f"p_ok:{r['id']}")
        ik.button(text="↩️ Вернуть", callback_data=f"p_back:{r['id']}")
        ik.adjust(2)
        await m.bot.send_message(m.chat.id, card, reply_markup=ik.as_markup())

@router.message(F.text.startswith("👥 Ученики"))
async def msg_adm_students(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    async with get_db() as db:
        cur = await db.execute("""
            SELECT id, tg_id, username, first_name, last_name, onboarding_done, created_at
            FROM students ORDER BY id DESC LIMIT 30
        """)
        rows = await cur.fetchall()
    if not rows:
        await m.answer("Ученики не найдены.")
        return
    await m.answer("Последние ученики:")
    for r in rows:
        card = (f"id:{r['id']} • tg_id:{r['tg_id']} @{r['username'] or '—'}\n"
                f"{r['first_name'] or ''} {r['last_name'] or ''} • onb:{r['onboarding_done']} • {r['created_at']}")
        ik = InlineKeyboardBuilder()
        ik.button(text="ℹ️ Анкета", callback_data=f"stu_info:{r['id']}")
        ik.button(text="🗑 Удалить", callback_data=f"stu_del:{r['id']}")
        ik.adjust(2)
        await m.bot.send_message(m.chat.id, card, reply_markup=ik.as_markup())

@router.message(F.text == "💳 Платежи")
async def msg_adm_payments(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    await _show_payments(m.bot, m.chat.id)

@router.message(F.text.startswith("🧾 Заявки на оплату"))
async def msg_adm_pay_pending(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    await _show_pay_requests(m.bot, m.chat.id)

@router.message(F.text.startswith("📝 Анкеты (модерация)"))
async def msg_adm_onb_pending(m: types.Message):
    if not _is_admin(m.from_user.id):
        return
    await _show_onboarding_pending(m.bot, m.chat.id)

# ----------------- callbacks: карточки и пункты меню -----------------
@router.callback_query(F.data == "adm_payments")
async def cb_adm_payments(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer(); return
    await cb.answer()
    await cb.message.edit_text("💳 Платежи:")
    await _show_payments(cb.message.bot, cb.message.chat.id)

@router.callback_query(F.data == "adm_pay_pending")
async def cb_adm_pay_pending(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer(); return
    await cb.answer()
    await cb.message.edit_text("🧾 Заявки на оплату:")
    await _show_pay_requests(cb.message.bot, cb.message.chat.id)

@router.callback_query(F.data == "adm_onb_pending")
async def cb_adm_onb_pending(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer(); return
    await cb.answer()
    await cb.message.edit_text("📝 Анкеты (модерация):")
    await _show_onboarding_pending(cb.message.bot, cb.message.chat.id)

@router.callback_query(F.data.startswith("stu_info:"))
async def stu_info(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1])
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM students WHERE id=?", (sid,))
        s = await cur.fetchone()
    if not s:
        await cb.answer("Нет такого"); return
    card = (
        "👤 Анкета ученика\n"
        f"Имя: {s['first_name'] or ''} {s['last_name'] or ''}\n"
        f"Возраст: {s['age'] or '—'} (рожд.: {s['birth_date'] or '—'})\n"
        f"Телефон: {s['phone'] or '—'}\n"
        f"Гитара: {'есть' if (s['has_guitar'] or 0) else 'нет'}\n"
        f"Опыт: {s['experience_months'] or 0} мес\n"
        f"Цель: {s['goal'] or '—'}\n"
        f"@{s['username'] or '—'} • tg_id: {s['tg_id']}\n"
        f"Зарегистрирован: {s['created_at'] or '—'}"
    )
    await cb.message.edit_text(card)
    await cb.answer()

@router.callback_query(F.data.startswith("stu_del:"))
async def stu_del(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1])
    ik = InlineKeyboardBuilder()
    ik.button(text="Да, удалить", callback_data=f"stu_del_go:{sid}")
    ik.button(text="Отмена", callback_data="adm_students")
    await cb.message.edit_text(
        f"Удалить ученика id:{sid}? Это удалит его прогресс и платежи.",
        reply_markup=ik.as_markup(),
    )
    await cb.answer()

@router.callback_query(F.data.startswith("stu_del_go:"))
async def stu_del_go(cb: types.CallbackQuery):
    sid = int(cb.data.split(":")[1])
    async with get_db() as db:
        await db.execute("DELETE FROM students WHERE id=?", (sid,))
        await db.commit()
    await cb.message.edit_text("Удалено.")
    await cb.answer()

# ----- проверка работ -----
@router.callback_query(F.data.startswith("p_ok:"))
async def p_ok(cb: types.CallbackQuery):
    pid = int(cb.data.split(":")[1])

    # ↓↓↓ НАШЕ ИЗМЕНЕНИЕ №1 ↓↓↓
    # Немедленно убираем кнопки и показываем, что работа в процессе.
    original_text = cb.message.text
    await cb.message.edit_text(f"{original_text}\n\n⏳ Обрабатываю...")

    async with get_db() as db:
        # Прогресс
        cur = await db.execute("SELECT status, task_code FROM progress WHERE id=?", (pid,))
        prow = await cur.fetchone()
        if not prow:
            # Если что-то пошло не так, вернем исходный вид с кнопками
            await cb.message.edit_text(original_text, reply_markup=cb.message.reply_markup)
            await cb.answer("Прогресс не найден", show_alert=True)
            return

        # ... (вся ваша существующая логика проверок статуса)
        status = (prow["status"] or "")
        if status == "approved":
            await cb.message.edit_text(f"{original_text}\n\n✅ Уже было принято.")
            await cb.answer("Уже принято ✅")
            return
        if status != "submitted":
            await cb.message.edit_text(original_text, reply_markup=cb.message.reply_markup)
            await cb.answer("Работа не на проверке.", show_alert=True)
            return

        # апрув
        now = now_utc_str()
        await db.execute(
            "UPDATE progress SET status='approved', approved_at=?, updated_at=? WHERE id=?",
            (now, now, pid),
        )

        # студент
        cur = await db.execute("""
            SELECT s.id AS sid, s.tg_id AS tg_id
            FROM progress p JOIN students s ON s.id = p.student_id
            WHERE p.id = ?
        """, (pid,))
        row = await cur.fetchone()
        if not row:
            await cb.answer("Студент не найден", show_alert=True); return
        sid, tg_id = row["sid"], row["tg_id"]

        # +100 баллов за урок (идемпотентно)
        try:
            await points.add(sid, f"lesson_approved:{pid}", 100)
        except Exception:
            pass

        # сколько уже принято
        cur = await db.execute("SELECT COUNT(*) AS c FROM progress WHERE student_id=? AND status='approved'", (sid,))
        appr = (await cur.fetchone())["c"]

        bonus = None
        if appr == 8:
            bonus = ("module1_bonus:s{sid}", 500, "🎉 Поздравляем!\nТы закрыл 1-й модуль — 8 уроков 💪\n\n🎯 Бонус: +500 баллов")
        elif appr == 16:
            bonus = ("module2_bonus:s{sid}", 500, "🏆 Финал!\nТы прошёл 16 уроков.\n\n🎯 Бонус: +500 баллов\nБейдж: «Выпускник Maestro» 🏅")
        if bonus:
            try:
                await points.add(sid, bonus[0], bonus[1])
            except Exception:
                pass

        await db.commit()

    # пересчёт ранга
    total = await points.total(sid)
    async with get_db() as db:
        cur = await db.execute("SELECT rank FROM students WHERE id=?", (sid,))
        prev_rank = (await cur.fetchone())["rank"] or ""
    rank_name, next_thr = get_rank_by_points(total)

    now = now_utc_str()
    async with get_db() as db:
        if rank_name != prev_rank:
            await db.execute("UPDATE students SET rank=?, rank_points=?, updated_at=? WHERE id=?",
                             (rank_name, total, now, sid))
        else:
            await db.execute("UPDATE students SET rank_points=?, updated_at=? WHERE id=?",
                             (total, now, sid))
        await db.commit()

    # сообщение ученику
    rank_up_text = (f"🏅 Новый ранг: <b>{rank_name}</b>!\nТвои баллы: <b>{total}</b>"
                    f"\n⬆️ До следующего ранга: <b>{next_thr - total}</b>") if (rank_name != prev_rank and next_thr is not None) else None
    accept_text = "✅ Работа принята! +100 баллов 🎯"
    if appr == 8 or appr == 16:
        accept_text += f"\n\n{bonus[2]}"
    accept_text += f"\nТвой счёт: <b>{total}</b> баллов"
    final_text = f"{rank_up_text}\n\n{accept_text}" if rank_up_text else accept_text

    # ...
    try:  # <<< ИЗМЕНЕНИЕ: Начало блока try
        await cb.message.bot.send_message(tg_id, final_text)

        kb = InlineKeyboardBuilder()
        kb.button(text="📚 Следующий урок", callback_data=f"stu:take_next:{sid}")
        kb.adjust(1)
        await cb.message.bot.send_message(tg_id, random.choice(MOTIVATION_TEXTS), reply_markup=kb.as_markup())

        await cb.message.edit_text(f"{original_text}\n\n✅ Принято. Ученик уведомлен.")
        await cb.answer("Принято ✅")

    except Exception as e:  # <<< ИЗМЕНЕНИЕ: Ловим возможную ошибку
        # Если юзер заблокировал бота, просто сообщим админу
        print(f"Не удалось отправить сообщение ученику {tg_id}: {e}")
        await cb.message.edit_text(
            f"{original_text}\n\n✅ Принято. (Не удалось уведомить ученика, возможно, он заблокировал бота)")
        await cb.answer("Принято, но не удалось уведомить", show_alert=True)


# Файл: Bot/routers/admin.py

@router.callback_query(F.data.startswith("p_back:"))
async def p_back(cb: types.CallbackQuery):
    pid = int(cb.data.split(":")[1])

    # 1. Сохраняем исходный текст и сразу блокируем интерфейс
    original_text = cb.message.text
    await cb.message.edit_text(f"{original_text}\n\n⏳ Возвращаю на доработку...")

    async with get_db() as db:
        cur = await db.execute("SELECT status FROM progress WHERE id=?", (pid,))
        prow = await cur.fetchone()

    # 2. Проверяем все возможные ошибки и даем обратную связь
    if not prow:
        await cb.message.edit_text(original_text, reply_markup=cb.message.reply_markup)
        await cb.answer("Прогресс не найден", show_alert=True)
        return
    if prow["status"] == "returned":
        await cb.message.edit_text(f"{original_text}\n\n⚠️ Уже было возвращено.")
        await cb.answer("Уже отправлено на доработку ⚠️")
        return
    if prow["status"] == "approved":
        await cb.message.edit_text(f"{original_text}\n\n✅ Работа уже принята.")
        await cb.answer("Работа уже принята ✅", show_alert=True)
        return
    # Эта проверка может быть лишней, но на всякий случай оставляем
    if prow["status"] not in ("submitted", "returned"):
        await cb.message.edit_text(original_text, reply_markup=cb.message.reply_markup)
        await cb.answer("Работа не на проверке.", show_alert=True)
        return

    # 3. Выполняем основную логику
    async with get_db() as db:
        await db.execute("UPDATE progress SET status='returned', returned_at=?, updated_at=? WHERE id=?",
                         (now_utc_str(), now_utc_str(), pid))
        cur = await db.execute("""
            SELECT s.tg_id AS tg_id
            FROM progress p JOIN students s ON s.id = p.student_id
            WHERE p.id = ?
        """, (pid,))
        row = await cur.fetchone()
        await db.commit()

    if row and row["tg_id"]:
        await cb.message.bot.send_message(row["tg_id"], "↩️ Работа возвращена на доработку. Исправь и сдавай снова 💪")

    # 4. Сообщаем админу об успешном выполнении
    await cb.message.edit_text(f"{original_text}\n\n↩️ Возвращено. Ученик уведомлен.")
    await cb.answer("Возвращено")
# ----- платежи -----
async def _show_payments(bot: Bot, chat_id: int):
    settings = get_settings(); tz = settings.timezone
    async with get_db() as db:
        cur = await db.execute("""
            SELECT p.id, s.username, s.tg_id, p.amount, p.method, p.note, p.paid_at
            FROM payments p JOIN students s ON s.id = p.student_id
            ORDER BY COALESCE(p.paid_at,'') DESC, p.id DESC
            LIMIT 20
        """); pays = await cur.fetchall()
        cur = await db.execute("""
            SELECT pr.id, pr.amount, pr.created_at, s.username, s.tg_id
            FROM payment_requests pr JOIN students s ON s.id = pr.student_id
            WHERE pr.status='pending'
            ORDER BY pr.created_at DESC
        """); reqs = await cur.fetchall()
        cur = await db.execute("""
            SELECT COALESCE(SUM(amount),0) AS s
            FROM payments
            WHERE paid_at >= datetime('now','-30 day') || 'Z'
        """); sum30 = (await cur.fetchone())["s"]

    await bot.send_message(chat_id, f"💳 Платежи (последние 20)\nИтого за 30 дней: {sum30} ₸")

    if pays:
        lines = []
        for p in pays:
            paid = local_dt_str(p["paid_at"], tz) if p["paid_at"] else "—"
            user = p["username"] or "no_username"
            method = p["method"] or "manual"
            note = (f" • {p['note']}" if (p["note"] or "").strip() else "")
            lines.append(f"{paid} • @{user} ({p['tg_id']}) — {p['amount']} ₸ [{method}]{note}")
        await _send_chunked(bot, chat_id, lines)
    else:
        await bot.send_message(chat_id, "Платежей пока нет.")

    if reqs:
        await bot.send_message(chat_id, "Ожидают подтверждения:")
        for r in reqs:
            ik = InlineKeyboardBuilder()
            ik.button(text="✅ Подтвердить", callback_data=f"adm_pay_ok:{r['tg_id']}")
            ik.button(text="❌ Отклонить",  callback_data=f"adm_pay_no:{r['tg_id']}")
            ik.adjust(2)
            created = local_dt_str(r["created_at"], tz) if r["created_at"] else "—"
            await bot.send_message(
                chat_id,
                f"@{r['username'] or 'no_username'} ({r['tg_id']}) — {r['amount']} ₸, {created}",
                reply_markup=ik.as_markup(),
            )
    else:
        await bot.send_message(chat_id, "Нет ожидающих заявок.")

async def _show_pay_requests(bot: Bot, chat_id: int):
    async with get_db() as db:
        cur = await db.execute("""
            SELECT pr.id, pr.amount, pr.created_at, s.username, s.tg_id
            FROM payment_requests pr JOIN students s ON s.id = pr.student_id
            WHERE pr.status='pending' ORDER BY pr.created_at ASC
        """); reqs = await cur.fetchall()
    if not reqs:
        await bot.send_message(chat_id, "Нет ожидающих заявок на оплату.")
        return
    await bot.send_message(chat_id, "Ожидают подтверждения:")
    for r in reqs:
        ik = InlineKeyboardBuilder()
        ik.button(text="✅ Подтвердить", callback_data=f"adm_pay_ok:{r['tg_id']}")
        ik.button(text="❌ Отклонить",  callback_data=f"adm_pay_no:{r['tg_id']}")
        ik.adjust(2)
        await bot.send_message(chat_id,
            f"@{r['username'] or 'no_username'} ({r['tg_id']}) — {r['amount']} ₸, {r['created_at']}",
            reply_markup=ik.as_markup())

async def _show_onboarding_pending(bot: Bot, chat_id: int):
    async with get_db() as db:
        cur = await db.execute("""
            SELECT id, tg_id, username, first_name, last_name, created_at
            FROM students
            WHERE onboarding_done = 1 AND COALESCE(approved, 0) = 0
            ORDER BY created_at ASC
        """); rows = await cur.fetchall()
    if not rows:
        await bot.send_message(chat_id, "Нет анкет на модерации.")
        return
    await bot.send_message(chat_id, "Анкеты на модерации:")
    for r in rows:
        card = (f"id:{r['id']} • tg_id:{r['tg_id']} @{r['username'] or '—'}\n"
                f"{r['first_name'] or ''} {r['last_name'] or ''} • {r['created_at']}")
        ik = InlineKeyboardBuilder()
        ik.button(text="✅ Одобрить", callback_data=f"onb_ok:{r['id']}")
        ik.button(text="❌ Отклонить", callback_data=f"onb_rej:{r['id']}")
        ik.adjust(2)
        await bot.send_message(chat_id, card, reply_markup=ik.as_markup())

# ----- подтверждение/отклонение оплаты -----
@router.callback_query(F.data.startswith("adm_pay_ok:"))
async def adm_pay_ok(cb: types.CallbackQuery):
    try:
        _, course_code, tg_id_str = cb.data.split(":")
        tg_id = int(tg_id_str)
    except (ValueError, IndexError):
        await cb.answer("Ошибка в данных кнопки.", show_alert=True)
        return

    course = get_course(course_code)
    if not course:
        await cb.answer(f"Курс с кодом {course_code} не найден.", show_alert=True)
        return

    original_text = cb.message.text
    await cb.message.edit_text(f"{original_text}\n\n⏳ Подтверждаю оплату...")

    async with get_db() as db:
        cur = await db.execute("SELECT id FROM students WHERE tg_id=?", (tg_id,))
        srow = await cur.fetchone()
        if not srow:
            await cb.answer("Студент не найден", show_alert=True)
            return
        sid = srow["id"]

        # Создаём запись об оплате для конкретного курса
        now = now_utc_str()
        await db.execute(
            "INSERT INTO payments(student_id, amount, course_code, method, note, paid_at, created_at) VALUES(?,?,?,?,?,?,?)",
            (sid, course.price, course.code, "manual", f"confirmed by {cb.from_user.id}", now, now),
        )
        # Закрываем заявку на оплату
        await db.execute(
            "UPDATE payment_requests SET status='confirmed', resolved_at=? WHERE student_id=? AND course_code=? AND status='pending'",
            (now, sid, course.code)
        )
        await db.commit()

    await cb.message.edit_text(f"{original_text}\n\n✅ Оплата курса «{course.title}» подтверждена.")
    await cb.answer("Подтверждено")

    try:
        await cb.bot.send_message(tg_id, f"✅ Доступ к курсу «{course.title}» открыт! Можешь начинать обучение.")
    except Exception as e:
        print(f"Не удалось уведомить студента {tg_id} об оплате: {e}")

@router.callback_query(F.data.startswith("adm_pay_no:"))
async def adm_pay_no(cb: types.CallbackQuery):
    try:
        _, course_code, tg_id_str = cb.data.split(":")
        tg_id = int(tg_id_str)
    except (ValueError, IndexError):
        await cb.answer("Ошибка в данных кнопки.", show_alert=True)
        return

    course = get_course(course_code)
    if not course:
        await cb.answer(f"Курс с кодом {course_code} не найден.", show_alert=True)
        return

    original_text = cb.message.text
    await cb.message.edit_text(f"{original_text}\n\n⏳ Отклоняю заявку...")

    async with get_db() as db:
        cur = await db.execute("SELECT id FROM students WHERE tg_id=?", (tg_id,))
        row = await cur.fetchone()
        if not row:
            await cb.answer("Студент не найден", show_alert=True)
            return
        sid = row["id"]

        await db.execute("UPDATE payment_requests SET status='rejected', resolved_at=? WHERE student_id=? AND course_code=? AND status='pending'",
                         (now_utc_str(), sid, course.code))
        await db.commit()

    await cb.message.edit_text(f"{original_text}\n\n❌ Заявка на курс «{course.title}» отклонена.")
    await cb.answer("Отклонено")
    try:
        await cb.bot.send_message(tg_id, f"❗️ Твоя заявка на оплату курса «{course.title}» была отклонена. Если считаешь, что это ошибка, свяжись с нами через «🆘 Помощь».")
    except Exception:
        pass

# ----- модерация онбординга -----
@router.callback_query(F.data.startswith("onb_ok:"))
async def onb_ok(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer(); return

    sid = int(cb.data.split(":")[1])
    # Блокируем интерфейс
    original_text = cb.message.text
    await cb.message.edit_text(f"{original_text}\n\n⏳ Одобряю анкету...")

    # 1) пометить как одобренного и достать tg_id
    async with get_db() as db:
        await db.execute("UPDATE students SET approved=1, updated_at=? WHERE id=?",
                         (now_utc_str(), sid))
        await db.commit()
        cur = await db.execute("SELECT tg_id, COALESCE(rank,'') AS rank FROM students WHERE id=?", (sid,))
        row = await cur.fetchone()

    if not row:
        await cb.answer("Студент не найден", show_alert=True); return

    tg_id = row["tg_id"]
    prev_rank = row["rank"] or ""

    # 2) безопасно начислить +50 за онбординг (идемпотентно по UNIQUE(student_id, source))
    try:
        await points.add(sid, "onboarding_bonus", 50)
    except Exception:
        pass

    # 3) пересчитать ранг и сохранить rank/rank_points
    total = await points.total(sid)
    rank_name, next_thr = get_rank_by_points(total)
    async with get_db() as db:
        if rank_name != prev_rank:
            await db.execute(
                "UPDATE students SET rank=?, rank_points=?, updated_at=? WHERE id=?",
                (rank_name, total, now_utc_str(), sid),
            )
        else:
            await db.execute(
                "UPDATE students SET rank_points=?, updated_at=? WHERE id=?",
                (total, now_utc_str(), sid),
            )
        await db.commit()

    # 4) уведомления
    await cb.message.edit_text(f"{original_text}\n\n✅ Анкета одобрена.")
    await cb.answer("Анкета одобрена ✅", show_alert=True)

    # студенту — статус, баллы, ранг + меню
    msg = f"✅ Твоя анкета одобрена! Доступ открыт.\nНачислено: +50 баллов.\n"
    msg += f"🏅 Твой ранг: <b>{rank_name}</b> • Баллы: <b>{total}</b>"
    if next_thr is not None:
        msg += f"\n⬆️ До следующего ранга: <b>{next_thr - total}</b>"
    await cb.bot.send_message(tg_id, msg)
    await cb.bot.send_message(tg_id, "Открываю меню 👇", reply_markup=student_main_kb())


@router.callback_query(F.data.startswith("onb_rej:"))
async def onb_rej(cb: types.CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer(); return
    sid = int(cb.data.split(":")[1])
    original_text = cb.message.text
    await cb.message.edit_text(f"{original_text}\n\n⏳ Отклоняю анкету...")

    async with get_db() as db:
        # опционально «выкидываем в начало»: сбрасываем флаг онбординга
        await db.execute(
            "UPDATE students SET approved=0, onboarding_done=0, updated_at=? WHERE id=?",
            (now_utc_str(), sid),
        )
        await db.commit()
        cur = await db.execute("SELECT tg_id FROM students WHERE id=?", (sid,))
        row = await cur.fetchone()

    await cb.message.edit_text(f"{original_text}\n\n❌ Анкета отклонена.")
    await cb.answer("Анкета отклонена ❌", show_alert=True)

    if row and row["tg_id"]:
        # маленькая кнопка «начать заново» — переиспользуем твой onb_go
        ik = InlineKeyboardBuilder()
        ik.button(text="🔁 Заполнить анкету заново", callback_data="onb_go")
        ik.adjust(1)
        await cb.bot.send_message(
            row["tg_id"],
            "❌ Твоя анкета отклонена.\nПожалуйста, заполни её заново — займет пару минут.",
            reply_markup=ik.as_markup(),
        )
@router.message(F.text == "📣 Рассылка")
async def msg_broadcast_start(m: types.Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    await state.set_state(BroadcastForm.waiting_text)
    await m.answer(
        "Введи текст рассылки.\n"
        "Доступные коды: {name}, {first_name}, {last_name}, {username}, {tg_id}.\n"
        "Пример: «Привет, {name}! Завтра урок в 19:00»\n\n"
        "Напиши «Отмена» чтобы выйти."
    )

@router.message(BroadcastForm.waiting_text, F.text.casefold() == "отмена")
async def msg_broadcast_cancel(m: types.Message, state: FSMContext):
    await state.clear()
    await m.answer("Отменил рассылку.")

@router.message(BroadcastForm.waiting_text)
async def msg_broadcast_run(m: types.Message, state: FSMContext):
    if not _is_admin(m.from_user.id):
        return
    tpl = m.text.strip()
    if not tpl:
        await m.answer("Пустой текст, отправь ещё раз или «Отмена».")
        return

    # берём все нужные поля для подстановки
    async with get_db() as db:
        cur = await db.execute("""
            SELECT id, tg_id, username, first_name, last_name
            FROM students
            WHERE tg_id IS NOT NULL
        """)
        students = await cur.fetchall()

    ok = fail = 0
    await m.answer(f"Начинаю рассылку ({len(students)} получателей)…")

    for s in students:
        try:
            text = render_broadcast(tpl, s)  # ← ПОДСТАВЛЯЕМ {name}, {first_name} и т.д.
            await m.bot.send_message(s["tg_id"], text)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)

    await state.clear()
    await m.answer(f"Готово. Успешно: {ok}, ошибок: {fail}.")

@router.message(Command("db"))
async def db_health(m: types.Message):
    try:
        async with get_db() as db:
            tables = []
            for t in ("students","test_results","points"):
                try:
                    cur = await db.execute(f"SELECT COUNT(*) FROM {t}")
                    n = (await cur.fetchone())[0]
                    tables.append(f"{t}={n}")
                except Exception as e:
                    tables.append(f"{t}=ERR({e})")
        await m.answer(f"DB={DB_PATH}\n" + "\n".join(tables))
    except Exception as e:
        await m.answer(f"DB open failed: {e}")