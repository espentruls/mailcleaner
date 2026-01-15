
from models import Database
import json

try:
    db = Database()
    print("Testing get_category_stats...")
    try:
        res = db.get_category_stats()
        print("Result:", res)
    except Exception as e:
        print("get_category_stats Error:", e)

    print("\nTesting get_sender_stats...")
    try:
        res = db.get_sender_stats()
        print("Result count:", len(res))
    except Exception as e:
        print("get_sender_stats Error:", e)

    print("\nTesting get_leaderboard_stats...")
    try:
        res = db.get_leaderboard_stats()
        print("Result:", json.dumps(res, indent=2))
    except Exception as e:
        print("get_leaderboard_stats Error:", e)

except Exception as e:
    print("Database init or general error:", e)
