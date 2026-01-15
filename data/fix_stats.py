import sys
from pathlib import Path
sys.path.append('/app')
from execution.models import Database

DB_PATH = '/app/data/mailcleaner.db'

def force_refresh():
    print(f"Connecting to {DB_PATH}")
    db = Database(DB_PATH)
    
    print("Forcing refresh_all_stats()...")
    try:
        db.refresh_all_stats()
        print("Refresh complete.")
        
        # Verify
        count = db.get_total_senders_count()
        print(f"New Sender Count: {count}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    force_refresh()
