"""
AI-powered email summarization using Google Gemini API.
Uses the free tier via Google AI Studio.
Caches summaries to minimize API calls.
"""

import os
import json
import hashlib
import time
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timedelta

import google.generativeai as genai
from dotenv import load_dotenv

from models import Email, Database

load_dotenv()


class RateLimiter:
    """Simple rate limiter for API calls."""

    def __init__(self, max_calls: int, period_seconds: int):
        self.max_calls = max_calls
        self.period = period_seconds
        self.calls = []

    def can_call(self) -> bool:
        now = time.time()
        # Remove old calls outside the window
        self.calls = [t for t in self.calls if now - t < self.period]
        return len(self.calls) < self.max_calls

    def record_call(self):
        self.calls.append(time.time())

    def wait_if_needed(self):
        while not self.can_call():
            time.sleep(1)


class SummaryCache:
    """Cache for email summaries to avoid redundant API calls."""

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
    Summarizes emails using Google Gemini API.
    Uses free tier (5-15 RPM) with caching to minimize calls.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        self.model = None
        self.cache = SummaryCache()
        # Conservative rate limit: 10 RPM to stay safe
        self.rate_limiter = RateLimiter(max_calls=10, period_seconds=60)
        self._initialized = False

        if self.api_key:
            self._initialize()

    def _initialize(self):
        """Initialize the Gemini API."""
        try:
            genai.configure(api_key=self.api_key)
            # Use Gemini Flash for speed and lower cost
            self.model = genai.GenerativeModel('gemini-1.5-flash')
            self._initialized = True
        except Exception as e:
            print(f"Error initializing Gemini: {e}")
            self._initialized = False

    def is_available(self) -> bool:
        """Check if AI summarization is available."""
        return self._initialized and self.model is not None

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

        # Rate limit check
        self.rate_limiter.wait_if_needed()

        try:
            prompt = f"""Summarize this email in 1-2 sentences. Focus on the main purpose/action required.
Be concise and direct. If it's promotional, say what's being offered. If it's a notification, say what happened.

Email:
{text}

Summary:"""

            response = self.model.generate_content(prompt)
            self.rate_limiter.record_call()

            summary = response.text.strip()

            # Cache the result
            self.cache.set(text, summary)

            return summary

        except Exception as e:
            print(f"Error generating summary: {e}")
            return self._fallback_summary(email)

    def summarize_sender_batch(self, emails: List[Email], sender_email: str) -> Optional[str]:
        """
        Generate a single summary for all emails from the same sender.
        Useful for bulk newsletters/promotions.
        """
        if not emails:
            return None

        if not self.is_available():
            return f"{len(emails)} emails from {emails[0].sender}"

        # Build a summary of the emails
        subjects = [e.subject for e in emails[:10]]  # Limit to recent 10
        sender_name = emails[0].sender

        text = f"Sender: {sender_name}\nSubjects:\n" + "\n".join(f"- {s}" for s in subjects)

        # Check cache
        cached = self.cache.get(f"sender:{sender_email}:{len(emails)}")
        if cached:
            return cached

        self.rate_limiter.wait_if_needed()

        try:
            prompt = f"""Summarize what kind of emails this sender typically sends based on these subject lines.
Be brief (1-2 sentences). Mention if they're newsletters, promotions, notifications, etc.

{text}

Summary:"""

            response = self.model.generate_content(prompt)
            self.rate_limiter.record_call()

            summary = response.text.strip()
            self.cache.set(f"sender:{sender_email}:{len(emails)}", summary)

            return summary

        except Exception as e:
            print(f"Error generating sender summary: {e}")
            return f"{len(emails)} emails - topics: {', '.join(subjects[:3])}"

    def analyze_email_importance(self, email: Email) -> dict:
        """
        Analyze if an email is important and why.
        Returns dict with 'is_important', 'reason', 'confidence'.
        Only used for uncertain emails.
        """
        if not self.is_available():
            return {
                'is_important': False,
                'reason': 'AI unavailable',
                'confidence': 0.0
            }

        text = f"From: {email.sender} <{email.sender_email}>\nSubject: {email.subject}\n\n{email.body_preview[:500]}"

        self.rate_limiter.wait_if_needed()

        try:
            prompt = f"""Analyze this email and determine if it's important or can be safely deleted.

Email:
{text}

Respond in JSON format:
{{"is_important": true/false, "reason": "brief reason", "confidence": 0.0-1.0}}

Important emails include: personal messages, invoices, receipts, confirmations, security alerts, appointments.
Not important: promotional, newsletters, social notifications, ads, spam.

JSON:"""

            response = self.model.generate_content(prompt)
            self.rate_limiter.record_call()

            # Parse JSON response
            response_text = response.text.strip()
            # Extract JSON from response (handle markdown code blocks)
            if '```' in response_text:
                response_text = response_text.split('```')[1]
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
            return {
                'is_important': False,
                'reason': f'Analysis error: {str(e)}',
                'confidence': 0.0
            }

    def _fallback_summary(self, email: Email) -> str:
        """Generate a basic summary without AI."""
        subject = email.subject or "(No subject)"
        preview = email.snippet[:100] if email.snippet else ""

        if len(preview) > 80:
            preview = preview[:80] + "..."

        return f"{subject} - {preview}"

    def batch_summarize_uncertain(self, emails: List[Email], db: Database) -> List[Email]:
        """
        Summarize only uncertain emails to save API calls.
        Updates emails in-place and saves to database.
        """
        uncertain = [e for e in emails if e.category and e.category.value == 'uncertain']

        # Also summarize low-confidence categorizations
        low_confidence = [e for e in emails
                        if e.category_confidence < 0.4 and e not in uncertain]

        to_summarize = uncertain + low_confidence[:20]  # Limit to conserve API

        for email in to_summarize:
            if not email.ai_summary:
                summary = self.summarize_email(email)
                email.ai_summary = summary
                db.save_email(email)

        return emails


def main():
    """Test the summarizer."""
    summarizer = EmailSummarizer()

    if not summarizer.is_available():
        print("Gemini API not available. Set GEMINI_API_KEY environment variable.")
        return

    # Test email
    test_email = Email(
        id="test1",
        thread_id="test1",
        sender="TechNews Daily",
        sender_email="newsletter@technews.com",
        subject="Your Weekly Tech Digest - AI, Cloud, and More",
        snippet="This week in tech: OpenAI announces new features, AWS launches new service...",
        body_preview="""This week in tech:

- OpenAI announces GPT-5 preview
- AWS launches new serverless database
- Microsoft updates VS Code with AI features
- Google releases new Gemini models

Read more at technews.com

Unsubscribe | Update preferences""",
        date=datetime.now(),
        is_read=True,
        labels=[],
        unsubscribe_link="https://technews.com/unsubscribe"
    )

    print("Testing single email summary...")
    summary = summarizer.summarize_email(test_email)
    print(f"Summary: {summary}")

    print("\nTesting importance analysis...")
    importance = summarizer.analyze_email_importance(test_email)
    print(f"Importance: {importance}")


if __name__ == "__main__":
    main()
