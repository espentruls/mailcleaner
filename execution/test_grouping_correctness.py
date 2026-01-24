import unittest
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add execution dir to path
sys.path.insert(0, str(Path(__file__).parent))

from models import Database, Email, EmailCategory

class TestGroupingCorrectness(unittest.TestCase):
    db_path = "test_grouping.db"

    def setUp(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.db = Database(db_path=self.db_path)

        # Create test data
        # Sender A: 10 emails (5 read, 5 unread)
        # Sender B: 5 emails (5 read)
        # Sender C: 2 emails (2 unread)

        emails = []
        base_date = datetime.now()

        # Sender A
        for i in range(10):
            emails.append(Email(
                id=f"a_{i}", thread_id="t", sender="Sender A", sender_email="a@example.com",
                subject=f"Sub A {i}", snippet="s", body_preview="b",
                date=base_date - timedelta(minutes=i),
                is_read=(i < 5), # 0-4 read (newer), 5-9 unread (older)
                labels=[], category=EmailCategory.PERSONAL,
                unsubscribe_link=None, unsubscribe_email=None, user_action=None
            ))

        # Sender B
        for i in range(5):
            emails.append(Email(
                id=f"b_{i}", thread_id="t", sender="Sender B", sender_email="b@example.com",
                subject=f"Sub B {i}", snippet="s", body_preview="b",
                date=base_date - timedelta(hours=1, minutes=i),
                is_read=True,
                labels=[], category=EmailCategory.NEWSLETTER,
                unsubscribe_link=None, unsubscribe_email=None, user_action=None
            ))

        # Sender C
        for i in range(2):
            emails.append(Email(
                id=f"c_{i}", thread_id="t", sender="Sender C", sender_email="c@example.com",
                subject=f"Sub C {i}", snippet="s", body_preview="b",
                date=base_date - timedelta(hours=2, minutes=i),
                is_read=False,
                labels=[], category=EmailCategory.SPAM,
                unsubscribe_link=None, unsubscribe_email=None, user_action=None
            ))

        self.db.save_emails_batch(emails)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_grouping_all(self):
        groups = self.db.get_rich_sender_groups(read_filter='all', limit=10)
        self.assertEqual(len(groups), 3)

        # Sort order should be by total count DESC: A(10), B(5), C(2)
        self.assertEqual(groups[0]['sender_email'], 'a@example.com')
        self.assertEqual(groups[0]['total'], 10)
        self.assertEqual(groups[0]['unread'], 5)

        self.assertEqual(groups[1]['sender_email'], 'b@example.com')
        self.assertEqual(groups[1]['total'], 5)
        self.assertEqual(groups[1]['unread'], 0)

        self.assertEqual(groups[2]['sender_email'], 'c@example.com')
        self.assertEqual(groups[2]['total'], 2)
        self.assertEqual(groups[2]['unread'], 2)

        # Check previews
        # Sender A should have 5 previews (limit is 5)
        self.assertEqual(len(groups[0]['preview_emails']), 5)
        # Sender C should have 2
        self.assertEqual(len(groups[2]['preview_emails']), 2)

        # Check categories
        self.assertEqual(groups[0]['categories']['personal'], 10)

    def test_grouping_unread(self):
        groups = self.db.get_rich_sender_groups(read_filter='unread', limit=10)
        # Should only return groups with unread emails?
        # A (5 unread), C (2 unread). B (0 unread) should be excluded.

        self.assertEqual(len(groups), 2)

        stats = {g['sender_email']: g for g in groups}
        self.assertIn('a@example.com', stats)
        self.assertIn('c@example.com', stats)
        self.assertNotIn('b@example.com', stats)

        self.assertEqual(stats['a@example.com']['total'], 5)
        self.assertEqual(stats['a@example.com']['unread'], 5)

    def test_grouping_read(self):
        groups = self.db.get_rich_sender_groups(read_filter='read', limit=10)
        # A (5 read), B (5 read), C (0 read)
        self.assertEqual(len(groups), 2)

        stats = {g['sender_email']: g for g in groups}
        self.assertEqual(stats['a@example.com']['total'], 5)
        self.assertEqual(stats['b@example.com']['total'], 5)

if __name__ == "__main__":
    unittest.main()
