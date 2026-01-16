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
from typing import Optional, List, Dict
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
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
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
                CREATE INDEX IF NOT EXISTS idx_emails_action ON emails(user_action);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def save_email(self, email: Email):
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
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
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
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
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
            if row:
                return self._row_to_email(row)
        return None

    def get_emails_by_category(self, category: EmailCategory, limit: int = 50, offset: int = 0) -> List[Email]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM emails WHERE category = ? AND (user_action IS NULL OR user_action != 'delete') ORDER BY date DESC LIMIT ? OFFSET ?",
                (category.value, limit, offset)
            ).fetchall()
            return [self._row_to_email(row) for row in rows]

    def get_emails_by_sender(self, sender_email: str, limit: int = 50, offset: int = 0) -> List[Email]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM emails WHERE sender_email = ? AND (user_action IS NULL OR user_action != 'delete') ORDER BY date DESC LIMIT ? OFFSET ?",
                (sender_email, limit, offset)
            ).fetchall()
            return [self._row_to_email(row) for row in rows]

    def get_recent_emails_for_senders(self, sender_emails: List[str], limit_per_sender: int = 5) -> Dict[str, List[Email]]:
        if not sender_emails:
            return {}

        placeholders = ','.join('?' * len(sender_emails))
        query = f"""
            SELECT * FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY sender_email ORDER BY date DESC) as rn
                FROM emails
                WHERE sender_email IN ({placeholders})
                  AND (user_action IS NULL OR user_action != 'delete')
            ) WHERE rn <= ?
        """

        args = sender_emails + [limit_per_sender]

        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, args).fetchall()

            result = {email: [] for email in sender_emails}
            for row in rows:
                email = self._row_to_email(row)
                if email.sender_email in result:
                    result[email.sender_email].append(email)

            return result

    def get_email_ids_by_sender(self, sender_email: str) -> List[str]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id FROM emails WHERE sender_email = ? AND (user_action IS NULL OR user_action != 'delete')",
                (sender_email,)
            ).fetchall()
            return [row['id'] for row in rows]

    def get_email_ids_by_category(self, category: EmailCategory) -> List[str]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id FROM emails WHERE category = ? AND (user_action IS NULL OR user_action != 'delete')",
                (category.value,)
            ).fetchall()
            return [row['id'] for row in rows]

    def get_all_emails(self, read_filter: str = "all", limit: int = 50, offset: int = 0) -> List[Email]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            if read_filter == "read":
                query = "SELECT * FROM emails WHERE is_read = 1 AND (user_action IS NULL OR user_action != 'delete') ORDER BY date DESC LIMIT ? OFFSET ?"
            elif read_filter == "unread":
                query = "SELECT * FROM emails WHERE is_read = 0 AND (user_action IS NULL OR user_action != 'delete') ORDER BY date DESC LIMIT ? OFFSET ?"
            else:
                query = "SELECT * FROM emails WHERE (user_action IS NULL OR user_action != 'delete') ORDER BY date DESC LIMIT ? OFFSET ?"
            rows = conn.execute(query, (limit, offset)).fetchall()
            return [self._row_to_email(row) for row in rows]

    def get_top_sender_groups(self, limit: int = 50) -> List[dict]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(f"""
                SELECT 
                    sender_email,
                    sender,
                    COUNT(*) as total,
                    SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread,
                    MAX(CASE WHEN unsubscribe_link IS NOT NULL OR unsubscribe_email IS NOT NULL THEN 1 ELSE 0 END) as has_unsubscribe,
                    MAX(date) as last_received
                FROM emails
                WHERE (user_action IS NULL OR user_action != 'delete')
                GROUP BY sender_email
                ORDER BY total DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]

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
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
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
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM ml_training_data").fetchall()
            return [dict(row) for row in rows]

    def refresh_sender_stats(self):
        """Rebuild sender_stats table from emails table."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            # 1. Clear existing stats
            conn.execute("DELETE FROM sender_stats")
            
            # 2. Insert aggregated data
            conn.execute("""
                INSERT INTO sender_stats (email, name, total_emails, unread_count, last_received, has_unsubscribe, updated_at)
                SELECT 
                    sender_email,
                    MAX(sender),
                    COUNT(*),
                    SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END),
                    MAX(date),
                    MAX(CASE WHEN unsubscribe_link IS NOT NULL OR unsubscribe_email IS NOT NULL THEN 1 ELSE 0 END),
                    CURRENT_TIMESTAMP
                FROM emails
                WHERE (user_action IS NULL OR user_action != 'delete')
                GROUP BY sender_email
            """)

    def get_total_senders_count(self) -> int:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            # Efficiently count rows in the stats table
            row = conn.execute("SELECT COUNT(*) FROM sender_stats").fetchone()
            return row[0] if row else 0



    def get_sender_stats(self, limit: int = None, offset: int = 0) -> List[SenderStats]:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT * FROM sender_stats
                ORDER BY total_emails DESC
            """
            params = []
            if limit is not None:
                query += " LIMIT ? OFFSET ?"
                params = [limit, offset]
            
            rows = conn.execute(query, params).fetchall()
            rows = conn.execute(query, params).fetchall()
            return [
                SenderStats(
                    email=row['email'],
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
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("""
                INSERT INTO unsubscribe_log
                (email_id, sender_email, method, target, success, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (email_id, sender_email, method, target, 1 if success else 0, error_message))

    def mark_emails_deleted(self, email_ids: List[str]):
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            placeholders = ','.join('?' * len(email_ids))
            conn.execute(f"""
                UPDATE emails SET user_action = 'delete' WHERE id IN ({placeholders})
            """, email_ids)

    def get_category_stats(self) -> dict:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            rows = conn.execute("""
                SELECT category, COUNT(*) as count,
                       SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread
                FROM emails
                WHERE category IS NOT NULL AND (user_action IS NULL OR user_action != 'delete')
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

    def refresh_global_stats(self):
        """Calculate and cache all global dashboard stats."""
        stats = self.get_category_stats()
        sender_stats = self.get_sender_stats(limit=10)
        leaderboard = self.get_leaderboard_stats()
        
        total_emails = sum(s['count'] for s in stats.values())
        total_unread = sum(s['unread'] for s in stats.values())
        total_senders = self.get_total_senders_count()

        # Calculate deletable (non-important, non-uncertain)
        deletable = sum(
            s['count'] for cat, s in stats.items()
            if cat not in ['important', 'uncertain', 'personal']
        )
        
        # Calculate Mood
        mood = {'text': 'Balanced', 'emoji': '😐', 'color': '#CBD5E0', 'desc': 'Your inbox is well mixed.'}
        if total_emails > 0:
            imp = stats.get('important', {}).get('count', 0)
            promos = stats.get('promotions', {}).get('count', 0)
            ads = stats.get('ads', {}).get('count', 0)
            spam = stats.get('spam', {}).get('count', 0)
            junk = promos + ads + spam
            social = stats.get('social', {}).get('count', 0)
            news = stats.get('newsletter', {}).get('count', 0)
            personal = stats.get('personal', {}).get('count', 0)
            
            if total_emails < 20:
                mood = {'text': 'Zen', 'emoji': '🧘', 'color': '#63B3ED', 'desc': 'Inbox Zero is near.'}
            elif imp / total_emails > 0.3:
                mood = {'text': 'On Fire', 'emoji': '🔥', 'color': '#F56565', 'desc': 'Lots of important work!'}
            elif junk / total_emails > 0.5:
                mood = {'text': 'Shopaholic', 'emoji': '🛍️', 'color': '#ED8936', 'desc': 'Too many deals & spam.'}
            elif social / total_emails > 0.4:
                mood = {'text': 'Socialite', 'emoji': '💬', 'color': '#4299E1', 'desc': 'Very popular on socials.'}
            elif news / total_emails > 0.4:
                mood = {'text': 'News Junkie', 'emoji': '📰', 'color': '#48BB78', 'desc': 'Knowledge is power.'}
            elif personal / total_emails > 0.3:
                mood = {'text': 'Loved', 'emoji': '💌', 'color': '#ED64A6', 'desc': 'Lots of personal mail.'}
            else:
                mood = {'text': 'Chill', 'emoji': '🧊', 'color': '#A0CED9', 'desc': 'Nothing too crazy.'}

        # Structure final payload
        dashboard_data = {
            'total_emails': total_emails,
            'total_unread': total_unread,
            'total_senders': total_senders,
            'deletable': deletable,
            'would_keep': total_emails - deletable,
            'categories': stats,
            'leaderboard': leaderboard,
            'mood': mood,
            'top_senders': [
                {
                    'email': s.email,
                    'name': s.name,
                    'count': s.total_emails,
                    'unread': s.unread_count
                }
                for s in sender_stats
            ]
        }
        
        # Save to settings
        self.set_setting('dashboard_cache', json.dumps(dashboard_data))
        return dashboard_data

    def refresh_all_stats(self):
        """Rebuild all caches."""
        self.refresh_sender_stats()
        self.refresh_global_stats()


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
    
    def get_leaderboard_stats(self):
        """Get stats for leaderboard."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Most Chatty
            chatty = cursor.execute("""
                SELECT sender_email, sender, COUNT(*) as count 
                FROM emails 
                WHERE (user_action IS NULL OR user_action != 'delete')
                GROUP BY sender_email 
                ORDER BY count DESC 
                LIMIT 5
            """).fetchall()
            
            # Most Ignored (Unread & High Volume)
            junk = cursor.execute("""
                SELECT sender_email, sender, COUNT(*) as count,
                       SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread
                FROM emails 
                WHERE (user_action IS NULL OR user_action != 'delete')
                GROUP BY sender_email 
                ORDER BY unread DESC, count DESC 
                LIMIT 5
            """).fetchall()
            
            return {
                'chatty': [dict(row) for row in chatty],
                'spammers': [dict(row) for row in junk]
            }

    def get_subscription_stats(self, limit: int = 20):
        """Get newsletter stats."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Find senders with > 1 emails in newsletter/promotions
            rows = cursor.execute(f"""
                SELECT 
                    sender_email, 
                    sender, 
                    COUNT(*) as count, 
                    SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread_count,
                    MAX(CASE WHEN is_read = 1 THEN date ELSE NULL END) as last_read_date,
                    MAX(date) as last_received_date,
                    MAX(id) as sample_id
                FROM emails 
                WHERE category IN ('newsletter', 'promotions') AND (user_action IS NULL OR user_action != 'delete')
                GROUP BY sender_email 
                HAVING count > 1
                ORDER BY count DESC
                LIMIT {limit}
            """).fetchall()
            
            # Get unsubscribe links from sample emails
            results = []
            for row in rows:
                r = dict(row)
                # Try to get unsubscribe link from latest email
                sample = cursor.execute("SELECT unsubscribe_link, unsubscribe_email FROM emails WHERE sender_email = ? ORDER BY date DESC LIMIT 1", (r['sender_email'],)).fetchone()
                if sample:
                    r['unsubscribe_link'] = sample['unsubscribe_link']
                    r['unsubscribe_email'] = sample['unsubscribe_email']
                results.append(r)
                
            return results

    def get_global_counts(self):
        """Get global counts for UI badges."""
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            cursor = conn.cursor()
            
            # Total Emails (Active)
            total = cursor.execute("SELECT COUNT(*) FROM emails WHERE user_action IS NULL OR user_action != 'delete'").fetchone()[0]
            
            # Uncertain
            uncertain = cursor.execute("SELECT COUNT(*) FROM emails WHERE category = 'uncertain' AND (user_action IS NULL OR user_action != 'delete')").fetchone()[0]
            
            # Subscriptions
            subscriptions = cursor.execute("SELECT COUNT(*) FROM emails WHERE (unsubscribe_link IS NOT NULL OR unsubscribe_email IS NOT NULL) AND (user_action IS NULL OR user_action != 'delete')").fetchone()[0]
            
            # Cleanup (Spam, Ads, Promotions)
            cleanup = cursor.execute("SELECT COUNT(*) FROM emails WHERE category IN ('spam', 'ads', 'promotions') AND (user_action IS NULL OR user_action != 'delete')").fetchone()[0]
            
            return {
                'total': total,
                'uncertain': uncertain,
                'subscriptions': subscriptions,
                'cleanup': cleanup
            }
