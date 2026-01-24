import time
import os
import sys
import random
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

# Setup paths
sys.path.insert(0, str(Path(__file__).parent))
from models import Database, Email, EmailCategory

DB_PATH = "benchmark_test.db"

def setup_data(num_emails=50000):
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    db = Database(db_path=DB_PATH)
    emails = []

    # Create 100 senders to have more groups
    senders = [f"sender_{i}@example.com" for i in range(100)]

    print(f"Generating {num_emails} emails...")
    batch_size = 5000
    for i in range(0, num_emails, batch_size):
        batch = []
        for j in range(batch_size):
            idx = i + j
            sender_email = random.choice(senders)
            category = random.choice(list(EmailCategory))
            is_read = random.choice([True, False])

            email = Email(
                id=f"msg_{idx}",
                thread_id=f"thread_{idx}",
                sender=sender_email.split('@')[0],
                sender_email=sender_email,
                subject=f"Subject {idx}",
                snippet=f"Snippet {idx}",
                body_preview=f"Body {idx}",
                date=datetime.now() - timedelta(minutes=random.randint(0, 500000)),
                is_read=is_read,
                labels=[],
                category=category,
                category_confidence=0.9,
                ai_summary=None,
                unsubscribe_link=None,
                unsubscribe_email=None,
                user_action=None
            )
            batch.append(email)
        db.save_emails_batch(batch)
        print(f"Saved {i+batch_size}/{num_emails}...")

    print("Data setup complete.")
    return db

def measure_old_way_limited(db):
    """Original implementation: fast but only sees 2000 emails."""
    start_time = time.time()
    read_filter = 'all'
    emails = db.get_all_emails(read_filter=read_filter, limit=2000)

    groups = defaultdict(lambda: {
        'sender': '', 'sender_email': '', 'emails': [], 'total': 0, 'unread': 0,
        'categories': defaultdict(int), 'has_unsubscribe': False, 'last_received': None
    })

    for email in emails:
        key = email.sender_email
        group = groups[key]
        group['sender'] = email.sender
        group['sender_email'] = email.sender_email
        group['emails'].append(email.to_dict())
        group['total'] += 1
        if not email.is_read: group['unread'] += 1
        if email.category: group['categories'][email.category.value] += 1
        if email.unsubscribe_link or email.unsubscribe_email: group['has_unsubscribe'] = True
        if not group['last_received'] or email.date > datetime.fromisoformat(group['last_received']):
            group['last_received'] = email.date.isoformat() if email.date else None

    result = []
    for key, group in groups.items():
        group['categories'] = dict(group['categories'])
        group['preview_emails'] = group['emails'][:5]
        del group['emails']
        result.append(group)
    result.sort(key=lambda x: x['total'], reverse=True)

    return time.time() - start_time, len(result), sum(g['total'] for g in result)

def measure_old_way_full(db):
    """Old implementation logic but trying to group EVERYTHING (simulating desired functional goal)."""
    start_time = time.time()
    read_filter = 'all'
    # Fetch ALL (no limit, or huge limit)
    emails = db.get_all_emails(read_filter=read_filter, limit=1000000)

    groups = defaultdict(lambda: {
        'sender': '', 'sender_email': '', 'emails': [], 'total': 0, 'unread': 0,
        'categories': defaultdict(int), 'has_unsubscribe': False, 'last_received': None
    })

    for email in emails:
        key = email.sender_email
        group = groups[key]
        group['sender'] = email.sender
        group['sender_email'] = email.sender_email
        group['emails'].append(email.to_dict())
        group['total'] += 1
        if not email.is_read: group['unread'] += 1
        if email.category: group['categories'][email.category.value] += 1
        if email.unsubscribe_link or email.unsubscribe_email: group['has_unsubscribe'] = True
        if not group['last_received'] or email.date > datetime.fromisoformat(group['last_received']):
            group['last_received'] = email.date.isoformat() if email.date else None

    result = []
    for key, group in groups.items():
        group['categories'] = dict(group['categories'])
        group['preview_emails'] = group['emails'][:5]
        del group['emails']
        result.append(group)
    result.sort(key=lambda x: x['total'], reverse=True)

    # Simulate limit output to top 100 like new way (though we processed everything)
    result = result[:100]

    return time.time() - start_time, len(result), sum(g['total'] for g in result)

def measure_new_way(db):
    start_time = time.time()
    try:
        if hasattr(db, 'get_rich_sender_groups'):
             # Scan all, return top 100
             result = db.get_rich_sender_groups(read_filter='all', limit=100)
        else:
             return 0, 0, 0
    except Exception as e:
        print(f"New way failed: {e}")
        return 0, 0, 0
    return time.time() - start_time, len(result), sum(g['total'] for g in result)

if __name__ == "__main__":
    try:
        db = setup_data(num_emails=50000)

        print("\n--- Benchmark Results ---")

        t1, c1, total1 = measure_old_way_limited(db)
        print(f"Old Way (Limit 2000): {t1:.4f}s | Groups: {c1} | Total Emails Processed: {total1} (Partial Data)")

        t2, c2, total2 = measure_old_way_full(db)
        print(f"Old Way (Full):       {t2:.4f}s | Groups: {c2} | Total Emails Processed (in groups): {total2} (Full Data)")

        t3, c3, total3 = measure_new_way(db)
        print(f"New Way (SQL):        {t3:.4f}s | Groups: {c3} | Total Emails Processed (in groups): {total3} (Full Data)")

        print(f"\nSpeedup vs Full In-Memory: {t2 / t3:.2f}x")

    finally:
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
