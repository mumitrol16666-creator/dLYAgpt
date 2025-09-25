# -*- coding: utf-8 -*-
"""
Maestro Bot migration script (SQLite).
Creates tables / adds missing columns / adds indexes idempotently.
Generated: 2025-08-23T15:31:29.721080Z

Usage:
  DB_PATH=./data/bot.db python migrate_maestro_schema.py
"""
import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "./data/bot.db")

def execute(cur, sql):
    cur.execute(sql)

def table_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None

def index_exists(cur, name: str) -> bool:
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=? ", (name,))
    return cur.fetchone() is not None

def columns(cur, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}

def add_column(cur, table: str, ddl: str):
    print(f"[migrate] {table}: add column {ddl}")
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

def migrate_students(cur):
    if not table_exists(cur, "students"):
        execute(cur, """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tg_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            full_name TEXT,
            phone TEXT,
            age INTEGER,
            birth_date TEXT,
            has_guitar INTEGER DEFAULT 0,
            experience_months INTEGER DEFAULT 0,
            goal TEXT,
            approved INTEGER DEFAULT 0,
            waiting_lessons INTEGER DEFAULT 0,
            last_known_max_lesson INTEGER DEFAULT 0,
            rank TEXT,
            rank_points INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT,
            last_seen TEXT
        );
        """)
    cols = columns(cur, "students")
    need = {
        "approved": "INTEGER DEFAULT 0",
        "waiting_lessons": "INTEGER DEFAULT 0",
        "last_known_max_lesson": "INTEGER DEFAULT 0",
        "rank": "TEXT",
        "rank_points": "INTEGER DEFAULT 0",
        "updated_at": "TEXT",
        "last_seen": "TEXT",
    }
    for col, ddl in need.items():
        if col not in cols:
            add_column(cur, "students", f"{col} {ddl}")
    for idx_name, idx_sql in [
        ("idx_students_tg_id", "CREATE UNIQUE INDEX idx_students_tg_id ON students(tg_id)"),
    ]:
        if not index_exists(cur, idx_name):
            execute(cur, idx_sql)

def migrate_progress(cur):
    if not table_exists(cur, "progress"):
        execute(cur, """
        CREATE TABLE progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            lesson_id INTEGER,
            lesson_code TEXT,
            task_code TEXT,
            status TEXT NOT NULL,
            sent_at TEXT,
            returned_at TEXT,
            submitted_at TEXT,
            approved_at TEXT,
            deadline_at TEXT,
            remind_at TEXT,
            reminded INTEGER DEFAULT 0,
            updated_at TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """)
    else:
        cols = columns(cur, "progress")
        if "lesson_id" not in cols: add_column(cur, "progress", "lesson_id INTEGER")
        if "lesson_code" not in cols: add_column(cur, "progress", "lesson_code TEXT")
        if "task_code" not in cols: add_column(cur, "progress", "task_code TEXT")
        if "returned_at" not in cols: add_column(cur, "progress", "returned_at TEXT")
        if "submitted_at" not in cols: add_column(cur, "progress", "submitted_at TEXT")
        if "approved_at" not in cols: add_column(cur, "progress", "approved_at TEXT")
        if "deadline_at" not in cols: add_column(cur, "progress", "deadline_at TEXT")
        if "remind_at" not in cols: add_column(cur, "progress", "remind_at TEXT")
        if "reminded" not in cols: add_column(cur, "progress", "reminded INTEGER DEFAULT 0")
        if "updated_at" not in cols: add_column(cur, "progress", "updated_at TEXT")
    for idx_name, idx_sql in [
        ("idx_progress_student", "CREATE INDEX idx_progress_student ON progress(student_id)"),
        ("idx_progress_status", "CREATE INDEX idx_progress_status ON progress(status)"),
        ("idx_progress_status_remind", "CREATE INDEX idx_progress_status_remind ON progress(status, remind_at)"),
    ]:
        if not index_exists(cur, idx_name):
            execute(cur, idx_sql)


def migrate_payments(cur):
    if not table_exists(cur, "payments"):
        execute(cur, """
        CREATE TABLE payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            method TEXT,
            note TEXT,
            paid_at TEXT,
            created_at TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """)
    else:
        cols = columns(cur, "payments")
        if "method" not in cols: add_column(cur, "payments", "method TEXT")
        if "note" not in cols: add_column(cur, "payments", "note TEXT")
        if "created_at" not in cols: add_column(cur, "payments", "created_at TEXT")
    for idx_name, idx_sql in [
        ("idx_payments_paid_at", "CREATE INDEX idx_payments_paid_at ON payments(paid_at)"),
        ("idx_payments_student", "CREATE INDEX idx_payments_student ON payments(student_id)"),
    ]:
        if not index_exists(cur, idx_name):
            execute(cur, idx_sql)

def migrate_payment_requests(cur):
    if not table_exists(cur, "payment_requests"):
        execute(cur, """
        CREATE TABLE payment_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT,
            resolved_at TEXT,
            FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """)
    for idx_name, idx_sql in [
        ("idx_payreq_status", "CREATE INDEX idx_payreq_status ON payment_requests(status)"),
        ("idx_payreq_student", "CREATE INDEX idx_payreq_student ON payment_requests(student_id)"),
    ]:
        if not index_exists(cur, idx_name):
            execute(cur, idx_sql)

def migrate_help_requests(cur):
    if not table_exists(cur, "help_requests"):
        execute(cur, """
        CREATE TABLE help_requests(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          student_id INTEGER NOT NULL,
          status TEXT NOT NULL,
          created_at TEXT NOT NULL,
          answered_at TEXT,
          FOREIGN KEY(student_id) REFERENCES students(id) ON DELETE CASCADE
        );
        """)
    for idx_name, idx_sql in [
        ("idx_help_requests_student", "CREATE INDEX idx_help_requests_student ON help_requests(student_id)"),
        ("idx_help_requests_status", "CREATE INDEX idx_help_requests_status  ON help_requests(status)"),
    ]:
        if not index_exists(cur, idx_name):
            execute(cur, idx_sql)

def migrate_test_results(cur):
    if not table_exists(cur, "test_results"):
        print("[migrate] create table test_results")
        execute(cur, """
        CREATE TABLE test_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            test_code TEXT NOT NULL,
            correct_count INTEGER NOT NULL,
            total_count INTEGER NOT NULL,
            passed INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, test_code)
        );
        """)
    else:
        need = {
            "user_id": "INTEGER",
            "test_code": "TEXT",
            "correct_count": "INTEGER",
            "total_count": "INTEGER",
            "passed": "INTEGER",
            "created_at": "TEXT",
        }
        cols = columns(cur, "test_results")
        for col, ddl in need.items():
            if col not in cols:
                add_column(cur, "test_results", f"{col} {ddl}")
    for idx_name, idx_sql in [
        ("idx_test_results_user", "CREATE INDEX idx_test_results_user ON test_results(user_id)"),
        ("idx_test_results_user_code_time", "CREATE INDEX idx_test_results_user_code_time ON test_results(user_id, test_code, created_at)"),
    ]:
        if not index_exists(cur, idx_name):
            execute(cur, idx_sql)

def migrate():
    Path(os.path.dirname(DB_PATH) or ".").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        execute(cur, "PRAGMA foreign_keys = ON;")
        migrate_students(cur)
        migrate_progress(cur)
        migrate_payments(cur)
        migrate_payment_requests(cur)
        migrate_help_requests(cur)
        migrate_test_results(cur) # <-- ДОБАВЛЕНО
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()