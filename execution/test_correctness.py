
import unittest
import os
from models import Database, Email, EmailCategory
from datetime import datetime, timedelta

class TestDatabaseCorrectness(unittest.TestCase):
    db_path = "test_correctness.db"

    @classmethod
    def setUpClass(cls):
        """Set up a test database and populate it with data for all tests."""
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

        cls.db = Database(db_path=cls.db_path)

        emails = []
        # For subscription stats
        emails.extend([
            Email(id=f"news_{i}", thread_id="t1", sender="Newsletter", sender_email="news@example.com", subject=f"S{i}", snippet="s", body_preview="b", date=datetime.now() - timedelta(days=i), is_read=False, labels=[], category=EmailCategory.NEWSLETTER, unsubscribe_link=f"link_{i}", unsubscribe_email=None) for i in range(2)
        ])
        emails.extend([
            Email(id=f"promo_{i}", thread_id="t2", sender="Promotions", sender_email="promo@example.com", subject=f"S{i}", snippet="s", body_preview="b", date=datetime.now() - timedelta(days=i), is_read=True, labels=[], category=EmailCategory.PROMOTIONS, unsubscribe_link=None, unsubscribe_email=f"email_{i}") for i in range(2)
        ])
        cls.db.save_emails_batch(emails)
        cls.db.refresh_sender_stats()

    @classmethod
    def tearDownClass(cls):
        """Clean up the test database file."""
        if os.path.exists(cls.db_path):
            os.remove(cls.db_path)

    def test_get_subscription_stats_correctness(self):
        """
        Tests that get_subscription_stats returns the correct data, including the unsubscribe
        link from the MOST RECENT email.
        """
        stats = self.db.get_subscription_stats()
        self.assertEqual(len(stats), 2)

        stats_by_sender = {s['sender_email']: s for s in stats}

        self.assertEqual(stats_by_sender['promo@example.com']['unsubscribe_email'], 'email_0')
        self.assertEqual(stats_by_sender['news@example.com']['unsubscribe_link'], 'link_0')

if __name__ == "__main__":
    unittest.main(verbosity=2)
