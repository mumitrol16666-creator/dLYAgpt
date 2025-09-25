# bot/services/tests/progress.py
from typing import Literal
from aiogram import Bot, types
from bot.services.db import get_db
from bot.services.points import add
from bot.services.tests.registry import TestMeta
from bot.config import get_settings, now_utc_str

Status = Literal["locked", "available", "passed"]

PASS_THRESHOLD_PCT = 80
PASS_REWARD = 50
COOLDOWN_HOURS = 24  # 1 попытка/сутки (0 — выключить)


def is_passed(correct: int, total: int) -> bool:
    return total > 0 and correct * 100 >= total * PASS_THRESHOLD_PCT


def is_unlocked(user_passed: set[str], depends_on: str | None) -> bool:
    return True if not depends_on else (depends_on in user_passed)


async def _get_student_row_by_tg_id(tg_id: int):
    """Возвращает row с полями id, approved по tg_id или None."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id, COALESCE(approved,0) AS approved FROM students WHERE tg_id=?",
            (tg_id,)
        )
        return await cur.fetchone()


async def user_passed_codes(user_tg_id: int) -> set[str]:
    async with get_db() as db:
        cur = await db.execute("SELECT id FROM students WHERE tg_id=?", (user_tg_id,))
        s = await cur.fetchone()
        if not s: return set()
        cur = await db.execute(
            "SELECT test_code FROM test_results WHERE user_id=? AND passed=1", (s["id"],)
        )
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def write_result_and_reward(
    user_id: int,
    meta: TestMeta,
    correct_count: int,
    total_count: int,
    tg_user: types.User,
    bot: Bot,
):
    passed = is_passed(correct_count, total_count)
    now = now_utc_str()

    # 1) находим студента по tg_id
    student = await _get_student_row_by_tg_id(user_id)
    if not student:
        return
    student_id = student["id"]
    approved = int(student["approved"])

    # 2) апсерт результата по (student_id, meta.code)
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id FROM test_results WHERE user_id=? AND test_code=?",
            (student_id, meta.code)
        )
        existing = await cur.fetchone()

        if existing:
            await db.execute(
                "UPDATE test_results "
                "SET correct_count=?, total_count=?, passed=?, updated_at=? "
                "WHERE id=?",
                (correct_count, total_count, int(passed), now, existing["id"])
            )
        else:
            await db.execute(
                "INSERT INTO test_results "
                "(user_id, test_code, correct_count, total_count, passed, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (student_id, meta.code, correct_count, total_count, int(passed), now, now)
            )
        await db.commit()

    # 3) если прошёл и одобрен — начисляем +50 и уведомляем админов
    if passed and approved:
        # порядок аргументов: (student_id, source, amount)
        await add(student_id, f"Тест: {meta.title}", PASS_REWARD)
