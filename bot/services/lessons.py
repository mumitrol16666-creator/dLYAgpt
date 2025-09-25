from __future__ import annotations
from pathlib import Path
from typing import List, Tuple
import re

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
TEXT_EXT  = {".txt", ".md"}

L_PATTERN = re.compile(r"^L(\d{2,})$")
T_PATTERN = re.compile(r"^T(\d{2,})$")

def list_l_lessons(lessons_root: Path) -> List[str]:
    if not lessons_root.exists():
        return []
    items = []
    for p in lessons_root.iterdir():
        if p.is_dir() and L_PATTERN.match(p.name):
            items.append(p.name)
    # sort by numeric value
    def key_fn(name: str) -> int:
        m = L_PATTERN.match(name)
        return int(m.group(1)) if m else 0
    return sorted(items, key=key_fn)

def next_l_after(lessons_root: Path, last_num: int) -> str | None:
    for name in list_l_lessons(lessons_root):
        m = L_PATTERN.match(name)
        if not m:
            continue
        n = int(m.group(1))
        if n > last_num:
            return name
    return None

def list_t_blocks(lesson_dir: Path) -> List[str]:
    if not lesson_dir.exists():
        return []
    items = []
    for p in lesson_dir.iterdir():
        if p.is_dir() and T_PATTERN.match(p.name):
            items.append(p.name)
    def key_fn(name: str) -> int:
        m = T_PATTERN.match(name)
        return int(m.group(1)) if m else 0
    return sorted(items, key=key_fn)

def sort_materials(t_dir: Path) -> List[Path]:
    files = [p for p in t_dir.iterdir() if p.is_file()]

    # карта приоритетов по расширению
    prio_map: dict[str, int] = {}
    prio_map.update({ext: 0 for ext in VIDEO_EXT})
    prio_map.update({ext: 1 for ext in IMAGE_EXT})
    prio_map.update({ext: 2 for ext in TEXT_EXT})

    # ключ сортировки: (приоритет, имя файла)
    return sorted(
        files,
        key=lambda p: (prio_map.get(p.suffix.lower(), 3), p.name.lower())
    )


def parse_l_num(code: str) -> int | None:
    m = L_PATTERN.match(code)
    return int(m.group(1)) if m else None
