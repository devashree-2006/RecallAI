import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = DATA_DIR / "recallai.db"


@contextmanager
def get_connection():
    DATA_DIR.mkdir(exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    with get_connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS challenges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                challenge_type TEXT NOT NULL,
                difficulty INTEGER NOT NULL,
                challenge_data TEXT NOT NULL,
                started_at TEXT NOT NULL,
                submitted_at TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            );

            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                score REAL NOT NULL,
                correct_count INTEGER NOT NULL,
                total_count INTEGER NOT NULL,
                response_time REAL NOT NULL,
                result_data TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (challenge_id) REFERENCES challenges(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                challenge_type TEXT NOT NULL,
                skill_score REAL NOT NULL DEFAULT 50,
                level INTEGER NOT NULL DEFAULT 1,
                attempts INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, challenge_type),
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS journal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                entry_date TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_journal_user_date
                ON journal_entries(user_id, entry_date DESC, id DESC);

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                citations_json TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_chat_user_id
                ON chat_messages(user_id, id DESC);
        """)

        # Older RecallAI versions stored the speaker in `sender` and did not
        # have a `role` column. Upgrade that table in place so existing chat
        # history remains available after this release.
        chat_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(chat_messages)")
        }
        if "citations_json" not in chat_columns:
            db.execute("ALTER TABLE chat_messages ADD COLUMN citations_json TEXT NOT NULL DEFAULT '[]'")
            chat_columns.add("citations_json")
        if "role" not in chat_columns:
            db.execute("ALTER TABLE chat_messages ADD COLUMN role TEXT")
            chat_columns.add("role")
        if "sender" in chat_columns:
            db.execute("""
                UPDATE chat_messages
                SET role = CASE
                    WHEN LOWER(TRIM(COALESCE(sender, ''))) IN ('user', 'you', 'human')
                        THEN 'user'
                    ELSE 'assistant'
                END
                WHERE role IS NULL OR TRIM(role) = ''
            """)
        else:
            db.execute("""
                UPDATE chat_messages SET role = 'assistant'
                WHERE role IS NULL OR TRIM(role) = ''
            """)


def save_chat_turn(user_id, user_message, assistant_message, citations=None):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as db:
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(chat_messages)")
        }
        if "sender" in columns:
            # Keep the legacy NOT NULL sender field populated as well. Some
            # existing databases require it even after the role migration.
            insert_columns = ["user_id", "sender", "message", "intent", "created_at", "role"]
            if "citations_json" in columns:
                insert_columns.append("citations_json")
            placeholders = ", ".join("?" for _ in insert_columns)
            db.executemany(
                f"INSERT INTO chat_messages ({', '.join(insert_columns)}) VALUES ({placeholders})",
                [
                    (user_id, "user", user_message, None, now, "user", "[]")
                    if "citations_json" in columns else
                    (user_id, "user", user_message, None, now, "user"),
                    (user_id, "bot", assistant_message, None, now, "assistant", json.dumps(citations or []))
                    if "citations_json" in columns else
                    (user_id, "bot", assistant_message, None, now, "assistant")
                ]
            )
        else:
            insert_columns = ["user_id", "role", "message", "created_at"]
            if "citations_json" in columns:
                insert_columns.append("citations_json")
            placeholders = ", ".join("?" for _ in insert_columns)
            db.executemany(
                f"INSERT INTO chat_messages ({', '.join(insert_columns)}) VALUES ({placeholders})",
                [
                    (user_id, "user", user_message, now, "[]")
                    if "citations_json" in columns else
                    (user_id, "user", user_message, now),
                    (user_id, "assistant", assistant_message, now, json.dumps(citations or []))
                    if "citations_json" in columns else
                    (user_id, "assistant", assistant_message, now)
                ]
            )


def get_chat_history(user_id, limit=200):
    with get_connection() as db:
        rows = db.execute("""
            SELECT id, role, message, created_at, citations_json FROM (
                SELECT id, role, message, created_at, citations_json
                FROM chat_messages WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC
        """, (user_id, limit)).fetchall()
        messages = [dict(row) for row in rows]
        for item in messages:
            try:
                item["citations"] = json.loads(item.pop("citations_json", "[]") or "[]")
            except (TypeError, json.JSONDecodeError):
                item["citations"] = []
        return messages


def clear_chat_history(user_id):
    with get_connection() as db:
        db.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))


def create_journal_entry(user_id, entry_date, content):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as db:
        cursor = db.execute("""
            INSERT INTO journal_entries
            (user_id, entry_date, content, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, entry_date, content, now, now))
        row = db.execute(
            "SELECT * FROM journal_entries WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return dict(row)


def get_journal_entries(user_id, start_date=None, end_date=None, limit=100):
    clauses = ["user_id = ?"]
    params = [user_id]
    if start_date:
        clauses.append("entry_date >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("entry_date <= ?")
        params.append(end_date)
    params.append(limit)
    with get_connection() as db:
        rows = db.execute(
            f"SELECT * FROM journal_entries WHERE {' AND '.join(clauses)} "
            "ORDER BY entry_date DESC, id DESC LIMIT ?", params
        ).fetchall()
        return [dict(row) for row in rows]


def update_journal_entry(user_id, entry_id, entry_date, content):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as db:
        cursor = db.execute("""
            UPDATE journal_entries SET entry_date = ?, content = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
        """, (entry_date, content, now, entry_id, user_id))
        if not cursor.rowcount:
            return None
        row = db.execute(
            "SELECT * FROM journal_entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id)
        ).fetchone()
        return dict(row) if row else None


def delete_journal_entry(user_id, entry_id):
    with get_connection() as db:
        cursor = db.execute(
            "DELETE FROM journal_entries WHERE id = ? AND user_id = ?",
            (entry_id, user_id)
        )
        return cursor.rowcount > 0


def create_user(username):
    with get_connection() as db:
        now = datetime.now().isoformat(timespec="seconds")
        db.execute(
            "INSERT OR IGNORE INTO users (username, created_at) VALUES (?, ?)",
            (username, now)
        )
        user = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        return dict(user)


def get_user(user_id):
    with get_connection() as db:
        user = db.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        return dict(user) if user else None


def create_session(user_id):
    with get_connection() as db:
        cursor = db.execute(
            "INSERT INTO sessions (user_id, started_at) VALUES (?, ?)",
            (user_id, datetime.now().isoformat(timespec="seconds"))
        )
        return cursor.lastrowid


def create_challenge(session_id, challenge_type, difficulty, challenge_data):
    with get_connection() as db:
        cursor = db.execute("""
            INSERT INTO challenges
            (session_id, challenge_type, difficulty, challenge_data, started_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session_id,
            challenge_type,
            difficulty,
            challenge_data,
            datetime.now().isoformat(timespec="seconds")
        ))
        return cursor.lastrowid


def get_challenge(challenge_id, user_id):
    with get_connection() as db:
        row = db.execute("""
            SELECT c.*
            FROM challenges c
            JOIN sessions s ON c.session_id = s.id
            WHERE c.id = ? AND s.user_id = ?
        """, (challenge_id, user_id)).fetchone()
        return dict(row) if row else None


def save_attempt(challenge_id, user_id, score, correct_count,
                 total_count, response_time, result_data):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as db:
        db.execute("""
            INSERT INTO attempts
            (challenge_id, user_id, score, correct_count, total_count,
             response_time, result_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            challenge_id, user_id, score, correct_count,
            total_count, response_time, result_data, now
        ))
        db.execute(
            "UPDATE challenges SET submitted_at = ? WHERE id = ?",
            (now, challenge_id)
        )


def get_user_attempts(user_id):
    with get_connection() as db:
        rows = db.execute("""
            SELECT a.*, c.challenge_type, c.difficulty
            FROM attempts a
            JOIN challenges c ON c.id = a.challenge_id
            WHERE a.user_id = ?
            ORDER BY a.id DESC
        """, (user_id,)).fetchall()
        return [dict(row) for row in rows]


def get_skill(user_id, challenge_type):
    with get_connection() as db:
        row = db.execute("""
            SELECT * FROM skills
            WHERE user_id = ? AND challenge_type = ?
        """, (user_id, challenge_type)).fetchone()
        return dict(row) if row else None


def save_skill(user_id, challenge_type, skill_score, level, attempts):
    now = datetime.now().isoformat(timespec="seconds")
    with get_connection() as db:
        db.execute("""
            INSERT INTO skills
            (user_id, challenge_type, skill_score, level, attempts, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, challenge_type) DO UPDATE SET
                skill_score = excluded.skill_score,
                level = excluded.level,
                attempts = excluded.attempts,
                updated_at = excluded.updated_at
        """, (
            user_id, challenge_type, skill_score, level, attempts, now
        ))


def get_all_skills(user_id):
    with get_connection() as db:
        rows = db.execute(
            "SELECT * FROM skills WHERE user_id = ? ORDER BY challenge_type",
            (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]
