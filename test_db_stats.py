
import unittest
import os
import sqlite3
from unittest.mock import patch
from execution.models import Database, Email, EmailCategory
from datetime import datetime, timedelta

class TestDatabaseOptimizations(unittest.TestCase):
    db_path = "test_optimizations.db"

    def setUp(self):
        """Set up a fresh test database for each test."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

        self.db = Database(db_path=self.db_path)

        emails = []
        # Sender 1: Newsletter - 5 emails, latest is 0 days ago
        for i in range(5):
            emails.append(Email(
                id=f"newsletter_{i}", thread_id="t1", sender="Newsletter Monthly", sender_email="news@example.com",
                subject=f"Update #{i}", snippet="...", body_preview="...", date=datetime.now() - timedelta(days=i),
                is_read= i % 2 != 0, # unread are 0, 2, 4 days ago. read are 1, 3 days ago.
                labels=[], category=EmailCategory.NEWSLETTER,
                unsubscribe_link=f"http://news.com/unsub/{i}", unsubscribe_email=None
            ))

        # Sender 2: Promotions - 3 emails, latest is 0 days ago
        for i in range(3):
            emails.append(Email(
                id=f"promo_{i}", thread_id="t2", sender="Big Sales", sender_email="promo@example.com",
                subject=f"Sale #{i}", snippet="...", body_preview="...", date=datetime.now() - timedelta(days=i),
                is_read=True, labels=[], category=EmailCategory.PROMOTIONS,
                unsubscribe_link=None, unsubscribe_email=f"unsub_{i}@promo.com"
            ))

        # Sender 3: Not a subscription category - 2 emails
        for i in range(2):
            emails.append(Email(
                id=f"personal_{i}", thread_id="t3", sender="John Doe", sender_email="john@example.com",
                subject=f"Hi #{i}", snippet="...", body_preview="...", date=datetime.now() - timedelta(days=i),
                is_read=True, labels=[], category=EmailCategory.PERSONAL,
                unsubscribe_link=None, unsubscribe_email=None
            ))

        self.db.save_emails_batch(emails)

    def tearDown(self):
        """Clean up the test database file."""
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_get_subscription_stats_efficiency(self):
        """
        Tests that get_subscription_stats is optimized to use a single database connection/query.
        The original implementation used N+1 queries.
        """
        real_connect = sqlite3.connect
        call_count = 0
        def connect_counter(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return real_connect(*args, **kwargs)

        with patch('sqlite3.connect', side_effect=connect_counter):
            stats = self.db.get_subscription_stats()

        # The optimized version should only need one connection.
        # Unoptimized: 1 (for senders) + 2 (for each of 2 subscription senders) = 3
        self.assertEqual(call_count, 1, f"Expected 1 DB connection, but found {call_count}. This indicates an N+1 query problem.")

    def test_get_subscription_stats_correctness(self):
        """
        Tests that get_subscription_stats returns the correct data, including the unsubscribe
        link from the MOST RECENT email.
        """
        stats = self.db.get_subscription_stats()

        self.assertEqual(len(stats), 2, "Should find 2 senders in subscription categories ('newsletter', 'promotions')")

        # Make it a dict for easier lookup
        stats_by_sender = {s['sender_email']: s for s in stats}

        promo_stats = stats_by_sender['promo@example.com']
        self.assertEqual(promo_stats['count'], 3)
        self.assertEqual(promo_stats['unread_count'], 0) # All are read
        self.assertIsNone(promo_stats['unsubscribe_link'])
        self.assertIsNotNone(promo_stats['unsubscribe_email'])
        # The latest promo email is promo_0, so the unsub email should be unsub_0@promo.com
        self.assertEqual(promo_stats['unsubscribe_email'], 'unsub_0@promo.com')

        news_stats = stats_by_sender['news@example.com']
        self.assertEqual(news_stats['count'], 5)
        self.assertEqual(news_stats['unread_count'], 3) # is_read is False for i=0, 2, 4
        self.assertIsNone(news_stats['unsubscribe_email'])
        self.assertIsNotNone(news_stats['unsubscribe_link'])
        # The latest newsletter email is newsletter_0, so link should be .../unsub/0
        self.assertEqual(news_stats['unsubscribe_link'], "http://news.com/unsub/0")

if __name__ == "__main__":
    unittest.main(verbosity=2)
