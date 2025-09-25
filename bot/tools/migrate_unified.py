import asyncio
import os
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

load_dotenv()

DB_PATH = (os.getenv("DB_PATH") or "maestro.db").strip() or "maestro.db"


async def table_exists(db: aiosqlite.Connection, name: str) -> bool:
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return await cur.fetchone() is not None


async def column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in await cur.fetchall()]
    return column in cols


async def index_exists(db: aiosqlite.Connection, name: str) -> bool:
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (name,))
    return await cur.fetchone() is not None


async def migrate_students(db: aiosqlite.Connection) -> None:
    if not await table_exists(db, "students"):
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS students(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tg_id INTEGER UNIQUE,
              username TEXT,
              created_at TEXT,
              first_name TEXT,
              last_name TEXT,
              birth_date TEXT,
              age INTEGER,
              has_guitar INTEGER DEFAULT 0,
              experience_months INTEGER DEFAULT 0,
              goal TEXT,
              phone TEXT,
              onboarding_done INTEGER DEFAULT 0,
              consent INTEGER DEFAULT 0,
              waiting_lessons INTEGER DEFAULT 0,
              last_known_max_lesson INTEGER DEFAULT 0,
              last_seen TEXT
            );
            """
        )
    else:
        cols = [
            ("tg_id", "INTEGER"),
            ("username", "TEXT"),
            ("created_at", "TEXT"),
            ("first_name", "TEXT"),
            ("last_name", "TEXT"),
            ("birth_date", "TEXT"),
            ("age", "INTEGER"),
            ("has_guitar", "INTEGER"),
            ("experience_months", "INTEGER"),
            ("goal", "TEXT"),
            ("phone", "TEXT"),
            ("onboarding_done", "INTEGER"),
            ("consent", "INTEGER"),
            ("waiting_lessons", "INTEGER"),
            ("last_known_max_lesson", "INTEGER"),
            ("last_seen", "TEXT"),
        ]
        for name, typ in cols:
            if not await column_exists(db, "students", name):
                if name in {"has_guitar", "experience_months", "onboarding_done", "consent",
                            "waiting_lessons", "last_known_max_lesson"}:
                    await db.execute(f"ALTER TABLE students ADD COLUMN {name} {typ} DEFAULT 0")
                else:
                    await db.execute(f"ALTER TABLE students ADD COLUMN {name} {typ}")
    await db.commit()


async def migrate_progress(db: aiosqlite.Connection) -> None:
    if not await table_exists(db, "progress"):
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS progress(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              student_id INTEGER,
              lesson_id INTEGER,
              lesson_code TEXT,
              task_code TEXT,
              status TEXT,
              sent_at TEXT,
              submitted_at TEXT,
              returned_at TEXT,
              approved_at TEXT,
              deadline_at TEXT,
              remind_at TEXT,
              reminded INTEGER DEFAULT 0,
              updated_at TEXT
            );
            """
        )
    else:
        cols = [
            ("student_id", "INTEGER"),
            ("lesson_id", "INTEGER"),
            ("lesson_code", "TEXT"),
            ("task_code", "TEXT"),
            ("status", "TEXT"),
            ("sent_at", "TEXT"),
            ("submitted_at", "TEXT"),
            ("returned_at", "TEXT"),
            ("approved_at", "TEXT"),
            ("deadline_at", "TEXT"),
            ("remind_at", "TEXT"),
            ("reminded", "INTEGER"),
            ("updated_at", "TEXT"),
        ]
        for name, typ in cols:
            if not await column_exists(db, "progress", name):
                if name == "reminded":
                    await db.execute(f"ALTER TABLE progress ADD COLUMN {name} {typ} DEFAULT 0")
                else:
                    await db.execute(f"ALTER TABLE progress ADD COLUMN {name} {typ}")

    if not await index_exists(db, "idx_progress_student_status"):
        await db.execute("CREATE INDEX idx_progress_student_status ON progress(student_id, status)")
    if not await index_exists(db, "idx_progress_remind"):
        await db.execute("CREATE INDEX idx_progress_remind ON progress(remind_at)")
    if not await index_exists(db, "idx_progress_updated"):
        await db.execute("CREATE INDEX idx_progress_updated ON progress(updated_at)")
    await db.commit()


async def migrate_payments(db: aiosqlite.Connection) -> None:
    if not await table_exists(db, "payments"):
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS payments(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              student_id INTEGER,
              amount INTEGER NOT NULL,
              method TEXT,
              note TEXT,
              paid_at TEXT NOT NULL,
              created_at TEXT
            );
            """
        )
    else:
        cols = [
            ("student_id", "INTEGER"),
            ("amount", "INTEGER"),
            ("method", "TEXT"),
            ("note", "TEXT"),
            ("paid_at", "TEXT"),
            ("created_at", "TEXT"),
        ]
        for name, typ in cols:
            if not await column_exists(db, "payments", name):
                await db.execute(f"ALTER TABLE payments ADD COLUMN {name} {typ}")
    if not await index_exists(db, "idx_payments_paid_at"):
        await db.execute("CREATE INDEX idx_payments_paid_at ON payments(paid_at)")
    await db.commit()


async def migrate_payment_requests(db: aiosqlite.Connection) -> None:
    if not await table_exists(db, "payment_requests"):
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS payment_requests(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              student_id INTEGER,
              amount INTEGER,
              status TEXT,
              created_at TEXT,
              resolved_at TEXT
            );
            """
        )
    else:
        cols = [
            ("student_id", "INTEGER"),
            ("amount", "INTEGER"),
            ("status", "TEXT"),
            ("created_at", "TEXT"),
            ("resolved_at", "TEXT"),
        ]
        for name, typ in cols:
            if not await column_exists(db, "payment_requests", name):
                await db.execute(f"ALTER TABLE payment_requests ADD COLUMN {name} {typ}")
    await db.commit()


async def migrate_points(db: aiosqlite.Connection) -> None:
    if not await table_exists(db, "points"):
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS points(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              student_id INTEGER,
              source TEXT,
              amount INTEGER,
              created_at TEXT
            );
            """
        )
    else:
        cols = [
            ("student_id", "INTEGER"),
            ("source", "TEXT"),
            ("amount", "INTEGER"),
            ("created_at", "TEXT"),
        ]
        for name, typ in cols:
            if not await column_exists(db, "points", name):
                await db.execute(f"ALTER TABLE points ADD COLUMN {name} {typ}")
    await db.commit()


async def migrate_views(db: aiosqlite.Connection) -> None:
    return


async def migrate():
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(db_path.as_posix()) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await migrate_students(db)
        await migrate_progress(db)
        await migrate_payments(db)
        await migrate_payment_requests(db)
        await migrate_points(db)
        await migrate_views(db)

    print("[OK] Миграция завершена успешно.")


if __name__ == "__main__":
    asyncio.run(migrate())
