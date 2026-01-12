"""
Gmail API client for MailCleaner.
Handles authentication, fetching emails, deleting, and batch operations.
"""

import os
import base64
import email
import re
import time
import random
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from email.utils import parseaddr

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from models import Email, Database

# Gmail API scopes needed
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
]

# Rate limiting constants
QUOTA_UNITS_PER_SECOND = 150  # Stay below 250 for safety
READ_MESSAGE_COST = 5
LIST_MESSAGES_COST = 5
MODIFY_MESSAGE_COST = 5
SEND_MESSAGE_COST = 100


class GmailClient:
    def __init__(self, credentials_path: str = None, token_path: str = None):
        base_path = Path(__file__).parent.parent
        is_docker = os.environ.get('DOCKER_CONTAINER') == '1'
        
        if is_docker:
            # In Docker, use /app/data for persistent files
            data_path = Path('/app/data')
            data_path.mkdir(parents=True, exist_ok=True)
            default_creds = data_path / "credentials.json"
            default_token = data_path / "token.json"
        else:
            # Local development - use project root
            default_creds = base_path / "credentials.json"
            default_token = base_path / "token.json"
        
        self.credentials_path = credentials_path or default_creds
        self.token_path = token_path or default_token
        self.service = None
        self._quota_used = 0
        self._quota_reset_time = time.time()

    def authenticate(self) -> bool:
        """Authenticate with Gmail API using OAuth2."""
        creds = None

        # Load existing token
        if Path(self.token_path).exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    creds = None

            if not creds:
                if not Path(self.credentials_path).exists():
                    raise FileNotFoundError(
                        f"credentials.json not found at {self.credentials_path}. "
                        "Please download it from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save token for future use
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())

        self.service = build('gmail', 'v1', credentials=creds)
        return True

    def _check_quota(self, cost: int):
        """Simple rate limiting to avoid hitting quota."""
        current_time = time.time()
        if current_time - self._quota_reset_time >= 1:
            self._quota_used = 0
            self._quota_reset_time = current_time

        if self._quota_used + cost > QUOTA_UNITS_PER_SECOND:
            sleep_time = 1 - (current_time - self._quota_reset_time)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self._quota_used = 0
            self._quota_reset_time = time.time()

        self._quota_used += cost

    def _exponential_backoff(self, func, max_retries: int = 5):
        """Execute function with exponential backoff on rate limit errors."""
        for attempt in range(max_retries):
            try:
                return func()
            except HttpError as e:
                if e.resp.status in [429, 500, 503]:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    print(f"Rate limited, waiting {wait_time:.2f}s before retry {attempt + 1}")
                    time.sleep(wait_time)
                else:
                    raise
        raise Exception(f"Max retries ({max_retries}) exceeded")

    def get_profile(self) -> dict:
        """Get user's Gmail profile."""
        self._check_quota(READ_MESSAGE_COST)
        return self._exponential_backoff(
            lambda: self.service.users().getProfile(userId='me').execute()
        )

    def list_messages(self, query: str = "", max_results: int = 500,
                     page_token: str = None) -> Tuple[List[dict], Optional[str]]:
        """
        List messages matching query.
        Returns tuple of (messages, next_page_token).
        """
        self._check_quota(LIST_MESSAGES_COST)
        result = self._exponential_backoff(
            lambda: self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=min(max_results, 500),
                pageToken=page_token
            ).execute()
        )
        messages = result.get('messages', [])
        next_token = result.get('nextPageToken')
        return messages, next_token

    def get_message(self, msg_id: str, format: str = 'full') -> dict:
        """Get a single message by ID."""
        self._check_quota(READ_MESSAGE_COST)
        return self._exponential_backoff(
            lambda: self.service.users().messages().get(
                userId='me',
                id=msg_id,
                format=format
            ).execute()
        )

    def get_messages_batch(self, msg_ids: List[str], format: str = 'metadata') -> List[dict]:
        """
        Fetch multiple messages in batch.
        Gmail API supports batch requests of up to 100 calls, but we limit to 50 for safety.
        """
        messages = []
        batch_size = 15  # Reduced from 50 to avoid 429 Rate Limit errors

        for i in range(0, len(msg_ids), batch_size):
            batch_ids = msg_ids[i:i + batch_size]
            batch = self.service.new_batch_http_request()

            def callback(request_id, response, exception):
                if exception:
                    print(f"Error fetching message {request_id}: {exception}")
                else:
                    messages.append(response)

            for msg_id in batch_ids:
                self._check_quota(READ_MESSAGE_COST)
                batch.add(
                    self.service.users().messages().get(
                        userId='me',
                        id=msg_id,
                        format=format,
                        metadataHeaders=['From', 'Subject', 'Date', 'List-Unsubscribe']
                    ),
                    callback=callback
                )

            self._exponential_backoff(lambda: batch.execute())

        return messages

    def parse_message(self, msg: dict) -> Email:
        """Parse a Gmail API message into our Email model."""
        headers = {h['name'].lower(): h['value'] for h in msg.get('payload', {}).get('headers', [])}

        # Parse sender
        from_header = headers.get('from', '')
        sender_name, sender_email = parseaddr(from_header)
        if not sender_name:
            sender_name = sender_email

        # Parse date
        date_str = headers.get('date', '')
        try:
            # Gmail dates can have various formats
            date = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            date = datetime.now()

        # Get labels
        labels = msg.get('labelIds', [])
        is_read = 'UNREAD' not in labels

        # Get snippet (preview text)
        snippet = msg.get('snippet', '')

        # Get body preview
        body_preview = self._extract_body_preview(msg)

        # Parse unsubscribe link
        unsubscribe_link, unsubscribe_email = self._parse_unsubscribe_header(
            headers.get('list-unsubscribe', '')
        )

        return Email(
            id=msg['id'],
            thread_id=msg.get('threadId', msg['id']),
            sender=sender_name,
            sender_email=sender_email.lower() if sender_email else '',
            subject=headers.get('subject', '(No Subject)'),
            snippet=snippet,
            body_preview=body_preview[:500] if body_preview else snippet,
            date=date,
            is_read=is_read,
            labels=labels,
            unsubscribe_link=unsubscribe_link,
            unsubscribe_email=unsubscribe_email
        )

    def _extract_body_preview(self, msg: dict, max_length: int = 500) -> str:
        """Extract plain text preview from message body."""
        payload = msg.get('payload', {})

        def get_body_from_parts(parts):
            for part in parts:
                mime_type = part.get('mimeType', '')
                if mime_type == 'text/plain':
                    data = part.get('body', {}).get('data', '')
                    if data:
                        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                elif 'parts' in part:
                    result = get_body_from_parts(part['parts'])
                    if result:
                        return result
            return None

        # Try to get plain text body
        if 'parts' in payload:
            body = get_body_from_parts(payload['parts'])
            if body:
                return body[:max_length]

        # Fall back to direct body
        body_data = payload.get('body', {}).get('data', '')
        if body_data:
            return base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')[:max_length]

        return msg.get('snippet', '')

    def _parse_unsubscribe_header(self, header: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse List-Unsubscribe header.
        Can contain mailto: links and/or http: links.
        Returns (http_link, mailto_email).
        """
        if not header:
            return None, None

        http_link = None
        mailto_email = None

        # Find all URLs in angle brackets
        urls = re.findall(r'<([^>]+)>', header)

        for url in urls:
            if url.startswith('mailto:'):
                # Extract email from mailto:email@domain.com?subject=...
                email_match = re.match(r'mailto:([^?]+)', url)
                if email_match:
                    mailto_email = email_match.group(1)
            elif url.startswith('http://') or url.startswith('https://'):
                http_link = url

        return http_link, mailto_email

    def delete_message(self, msg_id: str, permanent: bool = False) -> bool:
        """
        Delete a message.
        If permanent=False, moves to trash. If permanent=True, permanently deletes.
        """
        self._check_quota(MODIFY_MESSAGE_COST)
        try:
            if permanent:
                self._exponential_backoff(
                    lambda: self.service.users().messages().delete(
                        userId='me', id=msg_id
                    ).execute()
                )
            else:
                self._exponential_backoff(
                    lambda: self.service.users().messages().trash(
                        userId='me', id=msg_id
                    ).execute()
                )
            return True
        except HttpError as e:
            print(f"Error deleting message {msg_id}: {e}")
            return False

    def delete_messages_batch(self, msg_ids: List[str], permanent: bool = False) -> Tuple[int, int]:
        """
        Delete multiple messages in batch.
        Returns (success_count, failure_count).
        """
        success = 0
        failure = 0

        if permanent:
            # Use batchDelete for permanent deletion
            batch_size = 1000  # API limit
            for i in range(0, len(msg_ids), batch_size):
                batch_ids = msg_ids[i:i + batch_size]
                try:
                    self._check_quota(len(batch_ids) * MODIFY_MESSAGE_COST)
                    self._exponential_backoff(
                        lambda: self.service.users().messages().batchDelete(
                            userId='me',
                            body={'ids': batch_ids}
                        ).execute()
                    )
                    success += len(batch_ids)
                except HttpError as e:
                    print(f"Error in batch delete: {e}")
                    failure += len(batch_ids)
        else:
            # Use batchModify to move to trash
            batch_size = 1000
            for i in range(0, len(msg_ids), batch_size):
                batch_ids = msg_ids[i:i + batch_size]
                try:
                    self._check_quota(len(batch_ids) * MODIFY_MESSAGE_COST)
                    self._exponential_backoff(
                        lambda: self.service.users().messages().batchModify(
                            userId='me',
                            body={
                                'ids': batch_ids,
                                'addLabelIds': ['TRASH'],
                                'removeLabelIds': ['INBOX']
                            }
                        ).execute()
                    )
                    success += len(batch_ids)
                except HttpError as e:
                    print(f"Error in batch trash: {e}")
                    failure += len(batch_ids)

        return success, failure

    def send_unsubscribe_email(self, to_email: str, subject: str = "unsubscribe") -> bool:
        """Send an unsubscribe email to the given address."""
        try:
            message = email.message.EmailMessage()
            message['To'] = to_email
            message['Subject'] = subject
            message.set_content("unsubscribe")

            encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()

            self._check_quota(SEND_MESSAGE_COST)
            self._exponential_backoff(
                lambda: self.service.users().messages().send(
                    userId='me',
                    body={'raw': encoded}
                ).execute()
            )
            return True
        except Exception as e:
            print(f"Error sending unsubscribe email: {e}")
            return False

    def fetch_all_emails(self, query: str = "", max_emails: int = 1000,
                        callback=None, stop_event=None) -> List[Email]:
        """
        Fetch all emails matching query with progress callback.
        Callback receives (current_count, total_estimate).
        """
        all_emails = []
        page_token = None
        total_fetched = 0

        while total_fetched < max_emails:
            # Check if stop was requested
            if stop_event and stop_event.is_set():
                print("Sync stopped by user")
                break

            messages, next_token = self.list_messages(
                query=query,
                max_results=min(500, max_emails - total_fetched),
                page_token=page_token
            )

            if not messages:
                break

            # Batch fetch message details
            msg_ids = [m['id'] for m in messages]
            detailed_messages = self.get_messages_batch(msg_ids, format='metadata')

            for msg in detailed_messages:
                if stop_event and stop_event.is_set():
                    break
                try:
                    email_obj = self.parse_message(msg)
                    all_emails.append(email_obj)
                except Exception as e:
                    print(f"Error parsing message: {e}")

            total_fetched += len(messages)

            if callback:
                callback(total_fetched, max_emails)

            if not next_token:
                break

            page_token = next_token

        return all_emails


def main():
    """Test the Gmail client."""
    client = GmailClient()

    print("Authenticating with Gmail...")
    client.authenticate()

    profile = client.get_profile()
    print(f"Logged in as: {profile['emailAddress']}")

    print("\nFetching recent emails...")
    emails = client.fetch_all_emails(max_emails=20)

    for e in emails[:5]:
        print(f"\n{'='*60}")
        print(f"From: {e.sender} <{e.sender_email}>")
        print(f"Subject: {e.subject}")
        print(f"Date: {e.date}")
        print(f"Read: {e.is_read}")
        if e.unsubscribe_link or e.unsubscribe_email:
            print(f"Unsubscribe: {e.unsubscribe_link or e.unsubscribe_email}")
        print(f"Preview: {e.snippet[:100]}...")


if __name__ == "__main__":
    main()
