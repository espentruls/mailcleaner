import requests
import json

def test_cleanup():
    url = "http://localhost:5000/api/suggestions/deletion"
    # Need authentication? 
    # web_app.py check: if not is_authenticated(): return ..., 401
    # is_authenticated checks if CREDENTIALS_PATH exists or session has 'credentials'.
    # In local dev (simulated), maybe it passes if credentials file exists?
    # Or I can disable auth for the test if needed, but let's try calling it.
    
    # Actually, is_authenticated in web_app.py checks:
    # return os.path.exists(CREDENTIALS_PATH)
    
    try:
        response = requests.post(url, json={})
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"Count: {data.get('count')}")
            print("Suggestions:")
            print(json.dumps(data.get('suggestions'), indent=2))
        else:
            print(f"Error: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_cleanup()
