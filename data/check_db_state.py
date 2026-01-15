import sqlite3
import os

# DB is in /app/data inside container
DB_PATH = '/app/data/mailcleaner.db'

def check_db():
    print(f"Checking DB at: {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("DATABASE FILE NOT FOUND! (Is volume mounted correctly?)")
        # List dir to help debug
        print(f"Contents of /app/data: {os.listdir('/app/data')}")
        return

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        
        # Check Emails
        try:
            count = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            print(f"Total Emails: {count}")
        except Exception as e:
            print(f"Error querying emails: {e}")
        
        # Check Sender Stats
        try:
            s_count = conn.execute("SELECT COUNT(*) FROM sender_stats").fetchone()[0]
            print(f"Total Sender Stats: {s_count}")
            
            if s_count > 0:
                print("Top 5 Senders from DB:")
                rows = conn.execute("SELECT * FROM sender_stats ORDER BY total_emails DESC LIMIT 5").fetchall()
                for r in rows:
                    print(f" - {r['email']}: {r['total_emails']}")
        except Exception as e:
            print(f"Error querying sender_stats: {e}")
                
        # Check Settings
        try:
            res = conn.execute("SELECT value FROM settings WHERE key='dashboard_cache'").fetchone()
            if res:
                print("Dashboard Cache: FOUND (Length: {})".format(len(res[0])))
                # print snippet
                print(f"Snippet: {res[0][:100]}...")
            else:
                print("Dashboard Cache: NOT FOUND (This is why dashboard might be slow/empty)")
        except Exception as e:
            print(f"Error querying settings: {e}")
            
    except Exception as e:
        print(f"Connection Error: {e}")
    finally:
        if conn: conn.close()

if __name__ == "__main__":
    check_db()
