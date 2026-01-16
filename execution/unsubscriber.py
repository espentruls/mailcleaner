"""
Automated unsubscribe handler for MailCleaner.
Handles both mailto: and http: unsubscribe methods.
"""

import re
import requests
import smtplib
import concurrent.futures
import threading
from email.mime.text import MIMEText
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

from models import Email, Database


class UnsubscribeHandler:
    """
    Handles automated unsubscription from mailing lists.
    Supports:
    - HTTP/HTTPS POST requests to unsubscribe URLs
    - mailto: links (via Gmail API send)
    """

    def __init__(self, gmail_client=None, db: Database = None):
        self.gmail_client = gmail_client
        self.db = db or Database()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self._gmail_lock = threading.Lock()
        self._db_lock = threading.Lock()

    def can_unsubscribe(self, email: Email) -> bool:
        """Check if we can automatically unsubscribe from this sender."""
        return bool(email.unsubscribe_link or email.unsubscribe_email)

    def unsubscribe(self, email: Email) -> Tuple[bool, str]:
        """
        Attempt to unsubscribe from an email sender.
        Returns (success, message).

        Priority:
        1. HTTP POST to unsubscribe link (cleanest method)
        2. mailto: send unsubscribe email
        """
        if email.unsubscribe_link:
            success, message = self._unsubscribe_http(email)
            if success:
                self._log_attempt(email, 'http', email.unsubscribe_link, True)
                return True, message

        if email.unsubscribe_email:
            success, message = self._unsubscribe_mailto(email)
            if success:
                self._log_attempt(email, 'mailto', email.unsubscribe_email, True)
                return True, message

        return False, "No unsubscribe method available"

    def _unsubscribe_http(self, email: Email) -> Tuple[bool, str]:
        """
        Unsubscribe via HTTP POST to the unsubscribe URL.
        RFC 8058 recommends POST for one-click unsubscribe.
        """
        url = email.unsubscribe_link
        if not url:
            return False, "No HTTP unsubscribe URL"

        try:
            # First, try POST (RFC 8058 one-click unsubscribe)
            response = self.session.post(
                url,
                data={'List-Unsubscribe': 'One-Click'},
                timeout=30,
                allow_redirects=True
            )

            if response.status_code in [200, 201, 202, 204]:
                return True, f"Successfully unsubscribed via POST ({response.status_code})"

            # Some servers require GET, try that
            response = self.session.get(url, timeout=30, allow_redirects=True)

            if response.status_code in [200, 201, 202, 204]:
                # Check if page indicates success
                content = response.text.lower()
                success_indicators = [
                    'unsubscribed', 'removed', 'successfully',
                    'you have been unsubscribed', 'subscription cancelled',
                    'you will no longer receive'
                ]
                if any(indicator in content for indicator in success_indicators):
                    return True, "Successfully unsubscribed via GET"

                # Even without confirmation text, 200 OK might mean success
                return True, f"Unsubscribe page accessed ({response.status_code})"

            return False, f"HTTP request failed: {response.status_code}"

        except requests.Timeout:
            return False, "Request timed out"
        except requests.RequestException as e:
            return False, f"Request error: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    def _unsubscribe_mailto(self, email: Email) -> Tuple[bool, str]:
        """
        Unsubscribe by sending an email to the unsubscribe address.
        Requires gmail_client to be set.
        """
        mailto = email.unsubscribe_email
        if not mailto:
            return False, "No mailto unsubscribe address"

        if not self.gmail_client:
            return False, "Gmail client not available for sending"

        try:
            # Parse mailto for subject/body if specified
            subject = "unsubscribe"
            body = "unsubscribe"

            # Some mailto links have subject/body params
            if '?' in mailto:
                base_email, params = mailto.split('?', 1)
                parsed = parse_qs(params)
                subject = parsed.get('subject', ['unsubscribe'])[0]
                body = parsed.get('body', ['unsubscribe'])[0]
                mailto = base_email

            # Send via Gmail API
            with self._gmail_lock:
                success = self.gmail_client.send_unsubscribe_email(
                    to_email=mailto,
                    subject=subject
                )

            if success:
                return True, f"Unsubscribe email sent to {mailto}"
            else:
                return False, "Failed to send unsubscribe email"

        except Exception as e:
            return False, f"Error sending unsubscribe email: {str(e)}"

    def _log_attempt(self, email: Email, method: str, target: str,
                    success: bool, error: str = None):
        """Log unsubscribe attempt to database."""
        if self.db:
            with self._db_lock:
                self.db.log_unsubscribe(
                    email_id=email.id,
                    sender_email=email.sender_email,
                    method=method,
                    target=target,
                    success=success,
                    error_message=error
                )

    def _process_unsubscribe_task(self, sender_email: str, email: Email) -> Tuple[str, dict]:
        """Helper to process a single unsubscribe task."""
        if self.can_unsubscribe(email):
            success, message = self.unsubscribe(email)
            return sender_email, {
                'success': success,
                'message': message,
                'method': 'http' if email.unsubscribe_link else 'mailto'
            }
        else:
            return sender_email, {
                'success': False,
                'message': 'No unsubscribe method available',
                'method': None
            }

    def batch_unsubscribe(self, emails: list) -> dict:
        """
        Attempt to unsubscribe from multiple senders.
        Returns dict with results per sender.
        """
        results = {}

        # Group by sender to avoid duplicate attempts
        senders = {}
        for email in emails:
            if email.sender_email not in senders:
                senders[email.sender_email] = email

        # Process in parallel using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_sender = {
                executor.submit(self._process_unsubscribe_task, sender_email, email): sender_email
                for sender_email, email in senders.items()
            }

            for future in concurrent.futures.as_completed(future_to_sender):
                sender_email, result = future.result()
                results[sender_email] = result

        return results

    def get_unsubscribe_info(self, email: Email) -> dict:
        """Get information about unsubscribe options for an email."""
        return {
            'can_unsubscribe': self.can_unsubscribe(email),
            'http_link': email.unsubscribe_link,
            'mailto': email.unsubscribe_email,
            'preferred_method': 'http' if email.unsubscribe_link else 'mailto' if email.unsubscribe_email else None
        }


def main():
    """Test unsubscribe functionality."""
    from models import Email
    from datetime import datetime

    handler = UnsubscribeHandler()

    # Test email with unsubscribe link
    test_email = Email(
        id="test1",
        thread_id="test1",
        sender="Newsletter",
        sender_email="news@example.com",
        subject="Weekly Update",
        snippet="...",
        body_preview="...",
        date=datetime.now(),
        is_read=True,
        labels=[],
        unsubscribe_link="https://example.com/unsubscribe?id=123",
        unsubscribe_email="unsubscribe@example.com"
    )

    info = handler.get_unsubscribe_info(test_email)
    print(f"Unsubscribe info: {info}")


if __name__ == "__main__":
    main()
