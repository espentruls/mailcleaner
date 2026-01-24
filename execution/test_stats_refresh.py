import unittest
import os
import json
import sqlite3
from pathlib import Path
from models import Database, Email, EmailCategory
from datetime import datetime

class TestStatsRefresh(unittest.TestCase):
    db_path = "test_stats_refresh.db"

    def setUp(self):
        # Use a fresh DB for each test
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_refresh_all_stats_populates_sender_stats(self):
        """Test that refresh_all_stats correctly populates the sender_stats table."""
        # 1. Create a dummy email
        email = Email(
            id="test_id_1",
            thread_id="thread_1",
            sender="Test Sender",
            sender_email="test@example.com",
            subject="Test Subject",
            snippet="Test Snippet",
            body_preview="Test Body",
            date=datetime.now(),
            is_read=False,
            labels=[],
            category=EmailCategory.PERSONAL
        )

        self.db.save_email(email)

        # 2. Verify sender_stats is empty initially (direct SQL check)
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM sender_stats").fetchone()[0]
            self.assertEqual(count, 0, "sender_stats should be empty initially")

        # 3. Trigger refresh
        self.db.refresh_all_stats()

        # 4. Verify sender_stats is populated
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM sender_stats").fetchall()
            self.assertEqual(len(rows), 1, "sender_stats should have 1 row")
            row = rows[0]
            # row is a tuple, index 0 is email
            self.assertEqual(row[0], "test@example.com")
            # index 2 is total_emails
            self.assertEqual(row[2], 1)

    def test_refresh_all_stats_populates_dashboard_cache(self):
        """Test that refresh_all_stats correctly updates the dashboard cache setting."""
        # 1. Create a dummy email
        email = Email(
            id="test_id_2",
            thread_id="thread_2",
            sender="Test Sender 2",
            sender_email="test2@example.com",
            subject="Test Subject 2",
            snippet="Test Snippet 2",
            body_preview="Test Body 2",
            date=datetime.now(),
            is_read=True,
            labels=[],
            category=EmailCategory.PERSONAL
        )
        self.db.save_email(email)

        # 2. Trigger refresh
        self.db.refresh_all_stats()

        # 3. Verify dashboard cache
        cached_data = self.db.get_setting('dashboard_cache')
        self.assertIsNotNone(cached_data)

        data = json.loads(cached_data)
        self.assertEqual(data.get('total_emails'), 1)
        self.assertEqual(data.get('total_senders'), 1)

if __name__ == "__main__":
    unittest.main()
