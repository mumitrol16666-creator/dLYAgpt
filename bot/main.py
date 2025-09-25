# bot/main.py
import asyncio
import logging
from contextlib import suppress
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.middlewares.block_until_done import BlockUntilDoneMiddleware
from bot.routers.onboarding import router as onboarding_router
from bot.routers.student import router as student_router
from bot.routers.lesson_flow import router as lesson_flow_router
from bot.routers.admin import router as admin_router
from bot.routers.admin_reply import router as admin_reply_router
from bot.services.reminder_worker import reminder_loop
from bot.services.db import DB_PATH
import logging
from bot.routers.fallback import router as fallback_router
from bot.routers.debug import router as debug_router
from aiogram import Dispatcher
from bot.routers.tests.entry import router as tests_entry_router
from bot.routers.tests.engine import router as tests_engine_router
from bot.routers.tests.deeplink import router as deeplink_router
from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode

settings = get_settings()
logging.warning("ADMINS -> %s", settings.admin_ids)

logging.basicConfig(
    level=logging.INFO,  # общий уровень логов
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# создаём отдельный логгер для проекта
logger = logging.getLogger("maestro")
logger.setLevel(logging.INFO)

async def on_startup(bot: Bot) -> None:
    # Запускаем фоновый воркер как task_of(bot)
    bot.reminder_task = asyncio.create_task(reminder_loop(bot), name="reminder_loop")
    logging.warning("Reminder loop started")

async def on_shutdown(bot: Bot) -> None:
    # Отменяем фоновый воркер при остановке бота
    if (task := getattr(bot, "reminder_task", None)):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    logging.warning("Reminder loop stopped")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    logging.warning("DB in use -> %s", DB_PATH)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Роутеры
    dp.include_router(onboarding_router)
    dp.include_router(tests_entry_router)
    dp.include_router(tests_engine_router)
    dp.include_router(lesson_flow_router)
    dp.include_router(admin_router)
    dp.include_router(admin_reply_router)
    dp.include_router(student_router)

    # <<< ИЗМЕНЕНИЕ: fallback ловит "понятные" команды, которые не дошли до других
    dp.include_router(fallback_router)

    # <<< ИЗМЕНЕНИЕ: debug ловит ВООБЩЕ ВСЁ ОСТАЛЬНОЕ. Он должен быть последним.
    dp.include_router(debug_router)

    # Сбрасываем вебхук и висящие апдейты до старта
    await bot.delete_webhook(drop_pending_updates=True)

    try:
        # Ровно один запуск поллинга
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())