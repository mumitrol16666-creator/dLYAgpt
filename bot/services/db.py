# bot/services/db.py
import os, logging, contextlib
from pathlib import Path
import aiosqlite

# Абсолютный путь к БД: <repo_root>/data/bot.db (или DB_PATH из .env)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "bot.db"
DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)

DB_PATH = os.path.expanduser(os.path.expandvars(os.getenv("DB_PATH") or str(DEFAULT_DB)))
_LOGGED = False  # лог пути один раз

async def _prepare_conn(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA foreign_keys=ON;")
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute("PRAGMA busy_timeout=5000;")

@contextlib.asynccontextmanager
async def get_db():
    global _LOGGED
    if not _LOGGED:
        logging.warning("SQLite path: %s", os.path.abspath(DB_PATH))
        _LOGGED = True
    db = await aiosqlite.connect(DB_PATH, timeout=30)
    try:
        db.row_factory = aiosqlite.Row
        await _prepare_conn(db)
        yield db
    finally:
        await db.close()

# Одноразовая инициализация/миграции (вызови при старте)
async def init_db():
    async with aiosqlite.connect(DB_PATH, timeout=30) as db:
        db.row_factory = aiosqlite.Row
        await _prepare_conn(db)

        # --- таблицы ---
        await db.execute("""
            CREATE TABLE IF NOT EXISTS test_results (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                test_code TEXT NOT NULL,
                correct_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                passed INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS points (
                id INTEGER PRIMARY KEY,
                student_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                amount INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        # --- индексы (антидубли) ---
        await db.execute("DROP INDEX IF EXISTS ux_test_results;")  # старый, неправильный
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_test_results_user_code
            ON test_results(user_id, test_code);
        """)
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_points_student_source
            ON points(student_id, source);
        """)

        await db.commit()
