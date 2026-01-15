"""
AI-powered email summarization using Local Ollama.
"""

import os
import json
import hashlib
import time
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta

from ollama_client import OllamaClient
from models import Email, Database

class SummaryCache:
    """Cache for email summaries to avoid redundant AI calls."""

    def __init__(self, cache_path: str = None):
        base_path = Path(__file__).parent.parent / ".tmp"
        base_path.mkdir(parents=True, exist_ok=True)
        self.cache_path = cache_path or base_path / "summary_cache.json"
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if Path(self.cache_path).exists():
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_cache(self):
        with open(self.cache_path, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2)

    def _make_key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def get(self, text: str) -> Optional[str]:
        key = self._make_key(text)
        entry = self.cache.get(key)
        if entry:
            # Check if cache entry is still valid (7 days)
            cached_time = datetime.fromisoformat(entry['timestamp'])
            if datetime.now() - cached_time < timedelta(days=7):
                return entry['summary']
        return None

    def set(self, text: str, summary: str):
        key = self._make_key(text)
        self.cache[key] = {
            'summary': summary,
            'timestamp': datetime.now().isoformat()
        }
        self._save_cache()


class EmailSummarizer:
    """
    Summarizes emails using Local Ollama.
    """

    def __init__(self, api_key: str = None):
        # API key is no longer needed/used but kept for signature compatibility during refactor
        self.client = OllamaClient()
        self.cache = SummaryCache()

    def is_available(self) -> bool:
        """Check if AI summarization is available."""
        return self.client.is_available()

    def summarize_email(self, email: Email, force: bool = False) -> Optional[str]:
        """
        Generate a brief summary of an email.
        Returns cached summary if available.
        """
        if not self.is_available():
            return self._fallback_summary(email)

        # Create text to summarize
        text = f"From: {email.sender}\nSubject: {email.subject}\n\n{email.body_preview}"

        # Check cache first
        if not force:
            cached = self.cache.get(text)
            if cached:
                return cached

        try:
            prompt = f"Summarize this email in 1-2 sentences. Focus on the main purpose/action required.\n\nEmail:\n{text}"
            
            # Using category 'summary' logic from ollama_client if appropriate, 
            # or just a raw generate call. Using _generate from client would be ideal
            # but it is internal. We can use customize logic here or add public method to client.
            # For now, let's use the client's internal `_generate` if accessible or reimplement simple generation wrapper
            # modifying client usage to be safe.
            
            # Actually, let's check if OllamaClient has a generic chat/generate method exposed.
            # Looking at ollama_client.py (previous knowledge): it has `classify_email`, `summarize_sender`, `review_uncertain`.
            # It DOES NOT occupy a generic `generate` method publicly.
            # However, I can use `requests` directly here or add a method to `OllamaClient`.
            # A cleaner approach is to use `OllamaClient`'s _generate method if I can, OR just replicate the call 
            # since `OllamaClient` handles the host/model logic.
            
            # Replicating simple generate call using client properties:
            
            summary = self.client._generate(
                prompt=prompt,
                system="You are a helpful email assistant. Be concise."
            )

            if not summary:
                 return self._fallback_summary(email)

            summary = summary.strip()

            # Cache the result
            self.cache.set(text, summary)

            return summary

        except Exception as e:
            print(f"Error generating summary: {e}")
            return self._fallback_summary(email)

    def summarize_sender_batch(self, emails: List[Email], sender_email: str) -> Optional[str]:
        """
        Generate a single summary for all emails from the same sender.
        """
        # This functionality exists in OllamaClient! let's delegate.
        return self.client.summarize_sender(emails)

    def analyze_email_importance(self, email: Email) -> dict:
        """
        Analyze if an email is important and why.
        """
        if not self.is_available():
             return {'is_important': False, 'reason': 'AI unavailable', 'confidence': 0.0}

        text = f"From: {email.sender} <{email.sender_email}>\nSubject: {email.subject}\n\n{email.body_preview[:500]}"
        
        prompt = f"""Analyze this email and determine if it's important or can be safely deleted.
Email:
{text}
Respond in JSON format:
{{"is_important": true/false, "reason": "brief reason", "confidence": 0.0-1.0}}
Important emails: personal, invoices, receipts, security alerts.
Not important: newsletters, promotions, ads, spam.
JSON:"""

        try:
            response = self.client._generate(
                prompt=prompt,
                system="You are an email analyzer. Respond only in JSON."
            )
            
            # Parse JSON similar to before
            response_text = response.strip()
            if '```' in response_text:
                parts = response_text.split('```')
                if len(parts) > 1:
                    response_text = parts[1]
                    if response_text.startswith('json'):
                        response_text = response_text[4:]
            
            result = json.loads(response_text)
            return {
                'is_important': result.get('is_important', False),
                'reason': result.get('reason', ''),
                'confidence': float(result.get('confidence', 0.5))
            }
        except Exception as e:
            print(f"Error analyzing importance: {e}")
            return {'is_important': False, 'reason': f'Error: {str(e)}', 'confidence': 0.0}

    def _fallback_summary(self, email: Email) -> str:
        """Generate a basic summary without AI."""
        subject = email.subject or "(No subject)"
        preview = email.snippet[:100] if email.snippet else ""

        if len(preview) > 80:
            preview = preview[:80] + "..."

        return f"{subject} - {preview}"

    def batch_summarize_uncertain(self, emails: List[Email], db: Database) -> List[Email]:
        """
        Summarize only uncertain emails.
        """
        uncertain = [e for e in emails if e.category and e.category.value == 'uncertain']
        
        # Limit processing for local AI speed
        to_summarize = uncertain[:10]

        for email in to_summarize:
            if not email.ai_summary:
                summary = self.summarize_email(email)
                email.ai_summary = summary
                db.save_email(email)

        return emails


def main():
    """Test the summarizer."""
    try:
        summarizer = EmailSummarizer()
        if not summarizer.is_available():
            print("Ollama not available.")
            return

        print("Ollama Summarizer Initialized.")
    except Exception as e:
        print(f"Failed to init: {e}")

if __name__ == "__main__":
    main()
