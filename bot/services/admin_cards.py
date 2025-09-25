# bot/services/admin_cards.py

from __future__ import annotations

from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup

from bot.config import get_settings, local_dt_str, now_utc_str


def render_submission_card(
    pid: int,
    tg_user: types.User,
    *,
    lesson_code: str | None,
    task_code: str | None,
    submitted_at_utc: str | None = None,
    add_open_chat_button: bool = True,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Сформировать текст карточки сдачи ДЗ для админа + инлайн-клавиатуру.
    Возвращает (card_text, reply_markup).
    """
    settings = get_settings()
    submitted_at_utc = submitted_at_utc or now_utc_str()

    title = "📝 <b>Новая сдача на проверку</b>"
    lines: list[str] = [
        "—" * 24,
        f"👤 Ученик: @{tg_user.username or tg_user.id}",
        f"📘 Урок: <b>{lesson_code or '—'}</b>",
        f"🧩 Раздел: <b>{task_code or '—'}</b>",
        f"🕒 Отправлено: <b>{local_dt_str(submitted_at_utc, settings.timezone)}</b>",
        f"🆔 PID: <code>{pid}</code>",
    ]
    card_text = "\n".join([title, *lines])

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Принять", callback_data=f"p_ok:{pid}")
    kb.button(text="↩️ Вернуть", callback_data=f"p_back:{pid}")
    if add_open_chat_button:
        kb.button(text="💬 Открыть чат", url=f"tg://user?id={tg_user.id}")
        kb.button(text="💬 Ответить", callback_data=f"adm_reply:{tg_user.id}")  # <-- новая кнопка
    kb.adjust(1)

    return card_text, kb.as_markup()

from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardMarkup

def help_reply_kb(tg_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💬 Ответить", callback_data=f"adm_reply:{tg_id}")
    kb.button(text="tg-профиль", url=f"tg://user?id={tg_id}")
    kb.adjust(1)  # вертикально
    return kb.as_markup()