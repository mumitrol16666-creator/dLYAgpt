# bot/tools/migrate_add_course_code.py
import asyncio
import aiosqlite
from bot.config import get_settings


async def column_exists(db: aiosqlite.Connection, table: str, column: str) -> bool:
    """Проверяет, существует ли колонка в таблице."""
    try:
        cur = await db.execute(f"PRAGMA table_info({table})")
        cols = {row[1] for row in await cur.fetchall()}
        return column in cols
    except aiosqlite.Error:
        return False


async def main():
    """Добавляет колонку course_code в таблицы payments и payment_requests."""
    settings = get_settings()
    db_path = settings.db_path
    print(f"Подключаюсь к БД: {db_path}")

    async with aiosqlite.connect(db_path) as db:
        # Добавляем колонку в таблицу payments
        if not await column_exists(db, "payments", "course_code"):
            print("Добавляю `course_code` в таблицу `payments`...")
            await db.execute("ALTER TABLE payments ADD COLUMN course_code TEXT;")
            print("...готово.")
        else:
            print("Колонка `course_code` в `payments` уже существует.")

        # Добавляем колонку в таблицу payment_requests
        if not await column_exists(db, "payment_requests", "course_code"):
            print("Добавляю `course_code` в таблицу `payment_requests`...")
            await db.execute("ALTER TABLE payment_requests ADD COLUMN course_code TEXT;")
            print("...готово.")
        else:
            print("Колонка `course_code` в `payment_requests` уже существует.")

        await db.commit()
        print("Миграция успешно завершена!")


if __name__ == "__main__":
    asyncio.run(main())