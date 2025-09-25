from __future__ import annotations
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from aiogram import Bot

# --- ИСПРАВЛЕННЫЕ ИМПОРТЫ ---
# Мы объединили все импорты в один блок, чтобы не было дублирования.
from bot.services.db import get_db
from bot.config import get_settings, now_utc_str
from bot.services.lessons import list_l_lessons, parse_l_num
from . import points  # <-- ИСПРАВЛЕННЫЙ ИМПОРТ для points.py
# ---------------------------


# Тексты напоминаний по нарастающей строгости
REMINDER_TEXTS = [
    "👋 Напоминание: у тебя есть задание. Не забудь его сдать!",
    "⚡ Пора двигаться дальше — жду твою работу.",
    "🔥 Ты близок к следующему уровню. Сдай задание и получи баллы!",
]
# После этого количества напоминаний — перестаём слать (гасим remind_at)
MAX_REMIND_COUNT = len(REMINDER_TEXTS)

# Интервал между напоминаниями (MVP: 24 часа)
REMIND_INTERVAL_HOURS = 24

# Интервал цикла воркера
LOOP_SLEEP_SECONDS = 600


async def _send_progress_reminders(bot: Bot) -> None:
    """
    Шлём напоминания по прогрессам со статусами 'sent'/'returned',
    у которых remind_at <= now. Используем счётчик reminded для эскалации.
    """
    now_iso = now_utc_str()

    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT p.id, p.student_id, p.remind_at, p.reminded, p.status,
                   s.tg_id
            FROM progress p
            JOIN students s ON s.id = p.student_id
            WHERE p.status IN ('sent','returned')
              AND p.remind_at IS NOT NULL
              AND p.remind_at <= ?
            """,
            (now_iso,),
        )
        rows = await cur.fetchall()

        for r in rows:
            pid = r["id"]
            tg_id = r["tg_id"]
            reminded = (r["reminded"] or 0)

            # Выбираем текст по индексу, после лимита больше не шлём
            if reminded >= MAX_REMIND_COUNT:
                # Гасим дальнейшие напоминания
                await db.execute(
                    "UPDATE progress SET remind_at=NULL, updated_at=? WHERE id=?",
                    (now_iso, pid),
                )
                continue

            text = REMINDER_TEXTS[min(reminded, MAX_REMIND_COUNT - 1)]

            try:
                await bot.send_message(tg_id, text)
            except Exception:
                # не валимся из-за сетевых/блокировок
                pass

            # Сдвигаем следующее окно + увеличиваем счётчик
            next_at = (
                datetime.now(timezone.utc) + timedelta(hours=REMIND_INTERVAL_HOURS)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

            await db.execute(
                "UPDATE progress SET remind_at=?, reminded=COALESCE(reminded,0)+1, updated_at=? WHERE id=?",
                (next_at, now_iso, pid),
            )

        await db.commit()


async def _notify_waiting_lessons(bot: Bot) -> None:
    """
    Если у ученика стоит waiting_lessons=1 и появился новый L-урок — уведомляем.
    Сбрасываем флаг и обновляем last_known_max_lesson.
    """
    settings = get_settings()
    lessons_dir = Path(settings.lessons_path)

    lessons = list_l_lessons(lessons_dir)
    current_max = 0
    for code in lessons:
        n = parse_l_num(code) or 0
        if n > current_max:
            current_max = n

    if current_max <= 0:
        return

    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, tg_id, last_known_max_lesson FROM students WHERE waiting_lessons=1"
        )
        students_rows = await cur.fetchall()

        for s in students_rows:
            last_known = s["last_known_max_lesson"] or 0
            if current_max > last_known:
                try:
                    await bot.send_message(
                        s["tg_id"],
                        "Появились новые уроки! Можно продолжить обучение 🎸"
                    )
                except Exception:
                    pass

                await db.execute(
                    "UPDATE students SET waiting_lessons=0, last_known_max_lesson=? WHERE id=?",
                    (current_max, s["id"]),
                )

        await db.commit()


async def _auto_approve_submitted_lessons(bot: Bot) -> None:
    now_iso = now_utc_str()

    async with get_db() as db:
        # Ищем работы, которые были сданы более 10 минут назад
        # и ещё не приняты.
        cur = await db.execute(
            """
            SELECT p.id, s.tg_id, s.id AS sid
            FROM progress p
            JOIN students s ON s.id = p.student_id
            WHERE p.status = 'submitted'
              AND p.submitted_at <= datetime('now', '-10 minutes') || 'Z'
            """
        )
        rows = await cur.fetchall()

        for r in rows:
            pid, tg_id, sid = r['id'], r['tg_id'], r['sid']

            # Обновляем статус на 'approved'
            await db.execute(
                "UPDATE progress SET status='approved', approved_at=?, updated_at=? WHERE id=?",
                (now_iso, now_iso, pid),
            )

            # Начисляем 100 баллов
            try:
                # Используем идемпотентный метод для начисления
                await points.add(sid, f"lesson_approved_auto:{pid}", 100)
            except Exception:
                pass

            # Отправляем уведомление ученику
            await bot.send_message(tg_id, "✅ Твоя работа была автоматически принята. Держи 100 баллов!")

        await db.commit()

async def reminder_loop(bot: Bot):
    # ...
    while True:
        try:
            await _send_progress_reminders(bot)
            # Добавим новую функцию в цикл
            await _auto_approve_submitted_lessons(bot)
            #await _notify_waiting_lessons(bot)
        except Exception as e:
            # ... (логирование)
            print("[reminder_loop] error:", e)

        await asyncio.sleep(LOOP_SLEEP_SECONDS)