import asyncio
import aiosqlite
import logging

from bot.config import get_settings
from bot.services.db import get_db, _prepare_conn # <-- Импортируем служебные функции
from .migrate_schema import migrate as migrate_schema # <-- Импортируем миграцию схемы
from .migrate_points import run_migration as migrate_points # <-- Импортируем миграцию поинтов


async def clear_db():
    settings = get_settings()

    async with aiosqlite.connect(settings.db_path) as db:
        # отключаем проверки foreign key (иначе не даст удалить)
        await db.execute("PRAGMA foreign_keys = OFF;")

        # получаем список всех таблиц
        cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = await cur.fetchall()

        for (table,) in tables:
            if table == "sqlite_sequence":  # служебная таблица (автоинкременты)
                continue
            await db.execute(f"DELETE FROM {table};")

        # сброс автоинкрементов
        await db.execute("DELETE FROM sqlite_sequence;")
        await db.commit()

    logging.info("✅ Все таблицы очищены.")


async def prepare_db():
    """
    Универсальный скрипт:
    1. Очищает базу данных.
    2. Запускает все миграции.
    """
    settings = get_settings()
    db_path = settings.db_path

    # Шаг 1: очистка (используем уже имеющуюся логику)
    try:
        await clear_db()
    except Exception as e:
        logging.error(f"Не удалось очистить БД: {e}")
        # Если очистка не удалась, продолжаем, чтобы хотя бы миграция сработала
        pass

    # Шаг 2: запуск миграций (импортируем и вызываем)
    logging.info("🔧 Запускаю миграцию схемы...")
    try:
        await migrate_schema()
        logging.info("✅ Миграция схемы завершена.")
    except Exception as e:
        logging.error(f"❌ Ошибка миграции схемы: {e}")
        return

    logging.info("🔧 Запускаю миграцию точек и рангов...")
    try:
        await migrate_points()
        logging.info("✅ Миграция точек и рангов завершена.")
    except Exception as e:
        logging.error(f"❌ Ошибка миграции точек и рангов: {e}")
        return

    logging.info("🎉 База данных полностью подготовлена к работе!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(prepare_db())