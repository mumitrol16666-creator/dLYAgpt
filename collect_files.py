# collect_files.py
import argparse
from pathlib import Path
import sys

SEP = "=" * 80 + "\n"

def is_probably_binary(path: Path, check_bytes: int = 4096) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(check_bytes)
            if b"\x00" in chunk:
                return True
            # Heuristic: high non-text byte ratio -> binary
            if not chunk:
                return False
            nontext = sum(1 for b in chunk if b < 9 or (b > 13 and b < 32))
            if (nontext / len(chunk)) > 0.30:
                return True
    except Exception:
        return True
    return False

def read_text_with_fallback(path: Path) -> str:
    # Try common encodings
    encodings = ["utf-8", "cp1251", "latin-1"]
    raw = path.read_bytes()
    for enc in encodings:
        try:
            return raw.decode(enc)
        except Exception:
            continue
    # As a last resort, decode latin-1 to avoid crash
    try:
        return raw.decode("latin-1", errors="replace")
    except Exception:
        return ""

def collect(folders, output_file, skip_binary=True, extensions=None):
    out_path = Path(output_file)
    processed = 0
    text_files = 0
    binary_skipped = 0
    errors = 0

    with out_path.open("w", encoding="utf-8") as out:
        for folder in folders:
            base = Path(folder)
            if not base.exists():
                print(f"[WARN] Папка не найдена: {base}", file=sys.stderr)
                continue
            for file in base.rglob("*"):
                if file.is_file():
                    processed += 1
                    rel = file.relative_to(Path.cwd())
                    out.write(SEP)
                    out.write(f"FILE: {rel}\n")
                    out.write(SEP)
                    try:
                        if extensions and file.suffix.lower() not in extensions:
                            out.write(f"[Пропущён: расширение {file.suffix} не в списке]\n\n")
                            continue
                        if skip_binary and is_probably_binary(file):
                            binary_skipped += 1
                            out.write(f"[Пропущён бинарный файл]\n\n")
                            continue
                        text = read_text_with_fallback(file)
                        out.write(text)
                        out.write("\n\n")
                        text_files += 1
                    except Exception as e:
                        errors += 1
                        out.write(f"[Ошибка чтения: {e}]\n\n")
    print("Готово.")
    print(f"Всего файлов просмотрено: {processed}")
    print(f"Текстовых файлов записано: {text_files}")
    print(f"Бинарных пропущено: {binary_skipped}")
    print(f"Ошибок: {errors}")
    print(f"Результат в: {out_path.resolve()}")

def find_existing_default_folders(candidates=("Bot","bot","Data","data","requirements.txt")):
    found = []
    cwd = Path.cwd()
    for name in candidates:
        p = cwd / name
        if p.exists() and p.is_dir():
            found.append(str(p))
    return found

def main():
    parser = argparse.ArgumentParser(description="Collect texts from folders into one file.")
    parser.add_argument("folders", nargs="*", help="Папки для сбора (по умолчанию: Bot и Data).")
    parser.add_argument("-o", "--output", default="all_files.txt", help="Файл вывода")
    parser.add_argument("--no-skip-binary", action="store_true", help="Не пропускать бинарные файлы (опасно)")
    parser.add_argument("--ext", nargs="*", help="Список расширений для включения, например: .py .txt .md")
    args = parser.parse_args()

    if args.folders:
        folders = args.folders
    else:
        folders = find_existing_default_folders()
        if not folders:
            # если ничего не найдено — всё равно использовать стандартные имена
            folders = ["Bot", "Data"]
            print("[INFO] Не найдены стандартные папки. Попробую Bot и Data в текущей директории.", file=sys.stderr)

    exts = None
    if args.ext:
        exts = set(e.lower() if e.startswith(".") else f".{e.lower()}" for e in args.ext)

    collect(folders=folders, output_file=args.output, skip_binary=not args.no_skip_binary, extensions=exts)

if __name__ == "__main__":
    main()
