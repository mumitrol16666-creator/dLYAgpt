from __future__ import annotations
import re
from pathlib import Path

from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings, now_utc_str, local_dt_str
from bot.keyboards.student import next_t_inline
from bot.routers.forms import SubmitForm, HelpForm
from bot.services.db import get_db
from bot.services.lessons import list_t_blocks, sort_materials

router = Router(name="lesson_flow")

TELEGRAM_LINK_RE = re.compile(
    r"^https?://t\.me/(?:(?P<user>[A-Za-z0-9_]+)/(?P<msg>\d+)|c/(?P<intid>\d+)/(?P<msg2>\d+))$"
)


def parse_tg_link(url: str):
    m = TELEGRAM_LINK_RE.match(url.strip())
    if not m:
        return None
    if m.group("user"):
        return ("@" + m.group("user"), int(m.group("msg")))
    return -100 * int(m.group("intid")), int(m.group("msg2"))


def _final_submit_kb(pid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Прикрепить работу", callback_data=f"submit_start:{pid}")
    kb.button(text="🆘 Помощь", callback_data=f"ask_help:{pid}")
    kb.button(text="🔁 Начать урок заново", callback_data=f"restart_lesson:{pid}")
    kb.adjust(1)
    return kb.as_markup()


def _resume_submit_kb(pid: int):
    kb = InlineKeyboardBuilder()
    kb.button(text="📤 Прикрепить работу", callback_data=f"submit_start:{pid}")
    kb.button(text="🆘 Помощь", callback_data=f"ask_help:{pid}")
    kb.button(text="🔁 Начать урок заново", callback_data=f"restart_lesson:{pid}")
    kb.adjust(1)
    return kb.as_markup()


async def _send_materials_from_dir(bot: Bot, chat_id: int, directory: Path):
    """Вспомогательная функция для отправки всех материалов из папки."""
    if not directory.is_dir():
        return

    files = sort_materials(directory)
    for p in files:
        ext = p.suffix.lower()
        try:
            if ext in {".mp4", ".mov", ".m4v", ".avi", ".mkv"}:
                await bot.send_video(chat_id, video=FSInputFile(str(p)))
            elif ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                await bot.send_photo(chat_id, photo=FSInputFile(str(p)))
            elif ext in {".txt", ".md"}:
                txt = p.read_text(encoding="utf-8", errors="ignore").strip()
                if "\n" not in txt and " " not in txt:
                    tg = parse_tg_link(txt)
                    if tg:
                        from_chat_id, msg_id = tg
                        await bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=msg_id)
                        continue
                if len(txt) > 4000:
                    txt = txt[:3900] + "...\n(текст обрезан)"
                await bot.send_message(chat_id, txt)
            else:
                await bot.send_document(chat_id, document=FSInputFile(str(p)))
        except Exception as e:
            await bot.send_message(chat_id, f"(не удалось отправить файл {p.name}: {e})")


async def send_current_t_view(bot: Bot, chat_id: int, progress_id: int):
    settings = get_settings()
    async with get_db() as db:
        cur = await db.execute("SELECT lesson_code, task_code FROM progress WHERE id=?", (progress_id,))
        pr = await cur.fetchone()
    if not pr:
        await bot.send_message(chat_id, "Прогресс не найден.")
        return

    full_lesson_code = (pr["lesson_code"] or "").strip()
    task_code = (pr["task_code"] or "").strip()

    try:
        course_code, lesson_folder = full_lesson_code.split(":", 1)
    except ValueError:
        await bot.send_message(chat_id, "Ошибка в коде урока.")
        return

    lesson_dir = settings.lessons_path / course_code / lesson_folder
    t_list = list_t_blocks(lesson_dir)
    if not t_list:
        await bot.send_message(chat_id, "Материалы для этого урока не найдены.")
        return

    if task_code.startswith("T") and task_code in t_list:
        t_code = task_code
    elif task_code == "DONE":
        t_code = t_list[-1]
    else:
        t_code = t_list[0]

    await bot.send_message(
        chat_id,
        f"🧩 Последний раздел <b>{t_code}</b> урока <b>{lesson_folder}</b> 👇",
        parse_mode="HTML",
    )

    await _send_materials_from_dir(bot, chat_id, lesson_dir / t_code)

    await bot.send_message(
        chat_id,
        "Готов сдавать — жми «📤 Прикрепить работу». Запутался — «🆘 Помощь». "
        "Нужно с нуля — «🔁 Начать урок заново».",
        reply_markup=_resume_submit_kb(progress_id),
    )


async def send_next_t_block(bot: Bot, chat_id: int, progress_id: int, first: bool = False):
    settings = get_settings()
    async with get_db() as db:
        cur = await db.execute(
            "SELECT p.id, p.student_id, p.lesson_code, p.task_code, p.deadline_at FROM progress p WHERE p.id=?",
            (progress_id,),
        )
        pr = await cur.fetchone()

    if not pr:
        await bot.send_message(chat_id, "Прогресс не найден.")
        return

    full_lesson_code: str = pr["lesson_code"]
    task_code: str | None = pr["task_code"]

    try:
        course_code, lesson_folder = full_lesson_code.split(":", 1)
    except ValueError:
        await bot.send_message(chat_id, "Ошибка в коде урока. Сообщите администратору.")
        return

    lesson_dir = settings.lessons_path / course_code / lesson_folder
    t_list = list_t_blocks(lesson_dir)
    if not t_list:
        await bot.send_message(chat_id, "Материалы урока не найдены.")
        return

    current_idx = -1
    if task_code and task_code.startswith("T"):
        try:
            current_idx = t_list.index(task_code)
        except ValueError:
            pass

    next_idx = current_idx + 1

    if next_idx >= len(t_list):
        async with get_db() as db:
            await db.execute("UPDATE progress SET task_code='DONE', updated_at=? WHERE id=?",
                             (now_utc_str(), progress_id))
            await db.commit()
        dl = local_dt_str(pr["deadline_at"], settings.timezone) if pr["deadline_at"] else "—"
        await bot.send_message(
            chat_id,
            f"Урок готов ✅\nДедлайн: <b>{dl}</b>\n🎯 За выполнение получишь: <b>100 баллов</b>\n\n"
            f"Сдай работу через кнопку ниже.",
            reply_markup=_final_submit_kb(progress_id),
        )
        return

    t_code = t_list[next_idx]
    t_dir = lesson_dir / t_code

    header_text = f"Задание <b>{t_code}</b> 👇"
    if first:
        header_text = f"🎸 Урок <b>{lesson_folder}</b>. {header_text}"
    await bot.send_message(chat_id, header_text)

    await _send_materials_from_dir(bot, chat_id, t_dir)

    has_next = (next_idx + 1) < len(t_list)

    if has_next:
        await bot.send_message(
            chat_id, "Готов перейти к следующему разделу?", reply_markup=next_t_inline(progress_id, has_next=True)
        )
        async with get_db() as db:
            await db.execute("UPDATE progress SET task_code=?, updated_at=? WHERE id=?",
                             (t_code, now_utc_str(), progress_id))
            await db.commit()
    else:
        async with get_db() as db:
            await db.execute("UPDATE progress SET task_code='DONE', updated_at=? WHERE id=?",
                             (now_utc_str(), progress_id))
            await db.commit()
        dl = local_dt_str(pr["deadline_at"], settings.timezone) if pr["deadline_at"] else "—"
        await bot.send_message(
            chat_id,
            f"✅ Урок пройден \nДедлайн: <b>{dl}</b>\nОбязательно приложи свою работу, чтобы получить рекомендации и пройти урок.",
            reply_markup=_final_submit_kb(progress_id),
        )


@router.callback_query(F.data.startswith("next_t:"))
async def cb_next_t(cb: types.CallbackQuery):
    pid = int(cb.data.split(":")[1])
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_next_t_block(cb.message.bot, cb.message.chat.id, pid, first=False)


@router.callback_query(F.data.startswith("submit_start:"))
async def cb_submit_start(cb: types.CallbackQuery, state: FSMContext):
    pid = int(cb.data.split(":")[1])
    async with get_db() as db:
        await db.execute("UPDATE progress SET status='sent', updated_at=? WHERE id=?", (now_utc_str(), pid))
        await db.commit()
    await state.set_state(SubmitForm.waiting_work)
    await state.update_data(progress_id=pid)
    await cb.answer()
    await cb.message.answer("Пришли сюда фото/видео/документ или текст с ответом — я передам его на проверку")


@router.callback_query(F.data.startswith("ask_help:"))
async def cb_ask_help(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(HelpForm.waiting_text)
    await cb.message.answer("Опиши, что непонятно — передам админам.")
    await cb.answer()


@router.callback_query(F.data.startswith("restart_lesson:"))
async def cb_restart_lesson(cb: types.CallbackQuery):
    try:
        pid = int(cb.data.split(":")[1])
    except Exception:
        await cb.answer("Ошибка перезапуска.", show_alert=True)
        return
    async with get_db() as db:
        await db.execute("UPDATE progress SET task_code=NULL, status='sent', updated_at=? WHERE id=?",
                         (now_utc_str(), pid))
        await db.commit()
    await cb.answer("Урок начат заново.")
    await send_next_t_block(cb.message.bot, cb.message.chat.id, pid, first=True)