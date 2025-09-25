# bot/services/ranks.py
from __future__ import annotations
from typing import Optional, Tuple, List

# Базовая лестница порогов (можешь позже заменить на свои 13 уровней “Путь Маэстро”)
# Важно: отсортировано по возрастанию порога.
RANKS: List[tuple[int, str]] = [
    (0,    "Новичок"),
    (200,  "Ученик I"),
    (500,  "Ученик II"),
    (1000, "Продолжающий"),
    (1500, "Уверенный"),
    (2200, "Опытный"),
    (3000, "Наставник"),
    (4500, "Маэстро"),       # по твоим правилам: 4500+
    (6000, "Архимаэстро"),   # топ: 6000+
]

def get_rank_by_points(total: int) -> tuple[str, Optional[int]]:
    """
    По сумме баллов возвращает (название_ранга, следующий_порог_или_None).
    Пример: (\"Ученик II\", 1000) — значит до следующего ранга осталось (1000 - total).
    """
    current_thr, current_name = RANKS[0]
    for thr, name in RANKS:
        if total >= thr:
            current_thr, current_name = thr, name
        else:
            break

    next_thr: Optional[int] = None
    for thr, _ in RANKS:
        if thr > current_thr:
            next_thr = thr
            break

    return current_name, next_thr
