# bot/routers/tests/engine.py

from __future__ import annotations
import logging
import os
import random
import asyncio
import contextlib
import json
from collections import defaultdict
from html import escape as h
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from aiogram import F, Router, types
from aiogram.client.bot import Bot
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.student import student_main_kb
from bot.routers.tests.state import TestsFlow
from bot.services.tests.progress import (
    write_result_and_reward,
    is_passed,
    PASS_THRESHOLD_PCT,
)
from bot.services.tests.registry import TestMeta
from bot.config import get_settings

router = Router(name="tests_engine")
log = logging.getLogger(__name__)

# ===================== НАСТРОЙКИ ======================
TIME_PER_Q = 30  # секунд на вопрос (Telegram open_period поддерживает 5..600)

# ===================== ГЛОБАЛЬНОЕ СОСТОЯНИЕ ======================
# user_id -> {chat_id, tg_user, meta, qs, idx, correct, last_poll_msg_id, timer_task, state}
SESSIONS: Dict[int, Dict[str, Any]] = {}

# poll_id -> (user_id, idx)
POLL_MAP: Dict[str, tuple[int, int]] = {}

# дедупликация обработки конкретного poll (answer/closed/наш таймер)
FINALIZED_POLLS: set[str] = set()

# локи по пользователю, чтобы не было гонок на один и тот же шаг
USER_LOCKS: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

# лимиты Telegram для send_poll
MAX_Q   = 300   # длина question
MAX_OPT = 100   # длина одного варианта
MAX_EXP = 200   # длина explanation


# ===================== ВСПОМОГАТЕЛЬНОЕ ======================

def _kb_for_question() -> InlineKeyboardMarkup:
    """Клавиатура под вопросом: только 'Отменить тест'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⛔ Отменить тест", callback_data="quiz_cancel")]]
    )


# --- УДАЛЁННАЯ ФУНКЦИЯ ---
# def _get_admin_ids() -> list[int]:
#     ids: list[int] = []
#     ... (старая логика сбора ID из .env)
#     return ids

def _load_questions(meta: TestMeta) -> List[SimpleNamespace]:
    """Читаем JSON meta.file и отдаём список объектов {q, options, correct_idx, why?}."""
    p = Path(meta.file)
    if not p.exists():
        raise FileNotFoundError(f"Test file not found: {p}")

    raw = json.loads(p.read_text(encoding="utf-8"))

    # поддерживаем оба формата:
    # 1) {"questions": [...]}  2) [...]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("questions") or raw.get("items") or raw.get("data")
    else:
        items = None

    if not isinstance(items, list) or not items:
        raise ValueError(f"{p} has no questions array")

    out: List[SimpleNamespace] = []
    for i, it in enumerate(items, 1):
        q = it.get("q")
        options = it.get("options")
        correct_idx = it.get("correct_idx")
        why = it.get("why")
        if not isinstance(q, str) or not q.strip():
            raise ValueError(f"{p}: question #{i} has empty 'q'")
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError(f"{p}: question #{i} has invalid 'options'")
        if not isinstance(correct_idx, int) or not (0 <= correct_idx < len(options)):
            raise ValueError(f"{p}: question #{i} has invalid 'correct_idx'")
        out.append(SimpleNamespace(q=q, options=options, correct_idx=correct_idx, why=why))
    return out


def shuffle_options(options: List[str], correct_idx: int) -> Tuple[List[str], int]:
    """Перемешать варианты и пересчитать индекс правильного."""
    pairs = list(enumerate(options))
    random.shuffle(pairs)
    new_options = [t for _, t in pairs]
    new_correct_idx = next(i for i, (j, _) in enumerate(pairs) if j == correct_idx)
    return new_options, new_correct_idx


def _normalize_poll(prefix: str,
                    question: str,
                    options: List[str],
                    explanation: Optional[str]
                   ) -> Tuple[str, List[str], Optional[str]]:
    """
    Обрезает текст вопроса/вариантов/объяснения под лимиты Telegram, делает варианты уникальными.
    """
    # Вопрос (учитываем длину префикса "Вопрос X/Y:\n")
    body = (question or "").strip()
    room = MAX_Q - len(prefix)
    if room < 1:
        room = 1
    if len(body) > room:
        body = body[:room - 1].rstrip() + "…"
    q_text = prefix + body

    # Варианты: <=100, без пустых, уникальные после обрезки
    out: List[str] = []
    seen: set[str] = set()
    for i, opt in enumerate(options or []):
        s = (opt or "").strip() or f"Вариант {i+1}"
        if len(s) > MAX_OPT:
            s = s[:MAX_OPT - 1].rstrip() + "…"
        base, k = s, 1
        while s in seen:
            suffix = f" ({k})"
            s = base[:MAX_OPT - len(suffix)] + suffix
            k += 1
        seen.add(s)
        out.append(s)

    # Explanation: <=200
    exp = None
    if explanation:
        exp = explanation.strip()
        if len(exp) > MAX_EXP:
            exp = exp[:MAX_EXP - 1].rstrip() + "…"

    if not (2 <= len(out) <= 10):
        raise ValueError(f"Некорректное число вариантов: {len(out)} (нужно 2–10)")

    return q_text, out, exp


def _compose_explanation(q: SimpleNamespace) -> Optional[str]:
    """
    Собираем пояснение после неверного ответа:
    - текст правильного варианта (в ТЕКУЩЕМ порядке после нормализации)
    - блок 'Почему' из _explanation (если есть) или из why
    """
    try:
        correct_text = q.options[q.correct_idx]
    except Exception:
        return None
    why = getattr(q, "_explanation", None) or getattr(q, "why", None)
    parts = [f"Правильный ответ: {correct_text}"]
    if isinstance(why, str) and why.strip():
        parts.append(f"Почему: {why.strip()}")
    return "\n".join(parts)


async def _deadline_watch(
    user_id: int,
    poll_id: str,
    chat_id: int,
    idx_at_start: int,
    seconds: int,
    bot: Bot,
) -> None:
    """Серверный таймер: время вышло → финализируем как неверный → далее/финиш."""
    try:
        await asyncio.sleep(seconds + 0.5)
    except asyncio.CancelledError:
        return

    lock = USER_LOCKS[user_id]
    async with lock:
        st = SESSIONS.get(user_id)
        if not st:
            return
        if st["idx"] != idx_at_start:
            return
        if poll_id in FINALIZED_POLLS:
            return
        FINALIZED_POLLS.add(poll_id)
        POLL_MAP.pop(poll_id, None)

        msg_id = st.get("last_poll_msg_id")
        if msg_id:
            with contextlib.suppress(Exception):
                await bot.stop_poll(chat_id, msg_id)

        await _finalize_step(user_id, idx_at_start, is_correct=False, bot=bot)
        st.pop("timer_task", None)


# ===================== ОСНОВНОЙ ПОТОК ВОПРОСА ======================

async def _send_q(user_id: int, bot: Bot) -> None:
    """Отправка очередного вопроса (poll) + запуск серверного таймера."""
    st = SESSIONS[user_id]
    idx: int = st["idx"]
    qs = st["qs"]
    q = qs[idx]
    chat_id = st["chat_id"]

    kb = _kb_for_question()

    # 1) Перемешиваем варианты и пересчитываем индекс правильного (каждый раз при показе)
    opts_shuf, cid = shuffle_options(q.options, q.correct_idx)

    # 2) Нормализуем под лимиты Telegram
    prefix = f"Вопрос {idx + 1}/{len(qs)}:\n"
    q_text, opts_norm, expl = _normalize_poll(prefix, q.q, opts_shuf, getattr(q, "why", None))

    # 3) Сохраняем ТОЧНО то, что показали (важно для корректного фидбека/проверки)
    q.options = opts_norm
    q.correct_idx = cid
    q._shown_question = q_text
    q._explanation = expl

    # 4) Отправляем quiz-опрос
    open_sec = max(5, min(600, TIME_PER_Q))
    poll_msg = await bot.send_poll(
        chat_id=chat_id,
        question=q_text,
        options=opts_norm,
        type="quiz",
        correct_option_id=cid,
        is_anonymous=False,
        open_period=open_sec,      # визуал; логику держим на своём таймере
        explanation=expl or None,  # покажется в хинте Telegram после ответа
        reply_markup=kb,
    )

    # 5) Привязываем poll_id -> (user, question_idx) и запускаем дедлайн
    POLL_MAP[poll_msg.poll.id] = (user_id, idx)
    st["last_poll_msg_id"] = poll_msg.message_id

    if (old := st.get("timer_task")):
        old.cancel()
    st["timer_task"] = asyncio.create_task(
        _deadline_watch(user_id, poll_msg.poll.id, chat_id, idx, open_sec, bot),
        name=f"quiz_deadline_{user_id}_{idx}",
    )


async def _finalize_step(user_id: int, idx: int, is_correct: bool, bot: Bot) -> None:
    """Финализация шага: фидбек, счёт, переход к следующему/финиш."""
    st = SESSIONS.get(user_id)
    if not st:
        return

    if is_correct:
        await bot.send_message(st["chat_id"], "✅ Верно", parse_mode=None)
        st["correct"] += 1
    else:
        # показываем правильный вариант + почему
        q = st["qs"][idx]
        expl_text = _compose_explanation(q)
        msg = "❌ Неверно"
        if expl_text:
            msg += "\n" + expl_text
        await bot.send_message(st["chat_id"], msg, parse_mode=None)

    st["idx"] += 1
    if st["idx"] >= len(st["qs"]):
        await _finish(user_id, bot)
    else:
        await asyncio.sleep(0.2)
        await _send_q(user_id, bot)


async def _finish(user_id: int, bot: Bot) -> None:
    """Финал теста: запись результата, уведомление админам, сброс FSM, меню."""
    st = SESSIONS.pop(user_id, None)
    if not st:
        return

    # остановить таймер, если был
    if (t := st.get("timer_task")):
        t.cancel()

    # подчистить висячие poll'ы этого пользователя
    for pid, (uid, _) in list(POLL_MAP.items()):
        if uid == user_id:
            POLL_MAP.pop(pid, None)
            FINALIZED_POLLS.add(pid)

    correct = int(st.get("correct", 0))
    total = len(st["qs"])
    passed = is_passed(correct, total)
    chat_id = st["chat_id"]

    # сброс FSM-состояния теста
    state: Optional[FSMContext] = st.get("state")
    if state:
        with contextlib.suppress(Exception):
            await state.clear()

    # финальное сообщение ученику
    if passed:
        text = (
            f"✅ Тест пройден!\n"
            f"Результаты: {correct} из {total} правильных (порог {PASS_THRESHOLD_PCT}% и выше).\n"
            f"Баллы начислены (если профиль одобрен)."
        )
    else:
        text = (
            f"❌ Тест не пройден.\n"
            f"Результаты: {correct} из {total} правильных (меньше {PASS_THRESHOLD_PCT}%).\n"
            f"Попробуй снова завтра."
        )
    await bot.send_message(chat_id, text, parse_mode=None)

    # запись результата и (если нужно) внутренняя рассылка/награда
    with contextlib.suppress(Exception):
        await write_result_and_reward(
            user_id=user_id,
            meta=st.get("meta"),
            correct_count=correct,
            total_count=total,
            tg_user=st.get("tg_user"),
            bot=bot,
        )

    # уведомление админам
    try:
        tg_user = st.get("tg_user")
        meta = st.get("meta")
        title = getattr(meta, "title", None) or str(getattr(meta, "code", ""))
        pct = round((correct * 100) / total) if total else 0
        uname = f"@{tg_user.username}" if getattr(tg_user, "username", None) else "—"
        admin_msg = (
            "🧪 Результат теста\n"
            f"Тест: {title}\n"
            f"Ученик: {tg_user.full_name} {uname}\n"
            f"Telegram ID: {user_id}\n"
            f"Итог: {correct}/{total} ({pct}%) — {'ПРОЙДЕН' if passed else 'НЕ ПРОЙДЕН'}"
        )
        settings = get_settings()
        admin_ids = settings.admin_ids
        if not admin_ids:
            log.warning("[tests_engine] skip admin notify: no ADMIN ids configured")
        else:
            for aid in admin_ids:
                with contextlib.suppress(Exception):
                    await bot.send_message(aid, admin_msg)

    except Exception:
        pass

    await bot.send_message(chat_id, "Возвращаю в главное меню 👇", reply_markup=student_main_kb())


# ===================== API ДЛЯ ЗАПУСКА ТЕСТА ======================

async def start_test_quiz(message: types.Message, user_id: int, meta: TestMeta, state: FSMContext) -> None:
    """Вызов из tests/entry.py и deeplink: запускает тест."""
    bot = message.bot
    chat_id = message.chat.id
    tg_user = message.from_user

    # сброс залипшей сессии (если есть)
    if (st := SESSIONS.pop(user_id, None)):
        if (t := st.get("timer_task")):
            t.cancel()
        for pid, (uid, _) in list(POLL_MAP.items()):
            if uid == user_id:
                POLL_MAP.pop(pid, None)
                FINALIZED_POLLS.add(pid)

    # загрузка вопросов
    qs = _load_questions(meta)

    # инициализация сессии
    SESSIONS[user_id] = {
        "chat_id": chat_id,
        "tg_user": tg_user,
        "meta": meta,
        "qs": qs,
        "idx": 0,
        "correct": 0,
        "last_poll_msg_id": None,
        "timer_task": None,
        "state": state,  # сохраним FSM, чтобы почистить в _finish
    }

    # помечаем состояние "идёт квиз"
    await state.set_state(TestsFlow.RUNNING)

    title_safe = h(getattr(meta, "title", str(getattr(meta, "code", ""))))
    await bot.send_message(
        chat_id,
        f"🧠 Начинаем тест: <b>{title_safe}</b>\nНа каждый вопрос — {TIME_PER_Q} сек.",
        parse_mode=ParseMode.HTML,
    )

    await _send_q(user_id, bot)


# ===================== ХЭНДЛЕРЫ TELEGRAM ======================

@router.poll_answer()
async def on_poll_answer(pa: types.PollAnswer, bot: Bot) -> None:
    pid = pa.poll_id
    bind = POLL_MAP.pop(pid, None)
    if not bind:
        return
    user_id, idx_from_map = bind

    lock = USER_LOCKS[user_id]
    async with lock:
        st = SESSIONS.get(user_id)
        if not st:
            return
        if idx_from_map != st["idx"]:
            return

        # остановить наш таймер
        if (t := st.pop("timer_task", None)):
            t.cancel()

        # дедуп по poll'у
        if pid in FINALIZED_POLLS:
            return
        FINALIZED_POLLS.add(pid)

        selected = pa.option_ids[0] if pa.option_ids else None
        is_correct = (selected == st["qs"][st["idx"]].correct_idx)
        await _finalize_step(user_id, st["idx"], is_correct, bot=bot)


@router.poll()
async def on_poll_closed(p: types.Poll, bot: Bot) -> None:
    # ядро — наш таймер; здесь только best-effort подчистка
    if not p.is_closed:
        return
    pid = p.id

    bind = POLL_MAP.pop(pid, None)
    if not bind:
        return
    user_id, idx_from_map = bind

    lock = USER_LOCKS[user_id]
    async with lock:
        st = SESSIONS.get(user_id)
        if not st:
            return
        if idx_from_map != st["idx"]:
            return

        if (t := st.pop("timer_task", None)):
            t.cancel()

        if pid in FINALIZED_POLLS:
            return
        FINALIZED_POLLS.add(pid)

        await _finalize_step(user_id, st["idx"], is_correct=False, bot=bot)


@router.callback_query(F.data == "quiz_cancel")
async def on_quiz_cancel(cb: types.CallbackQuery, bot: Bot, state: FSMContext) -> None:
    uid = cb.from_user.id
    st = SESSIONS.pop(uid, None)

    # закрыть активный poll
    if st:
        chat_id = st["chat_id"]
        if (t := st.get("timer_task")):
            t.cancel()
        msg_id = st.get("last_poll_msg_id")
        if msg_id:
            with contextlib.suppress(Exception):
                await bot.stop_poll(chat_id, msg_id)

    # подчистить карты
    for pid, (u, _) in list(POLL_MAP.items()):
        if u == uid:
            POLL_MAP.pop(pid, None)
            FINALIZED_POLLS.add(pid)

    # уведомление админам о прерывании
    try:
        tg_user = cb.from_user
        uname = f"@{tg_user.username}" if getattr(tg_user, "username", None) else "—"
        admin_msg = (
            "🧪 Тест прерван\n"
            f"Ученик: {tg_user.full_name} {uname}\n"
            f"Telegram ID: {tg_user.id}"
        )
        settings = get_settings()
        admin_ids = settings.admin_ids
        for aid in admin_ids:
            with contextlib.suppress(Exception):
                await bot.send_message(aid, admin_msg)
    except Exception:
        pass

    # сбросить FSM и вернуть меню
    with contextlib.suppress(Exception):
        await state.clear()

    await cb.message.answer("Тест прерван. Он не сдан. Возвращаю в главное меню 👇", reply_markup=student_main_kb())
    await cb.answer()


@router.message(F.text == "/cancel_quiz")
async def cancel_quiz_cmd(m: types.Message, state: FSMContext) -> None:
    uid = m.from_user.id
    st = SESSIONS.pop(uid, None)

    if st:
        chat_id = st["chat_id"]
        if (t := st.get("timer_task")):
            t.cancel()
        msg_id = st.get("last_poll_msg_id")
        if msg_id:
            with contextlib.suppress(Exception):
                await m.bot.stop_poll(chat_id, msg_id)

    for pid, (u, _) in list(POLL_MAP.items()):
        if u == uid:
            POLL_MAP.pop(pid, None)
            FINALIZED_POLLS.add(pid)

    # уведомление админам о прерывании
    try:
        tg_user = m.from_user
        uname = f"@{tg_user.username}" if getattr(tg_user, "username", None) else "—"
        admin_msg = (
            "🧪 Тест прерван\n"
            f"Ученик: {tg_user.full_name} {uname}\n"
            f"Telegram ID: {uid}"
        )
        settings = get_settings()
        admin_ids = settings.admin_ids
        for aid in admin_ids:
            with contextlib.suppress(Exception):
                await m.bot.send_message(aid, admin_msg)
    except Exception:
        pass

    with contextlib.suppress(Exception):
        await state.clear()

    await m.answer("Тест прерван. Он не сдан. Возвращаю в главное меню 👇", reply_markup=student_main_kb())