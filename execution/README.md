# Execution Scripts

This folder contains deterministic Python scripts that do the actual work.

## Design Principles

1. **Deterministic** - Same inputs always produce same outputs
2. **Well-commented** - Explain the "why", not just the "what"
3. **Testable** - Can be run independently for testing
4. **Error-handling** - Graceful failures with clear error messages
5. **No side effects** - Don't modify global state unexpectedly

## Naming Convention

Use descriptive snake_case names that clearly indicate function:
- `connect_email.py`
- `query_emails.py`
- `categorize_message.py`
- `delete_emails.py`

## Environment Variables

All scripts should load credentials from `.env` using python-dotenv:

```python
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
```

## Standard Script Structure

```python
#!/usr/bin/env python3
"""
Script: script_name.py
Purpose: Brief description of what this script does

Usage:
    python script_name.py --input "value" --output "path"

Dependencies:
    - requests
    - python-dotenv
"""

import argparse
import os
from dotenv import load_dotenv

load_dotenv()


def main(input_value: str, output_path: str) -> dict:
    """
    Main function that does the work.
    
    Args:
        input_value: Description of input
        output_path: Where to write results
        
    Returns:
        dict: Summary of what was done
    """
    # Implementation here
    return {"status": "success", "processed": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Script description")
    parser.add_argument("--input", required=True, help="Input value")
    parser.add_argument("--output", required=True, help="Output path")
    args = parser.parse_args()
    
    result = main(args.input, args.output)
    print(result)
```

## Output Convention

Scripts should write intermediate files to `.tmp/` and return structured data (dict/JSON) for the orchestration layer to use.
