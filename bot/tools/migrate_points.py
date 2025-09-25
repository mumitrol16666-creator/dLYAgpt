# bot/tools/migrate_points_ranks.py
from __future__ import annotations

import asyncio
from typing import Iterable

import aiosqlite

# Берём путь к БД из твоего конфига
from bot.config import get_settings

S = get_settings()


async def column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    cols = {r[1] for r in rows}  # r[1] = name
    return column in cols


async def table_exists(db: aiosqlite.Connection, table: str) -> bool:
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return await cur.fetchone() is not None


async def index_exists(db: aiosqlite.Connection, index: str) -> bool:
    cur = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (index,)
    )
    return await cur.fetchone() is not None


async def ensure_points_table(db: aiosqlite.Connection) -> None:
    # 1) Таблица points
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            amount INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # 2) Уникальный индекс (student_id, source)
    if not await index_exists(db, "idx_points_student_source"):
        await db.execute(
            "CREATE UNIQUE INDEX idx_points_student_source ON points(student_id, source)"
        )

    # 3) (Опционально) Индекс по student_id для ускорения SUM
    if not await index_exists(db, "idx_points_student"):
        await db.execute("CREATE INDEX idx_points_student ON points(student_id)")


async def ensure_students_rank_columns(db: aiosqlite.Connection) -> None:
    # Добавляем rank / rank_points, если их нет
    if not await column_exists(db, "students", "rank"):
        await db.execute("ALTER TABLE students ADD COLUMN rank TEXT")

    if not await column_exists(db, "students", "rank_points"):
        await db.execute("ALTER TABLE students ADD COLUMN rank_points INTEGER DEFAULT 0")


async def run_migration() -> None:
    print(f"[migrate] DB path: {S.db_path}")

    async with aiosqlite.connect(S.db_path) as db:
        db.row_factory = aiosqlite.Row

        # sanity: students должна существовать
        if not await table_exists(db, "students"):
            raise SystemExit(
                "Таблица 'students' не найдена. Запусти основную миграцию проекта или проверь путь к БД."
            )

        await ensure_points_table(db)
        await ensure_students_rank_columns(db)

        await db.commit()

    print("[migrate] OK: points/индексы созданы (если не было), колонки rank/rank_points добавлены (если не было).")


if __name__ == "__main__":
    asyncio.run(run_migration())
