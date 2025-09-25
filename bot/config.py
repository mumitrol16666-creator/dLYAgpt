# bot/config.py (финальная, исправленная версия)
import os
import datetime
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()
__all__ = [
    "Settings", "get_settings", "Course", "get_course", "COURSES",
    "tzinfo", "now_utc_str", "local_dt_str", "format_deadline_text"
]

# <<< Класс для описания курса >>>
@dataclass
class Course:
    code: str
    title: str
    price: int
    free_lessons: int

# <<< "Каталог курсов" >>>
COURSES = {
    "course_general": Course(
        code="course_general",
        title="Общая программа",
        price=4999,
        free_lessons=3
    ),
    "course_five_songs": Course(
        code="course_five_songs",
        title="Простые аккорды и 5 песен",
        price=1999,
        free_lessons=1
    ),
}

def get_course(code: str) -> Course | None:
    """Возвращает информацию о курсе по его коду."""
    return COURSES.get(code)

def _clean(s: str | None) -> str:
    return (s or "").strip().strip('"').strip("'")

def _parse_admins() -> tuple[int, ...]:
    ids: set[int] = set()
    one = _clean(os.getenv("ADMIN_ID"))
    many = _clean(os.getenv("ADMIN_IDS"))
    if one.isdigit():
        ids.add(int(one))
    if many:
        for part in many.split(","):
            p = _clean(part)
            if p.isdigit():
                ids.add(int(p))
    return tuple(sorted(ids))

# bot/config.py

# ... (в начале файла у тебя уже есть @dataclass, Course, COURSES и т.д.) ...

@dataclass
class Settings:
    bot_token: str
    admin_ids: tuple[int, ...]
    db_path: str
    lessons_path: Path
    assets_path: Path
    timezone: str
    payment_link: str
    # <<< НОВОЕ: Добавляем пути к конкретным категориям уроков >>>
    course_general_path: Path
    by_code_path: Path

def get_settings() -> Settings:
    token = _clean(os.getenv("BOT_TOKEN"))
    if not token:
        raise RuntimeError("BOT_TOKEN is required in .env")
    db_path = _clean(os.getenv("DB_PATH") or "./data/bot.db")
    lessons = Path(_clean(os.getenv("LESSONS_PATH") or "./LESSONS_root")).resolve()
    assets = Path(_clean(os.getenv("ASSETS_PATH") or "./assets")).resolve()
    tz = _clean(os.getenv("TIMEZONE") or "Asia/Aqtobe")
    link = _clean(os.getenv("PAYMENT_LINK") or "")
    admin_ids = _parse_admins()

    # <<< НОВОЕ: Определяем пути к подпапкам с уроками >>>
    course_general = lessons / "course_general"
    by_code = lessons / "by_code"

    if not lessons.exists():
        print(f"[WARN] LESSONS_PATH={lessons} does not exist. Using demo './LESSONS_root'.")
        lessons = Path("./LESSONS_root").resolve()

    return Settings(
        bot_token=token,
        admin_ids=admin_ids,
        db_path=db_path,
        lessons_path=lessons,
        assets_path=assets,
        timezone=tz,
        payment_link=link,
        # <<< НОВОЕ: Передаем созданные пути в настройки >>>
        course_general_path=course_general,
        by_code_path=by_code,
    )


def tzinfo() -> ZoneInfo:
    return ZoneInfo(get_settings().timezone)

def now_utc_str() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def local_dt_str(utc_iso: str, tz: str) -> str:
    """Format UTC ISO to local time string"""
    try:
        dt = datetime.datetime.fromisoformat(utc_iso.replace("Z", "+00:00")).astimezone(ZoneInfo(tz))
        return dt.strftime("%d %B %Y, %H:%M")
    except Exception:
        return utc_iso

def _pluralize(number, one, few, many):
    """Выбирает правильную форму слова для числа."""
    num = number % 100
    if 11 <= num <= 19:
        return many
    num = number % 10
    if num == 1:
        return one
    if 2 <= num <= 4:
        return few
    return many

def format_deadline_text(utc_iso: str | None, tz: str) -> str:
    """Форматирует дедлайн в человекочитаемый вид."""
    if not utc_iso:
        return "бессрочно"
    try:
        now = datetime.datetime.now(datetime.timezone.utc)
        deadline_dt = datetime.datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        local_deadline = deadline_dt.astimezone(ZoneInfo(tz))
        date_str = local_deadline.strftime("%d %B")
        time_left = deadline_dt - now

        if time_left.total_seconds() <= 0:
            return f"до {date_str} (дедлайн прошел)"

        days = time_left.days
        if days > 0:
            days_str = _pluralize(days, "день", "дня", "дней")
            return f"до {date_str} (осталось {days} {days_str})"

        hours = int(time_left.total_seconds() / 3600)
        if hours > 0:
            hours_str = _pluralize(hours, "час", "часа", "часов")
            return f"до {date_str} (осталось {hours} {hours_str})"

        return f"до {date_str} (осталось меньше часа)"
    except Exception:
        return utc_iso