import sqlite3
import os

DB_PATH = '/app/data/mail_cleaner.db' if os.path.exists('/app/data/mail_cleaner.db') else 'mail_cleaner.db'

def check_db():
    print(f"Checking DB at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("DATABASE FILE NOT FOUND!")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        # Check Emails
        count = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        print(f"Total Emails: {count}")
        
        # Check Sender Stats
        s_count = conn.execute("SELECT COUNT(*) FROM sender_stats").fetchone()[0]
        print(f"Total Sender Stats: {s_count}")
        
        if s_count > 0:
            print("Top 5 Senders from DB:")
            rows = conn.execute("SELECT * FROM sender_stats ORDER BY total_emails DESC LIMIT 5").fetchall()
            for r in rows:
                print(f" - {r['email']}: {r['total_emails']}")
                
        # Check Settings
        res = conn.execute("SELECT value FROM settings WHERE key='dashboard_cache'").fetchone()
        if res:
            print("Dashboard Cache: FOUND (Length: {})".format(len(res[0])))
        else:
            print("Dashboard Cache: NOT FOUND")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    check_db()
