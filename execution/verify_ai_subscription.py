import sys
import os
from pathlib import Path
import json

# Add execution dir to path
sys.path.insert(0, '/app/execution')

try:
    from ollama_client import OllamaClient
    print("Successfully imported OllamaClient")
except ImportError as e:
    print(f"Failed to import: {e}")
    sys.exit(1)

def test_analysis():
    client = OllamaClient()
    
    if not client.is_available():
        print("WARNING: Ollama not available. Mocking for structure test only?")
        # If ollama is not up, we might fail. 
        # But we assume it is up in the container.
        # Let's try anyway, or mock the _generate method if needed.
    
    print("Testing analyze_subscription_value...")
    
    # Test Case 1: Unsubscribe Candidate
    sender = "Spammy Newsletter"
    stats = {'total': 50, 'unread': 48} # 96% unread
    subjects = ["Buy this now!", "Last chance!", "Sale extended", "Don't miss out", "Your cart is waiting"]
    
    result = client.analyze_subscription_value(sender, stats, subjects)
    print(f"\nCase 1 (Spammy): {json.dumps(result, indent=2)}")
    
    if result.get('recommendation') not in ['KEEP', 'UNSUBSCRIBE']:
         print("FAILED: Invalid recommendation")
    
    # Test Case 2: Keep Candidate
    sender = "Important Updates"
    stats = {'total': 10, 'unread': 0} # 100% read
    subjects = ["Security Alert", "Your Invoice", "Login detected", "Terms update", "Receipt"]
    
    result2 = client.analyze_subscription_value(sender, stats, subjects)
    print(f"\nCase 2 (Important): {json.dumps(result2, indent=2)}")

if __name__ == "__main__":
    test_analysis()
