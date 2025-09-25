import asyncio
import aiosqlite
from bot.config import get_settings

NEEDED_STUDENTS_COLS = {
    "approved": "INTEGER NOT NULL DEFAULT 0",
    "rank": "TEXT",
    "rank_points": "INTEGER NOT NULL DEFAULT 0",
    "updated_at": "TEXT",
}

# bot/tools/migrate_fix.py

CREATE_INDEX_SQL = [
    # points: антидубль бонусов [cite: 3]
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_points_student_source ON points(student_id, source)",
    # progress: ускоряем напоминалки/подбор очереди [cite: 2]
    "CREATE INDEX IF NOT EXISTS idx_progress_status_remind ON progress(status, remind_at)",

    # НОВЫЕ ИНДЕКСЫ:
    # Ускоряем поиск по `tg_id` в таблице `students`
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_tg_id ON students(tg_id)",
    # Ускоряем запросы по статусу прогресса
    "CREATE INDEX IF NOT EXISTS idx_progress_status ON progress(status)",
    # Ускоряем поиск прогресса для конкретного студента
    "CREATE INDEX IF NOT EXISTS idx_progress_student ON progress(student_id)",
    # Ускоряем поиск прогресса по статусу и студенту
    "CREATE INDEX IF NOT EXISTS idx_progress_student_status ON progress(student_id, status)"
]

async def ensure_students_columns(db):
    # текущее состояние
    cur = await db.execute("PRAGMA table_info(students)")
    cols = {row[1] for row in await cur.fetchall()}

    for col, ddl in NEEDED_STUDENTS_COLS.items():
        if col not in cols:
            await db.execute(f"ALTER TABLE students ADD COLUMN {col} {ddl}")

async def ensure_indexes(db):
    for sql in CREATE_INDEX_SQL:
        await db.execute(sql)

async def main():
    settings = get_settings()
    async with aiosqlite.connect(settings.db_path) as db:
        db.row_factory = aiosqlite.Row
        await ensure_students_columns(db)
        await ensure_indexes(db)
        await db.commit()
    print("OK: schema fixed")

if __name__ == "__main__":
    asyncio.run(main())
