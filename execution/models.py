"""
Data models and database operations for MailCleaner.
Uses SQLite for local storage of emails, user feedback, and ML model data.
"""

import os
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List
from enum import Enum


class EmailCategory(Enum):
    SPAM = "spam"
    NEWSLETTER = "newsletter"
    ADS = "ads"
    SOCIAL = "social"
    PROMOTIONS = "promotions"
    IMPORTANT = "important"
    UNCERTAIN = "uncertain"
    PERSONAL = "personal"


@dataclass
class Email:
    id: str
    thread_id: str
    sender: str
    sender_email: str
    subject: str
    snippet: str
    body_preview: str
    date: datetime
    is_read: bool
    labels: List[str]
    category: Optional[EmailCategory] = None
    category_confidence: float = 0.0
    ai_summary: Optional[str] = None
    unsubscribe_link: Optional[str] = None
    unsubscribe_email: Optional[str] = None
    user_action: Optional[str] = None  # 'keep', 'delete', 'unsubscribe'

    def to_dict(self):
        d = asdict(self)
        d['date'] = self.date.isoformat() if self.date else None
        d['category'] = self.category.value if self.category else None
        return d


@dataclass
class SenderStats:
    email: str
    name: str
    total_emails: int
    unread_count: int
    last_opened: Optional[datetime]
    last_received: datetime
    categories: dict
    has_unsubscribe: bool


class Database:
    def __init__(self, db_path: str = None):
        if db_path is None:
            is_docker = os.environ.get('DOCKER_CONTAINER') == '1'
            if is_docker:
                # In Docker, use /app/data for persistent files
                db_path = Path('/app/data') / "mailcleaner.db"
            else:
                # Local development - use .tmp directory
                db_path = Path(__file__).parent.parent / ".tmp" / "mailcleaner.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS emails (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    sender TEXT,
                    sender_email TEXT,
                    subject TEXT,
                    snippet TEXT,
                    body_preview TEXT,
                    date TEXT,
                    is_read INTEGER,
                    labels TEXT,
                    category TEXT,
                    category_confidence REAL,
                    ai_summary TEXT,
                    unsubscribe_link TEXT,
                    unsubscribe_email TEXT,
                    user_action TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS user_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id TEXT,
                    sender_email TEXT,
                    subject TEXT,
                    original_category TEXT,
                    user_decision TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (email_id) REFERENCES emails(id)
                );

                CREATE TABLE IF NOT EXISTS sender_stats (
                    email TEXT PRIMARY KEY,
                    name TEXT,
                    total_emails INTEGER DEFAULT 0,
                    unread_count INTEGER DEFAULT 0,
                    last_opened TEXT,
                    last_received TEXT,
                    has_unsubscribe INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS ml_training_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_email TEXT,
                    subject TEXT,
                    snippet TEXT,
                    label TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS unsubscribe_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id TEXT,
                    sender_email TEXT,
                    method TEXT,
                    target TEXT,
                    success INTEGER,
                    error_message TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender_email);
                CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category);
                CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date);
                CREATE INDEX IF NOT EXISTS idx_feedback_sender ON user_feedback(sender_email);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def save_email(self, email: Email):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO emails
                (id, thread_id, sender, sender_email, subject, snippet, body_preview,
                 date, is_read, labels, category, category_confidence, ai_summary,
                 unsubscribe_link, unsubscribe_email, user_action, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                email.id, email.thread_id, email.sender, email.sender_email,
                email.subject, email.snippet, email.body_preview,
                email.date.isoformat() if email.date else None,
                1 if email.is_read else 0,
                json.dumps(email.labels),
                email.category.value if email.category else None,
                email.category_confidence,
                email.ai_summary,
                email.unsubscribe_link,
                email.unsubscribe_email,
                email.user_action,
                datetime.now().isoformat()
            ))

    def save_emails_batch(self, emails: List[Email]):
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO emails
                (id, thread_id, sender, sender_email, subject, snippet, body_preview,
                 date, is_read, labels, category, category_confidence, ai_summary,
                 unsubscribe_link, unsubscribe_email, user_action, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    e.id, e.thread_id, e.sender, e.sender_email,
                    e.subject, e.snippet, e.body_preview,
                    e.date.isoformat() if e.date else None,
                    1 if e.is_read else 0,
                    json.dumps(e.labels),
                    e.category.value if e.category else None,
                    e.category_confidence,
                    e.ai_summary,
                    e.unsubscribe_link,
                    e.unsubscribe_email,
                    e.user_action,
                    datetime.now().isoformat()
                )
                for e in emails
            ])

    def get_email(self, email_id: str) -> Optional[Email]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
            if row:
                return self._row_to_email(row)
        return None

    def get_emails_by_category(self, category: EmailCategory) -> List[Email]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM emails WHERE category = ? ORDER BY date DESC",
                (category.value,)
            ).fetchall()
            return [self._row_to_email(row) for row in rows]

    def get_emails_by_sender(self, sender_email: str) -> List[Email]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM emails WHERE sender_email = ? ORDER BY date DESC",
                (sender_email,)
            ).fetchall()
            return [self._row_to_email(row) for row in rows]

    def get_all_emails(self, read_filter: str = "all", limit: int = 1000) -> List[Email]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if read_filter == "read":
                query = "SELECT * FROM emails WHERE is_read = 1 ORDER BY date DESC LIMIT ?"
            elif read_filter == "unread":
                query = "SELECT * FROM emails WHERE is_read = 0 ORDER BY date DESC LIMIT ?"
            else:
                query = "SELECT * FROM emails ORDER BY date DESC LIMIT ?"
            rows = conn.execute(query, (limit,)).fetchall()
            return [self._row_to_email(row) for row in rows]

    def _row_to_email(self, row) -> Email:
        return Email(
            id=row['id'],
            thread_id=row['thread_id'],
            sender=row['sender'],
            sender_email=row['sender_email'],
            subject=row['subject'],
            snippet=row['snippet'],
            body_preview=row['body_preview'],
            date=datetime.fromisoformat(row['date']) if row['date'] else None,
            is_read=bool(row['is_read']),
            labels=json.loads(row['labels']) if row['labels'] else [],
            category=EmailCategory(row['category']) if row['category'] else None,
            category_confidence=row['category_confidence'] or 0.0,
            ai_summary=row['ai_summary'],
            unsubscribe_link=row['unsubscribe_link'],
            unsubscribe_email=row['unsubscribe_email'],
            user_action=row['user_action']
        )

    def save_user_feedback(self, email_id: str, sender_email: str, subject: str,
                          original_category: str, user_decision: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO user_feedback
                (email_id, sender_email, subject, original_category, user_decision)
                VALUES (?, ?, ?, ?, ?)
            """, (email_id, sender_email, subject, original_category, user_decision))

            # Also add to training data
            conn.execute("""
                INSERT INTO ml_training_data (sender_email, subject, snippet, label)
                SELECT sender_email, subject, snippet, ?
                FROM emails WHERE id = ?
            """, (user_decision, email_id))

    def get_training_data(self) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM ml_training_data").fetchall()
            return [dict(row) for row in rows]

    def update_sender_stats(self, sender_email: str, sender_name: str,
                           has_unsubscribe: bool = False):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO sender_stats (email, name, has_unsubscribe, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    name = excluded.name,
                    has_unsubscribe = excluded.has_unsubscribe,
                    updated_at = excluded.updated_at
            """, (sender_email, sender_name, 1 if has_unsubscribe else 0,
                  datetime.now().isoformat()))

    def get_sender_stats(self) -> List[SenderStats]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT
                    e.sender_email,
                    e.sender as name,
                    COUNT(*) as total_emails,
                    SUM(CASE WHEN e.is_read = 0 THEN 1 ELSE 0 END) as unread_count,
                    MAX(e.date) as last_received,
                    MAX(e.unsubscribe_link IS NOT NULL OR e.unsubscribe_email IS NOT NULL) as has_unsubscribe
                FROM emails e
                GROUP BY e.sender_email
                ORDER BY total_emails DESC
            """).fetchall()
            return [
                SenderStats(
                    email=row['sender_email'],
                    name=row['name'],
                    total_emails=row['total_emails'],
                    unread_count=row['unread_count'],
                    last_opened=None,
                    last_received=datetime.fromisoformat(row['last_received']) if row['last_received'] else None,
                    categories={},
                    has_unsubscribe=bool(row['has_unsubscribe'])
                )
                for row in rows
            ]

    def log_unsubscribe(self, email_id: str, sender_email: str, method: str,
                       target: str, success: bool, error_message: str = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO unsubscribe_log
                (email_id, sender_email, method, target, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (email_id, sender_email, method, target, 1 if success else 0, error_message))

    def mark_emails_deleted(self, email_ids: List[str]):
        with sqlite3.connect(self.db_path) as conn:
            placeholders = ','.join('?' * len(email_ids))
            conn.execute(f"""
                UPDATE emails SET user_action = 'delete' WHERE id IN ({placeholders})
            """, email_ids)

    def get_category_stats(self) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("""
                SELECT category, COUNT(*) as count,
                       SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread
                FROM emails
                WHERE category IS NOT NULL
                GROUP BY category
            """).fetchall()
            return {row[0]: {"count": row[1], "unread": row[2]} for row in rows}

    def clear_all(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                DELETE FROM emails;
                DELETE FROM user_feedback;
                DELETE FROM sender_stats;
                DELETE FROM unsubscribe_log;
                DELETE FROM settings;
            """)

    def get_setting(self, key: str, default: str = None) -> Optional[str]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.now().isoformat()))
