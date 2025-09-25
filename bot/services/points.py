# bot/services/points.py
from __future__ import annotations

import aiosqlite
from typing import Optional

from bot.services.db import get_db
from bot.config import now_utc_str


async def add(student_id: int, source: str, amount: int) -> bool:
    """
    Безопасно начисляет баллы.
    Возвращает True, если запись добавлена; False, если такой source уже есть (антидубль).
    Требуется уникальный индекс points(student_id, source).
    """
    if not source:
        raise ValueError("source must be non-empty")
    if amount == 0:
        return False

    try:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO points(student_id, source, amount, created_at) VALUES(?,?,?,?)",
                (student_id, source, amount, now_utc_str()),
            )
            await db.commit()
        return True
    except aiosqlite.IntegrityError:
        # Нарвались на UNIQUE(student_id, source) — начисление уже было.
        return False


async def total(student_id: int) -> int:
    """
    Возвращает суммарные баллы студента (сумма по points.amount).
    """
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COALESCE(SUM(amount),0) AS s FROM points WHERE student_id=?",
            (student_id,),
        )
        row = await cur.fetchone()
    return int(row["s"] if row and row["s"] is not None else 0)
