"""
Flask web application for MailCleaner.
Provides a modern UI for email management with onboarding.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional
from collections import defaultdict

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from dotenv import load_dotenv

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent))

from models import Database, Email, EmailCategory

load_dotenv()

app = Flask(__name__,
           template_folder=str(Path(__file__).parent / 'templates'),
           static_folder=str(Path(__file__).parent / 'static'))
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'mailcleaner-dev-key-change-in-prod')

# Base paths - detect Docker environment
BASE_PATH = Path(__file__).parent.parent
IS_DOCKER = os.environ.get('DOCKER_CONTAINER') == '1'

if IS_DOCKER:
    # In Docker, use /app/data for persistent files
    DATA_PATH = Path('/app/data')
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH = DATA_PATH / "credentials.json"
    TOKEN_PATH = DATA_PATH / "token.json"
    ENV_PATH = DATA_PATH / ".env"
else:
    # Local development - use project root
    CREDENTIALS_PATH = BASE_PATH / "credentials.json"
    TOKEN_PATH = BASE_PATH / "token.json"
    ENV_PATH = BASE_PATH / ".env"

# Global instances (initialized on first request)
db: Optional[Database] = None
gmail_client = None
categorizer = None
summarizer = None
unsubscriber = None


def init_services():
    """Initialize all services."""
    global db, gmail_client, categorizer, summarizer, unsubscriber

    from gmail_client import GmailClient
    from categorizer import EmailCategorizer, bootstrap_model
    from summarizer import EmailSummarizer
    from unsubscriber import UnsubscribeHandler

    if db is None:
        db = Database()
    if categorizer is None:
        categorizer = EmailCategorizer()
        # Bootstrap if no model exists
        if not categorizer.is_trained:
            bootstrap_model()
            categorizer = EmailCategorizer()  # Reload
    if summarizer is None:
        summarizer = EmailSummarizer()
    if gmail_client is None:
        gmail_client = GmailClient()
    if unsubscriber is None:
        unsubscriber = UnsubscribeHandler(gmail_client, db)


def is_setup_complete():
    """Check if the initial setup is complete."""
    return CREDENTIALS_PATH.exists()


def is_authenticated():
    """Check if user is authenticated with Gmail."""
    return session.get('authenticated', False)


@app.before_request
def before_request():
    """Initialize services before each request."""
    # Skip for static files and setup endpoints
    if request.endpoint == 'static':
        return
    if request.endpoint and request.endpoint.startswith('api_setup'):
        return
    if request.endpoint == 'onboarding':
        return

    # Only init services if setup is complete
    if is_setup_complete():
        try:
            init_services()
        except Exception as e:
            print(f"Error initializing services: {e}")


@app.route('/')
def index():
    """Main page - show onboarding, login, or dashboard."""
    if not is_setup_complete():
        return redirect(url_for('onboarding'))

    if not is_authenticated():
        return render_template('login.html')

    return render_template('dashboard.html')


@app.route('/setup')
def onboarding():
    """Show onboarding/setup page."""
    return render_template('onboarding.html')


@app.route('/api/setup/status')
def api_setup_status():
    """Check setup status."""
    gemini_configured = bool(os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'))

    # Also check .env file
    if not gemini_configured and ENV_PATH.exists():
        try:
            env_content = ENV_PATH.read_text()
            gemini_configured = 'GEMINI_API_KEY=' in env_content and 'your_gemini' not in env_content and 'your_key' not in env_content
        except Exception:
            pass

    return jsonify({
        'credentials_exists': CREDENTIALS_PATH.exists(),
        'token_exists': TOKEN_PATH.exists(),
        'gemini_configured': gemini_configured,
        'fully_configured': CREDENTIALS_PATH.exists()
    })


@app.route('/api/setup/credentials', methods=['POST'])
def api_setup_credentials():
    """Handle credentials.json upload."""
    if 'credentials' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['credentials']

    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    if not file.filename.endswith('.json'):
        return jsonify({'success': False, 'error': 'File must be a JSON file'}), 400

    try:
        # Read and validate JSON
        content = file.read().decode('utf-8')
        data = json.loads(content)

        # Check if it looks like valid OAuth credentials
        if 'installed' not in data and 'web' not in data:
            return jsonify({
                'success': False,
                'error': 'Invalid credentials file. Make sure you downloaded OAuth client credentials (Desktop app type).'
            }), 400

        # Save the file
        with open(CREDENTIALS_PATH, 'w') as f:
            f.write(content)

        return jsonify({'success': True})

    except json.JSONDecodeError:
        return jsonify({'success': False, 'error': 'Invalid JSON file'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/setup/gemini', methods=['POST'])
def api_setup_gemini():
    """Save and validate Gemini API key."""
    data = request.json or {}
    api_key = data.get('api_key', '').strip()

    if not api_key:
        return jsonify({'success': False, 'error': 'No API key provided'}), 400

    # Validate the key by making a test request
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content("Say 'OK' if you can hear me.")

        if not response.text:
            return jsonify({'success': False, 'error': 'Invalid API key'}), 400

    except Exception as e:
        error_msg = str(e)
        if 'API_KEY_INVALID' in error_msg or 'invalid' in error_msg.lower():
            return jsonify({'success': False, 'error': 'Invalid API key. Please check and try again.'}), 400
        elif 'quota' in error_msg.lower():
            # Key is valid but quota exceeded - still save it
            pass
        else:
            return jsonify({'success': False, 'error': f'API error: {error_msg}'}), 400

    # Save to .env file
    try:
        env_content = ""
        if ENV_PATH.exists():
            env_content = ENV_PATH.read_text()

        # Update or add GEMINI_API_KEY
        lines = env_content.split('\n')
        found = False
        new_lines = []
        for line in lines:
            if line.startswith('GEMINI_API_KEY='):
                new_lines.append(f'GEMINI_API_KEY={api_key}')
                found = True
            else:
                new_lines.append(line)

        if not found:
            new_lines.append(f'GEMINI_API_KEY={api_key}')

        ENV_PATH.write_text('\n'.join(new_lines))

        # Also set in current environment
        os.environ['GEMINI_API_KEY'] = api_key

        # Reinitialize summarizer
        global summarizer
        from summarizer import EmailSummarizer
        summarizer = EmailSummarizer(api_key=api_key)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': f'Failed to save: {str(e)}'}), 500


@app.route('/auth/login')
def login():
    """Initiate Gmail OAuth flow using web-based redirect."""
    if not is_setup_complete():
        return redirect(url_for('onboarding'))

    try:
        import json
        from google_auth_oauthlib.flow import Flow
        
        # Read credentials to determine type
        with open(CREDENTIALS_PATH) as f:
            creds_data = json.load(f)
        
        # Determine if web or desktop credentials
        if 'web' in creds_data:
            # Web application credentials - use redirect flow
            flow = Flow.from_client_secrets_file(
                str(CREDENTIALS_PATH),
                scopes=[
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.modify',
                    'https://www.googleapis.com/auth/gmail.send',
                ],
                redirect_uri='http://localhost:5000/auth/callback'
            )
            
            authorization_url, state = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'
            )
            
            session['oauth_state'] = state
            return redirect(authorization_url)
        else:
            # Desktop app credentials - use InstalledAppFlow (local only)
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH),
                scopes=[
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.modify', 
                    'https://www.googleapis.com/auth/gmail.send',
                ]
            )
            creds = flow.run_local_server(port=0)
            
            # Save token
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())
            
            session['authenticated'] = True
            init_services()
            profile = gmail_client.get_profile()
            session['email'] = profile.get('emailAddress', '')
            return redirect(url_for('index'))
            
    except FileNotFoundError as e:
        return render_template('error.html', error=str(e))
    except Exception as e:
        return render_template('error.html', error=f"Authentication failed: {str(e)}")


@app.route('/auth/callback')
def oauth_callback():
    """Handle OAuth callback from Google."""
    try:
        import json
        from google_auth_oauthlib.flow import Flow
        
        # Recreate the flow
        flow = Flow.from_client_secrets_file(
            str(CREDENTIALS_PATH),
            scopes=[
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.modify',
                'https://www.googleapis.com/auth/gmail.send',
            ],
            redirect_uri='http://localhost:5000/auth/callback',
            state=session.get('oauth_state')
        )
        
        # Exchange authorization code for tokens
        flow.fetch_token(authorization_response=request.url)
        
        creds = flow.credentials
        
        # Save token for future use
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())
        
        session['authenticated'] = True
        
        # Initialize services and get profile
        init_services()
        gmail_client.service = build_gmail_service(creds)
        profile = gmail_client.get_profile()
        session['email'] = profile.get('emailAddress', '')
        
        return redirect(url_for('index'))
        
    except Exception as e:
        return render_template('error.html', error=f"OAuth callback failed: {str(e)}")


def build_gmail_service(creds):
    """Build Gmail API service from credentials."""
    from googleapiclient.discovery import build
    return build('gmail', 'v1', credentials=creds)


@app.route('/auth/logout')
def logout():
    """Log out user."""
    session.clear()
    return redirect(url_for('index'))


@app.route('/api/profile')
def api_profile():
    """Get user profile."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        profile = gmail_client.get_profile()
        return jsonify(profile)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/fetch', methods=['POST'])
def api_fetch_emails():
    """Fetch and categorize emails from Gmail."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        max_emails = min(data.get('max_emails', 500), 2000)
        query = data.get('query', '')
        read_filter = data.get('read_filter', 'all')

        # Build query based on filter
        if read_filter == 'unread':
            query = f"{query} is:unread".strip()
        elif read_filter == 'read':
            query = f"{query} -is:unread".strip()

        # Clear existing data if fresh fetch
        if data.get('fresh', False):
            db.clear_all()

        # Fetch emails
        emails = gmail_client.fetch_all_emails(query=query, max_emails=max_emails)

        # Categorize
        categorizer.categorize_batch(emails)

        # Save to database
        db.save_emails_batch(emails)

        # Get stats
        stats = db.get_category_stats()

        return jsonify({
            'success': True,
            'total_fetched': len(emails),
            'stats': stats
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/emails')
def api_get_emails():
    """Get emails, optionally filtered by category or read status."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        category = request.args.get('category')
        sender = request.args.get('sender')
        read_filter = request.args.get('read_filter', 'all')
        limit = min(int(request.args.get('limit', 500)), 1000)

        if sender:
            emails = db.get_emails_by_sender(sender)
        elif category:
            emails = db.get_emails_by_category(EmailCategory(category))
        else:
            emails = db.get_all_emails(read_filter=read_filter, limit=limit)

        return jsonify({
            'emails': [e.to_dict() for e in emails],
            'total': len(emails)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/emails/grouped')
def api_get_emails_grouped():
    """Get emails grouped by sender with stats."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        read_filter = request.args.get('read_filter', 'all')
        emails = db.get_all_emails(read_filter=read_filter, limit=2000)

        # Group by sender
        groups = defaultdict(lambda: {
            'sender': '',
            'sender_email': '',
            'emails': [],
            'total': 0,
            'unread': 0,
            'categories': defaultdict(int),
            'has_unsubscribe': False,
            'last_received': None,
            'summary': None
        })

        for email in emails:
            key = email.sender_email
            group = groups[key]
            group['sender'] = email.sender
            group['sender_email'] = email.sender_email
            group['emails'].append(email.to_dict())
            group['total'] += 1
            if not email.is_read:
                group['unread'] += 1
            if email.category:
                group['categories'][email.category.value] += 1
            if email.unsubscribe_link or email.unsubscribe_email:
                group['has_unsubscribe'] = True
            if not group['last_received'] or email.date > datetime.fromisoformat(group['last_received']):
                group['last_received'] = email.date.isoformat() if email.date else None

        # Convert to list and sort by total
        result = []
        for key, group in groups.items():
            group['categories'] = dict(group['categories'])
            # Limit emails in response to save bandwidth
            group['preview_emails'] = group['emails'][:5]
            del group['emails']
            result.append(group)

        result.sort(key=lambda x: x['total'], reverse=True)

        return jsonify({
            'groups': result,
            'total_groups': len(result),
            'total_emails': len(emails)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/emails/by-category')
def api_get_emails_by_category():
    """Get emails organized by category with counts."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        stats = db.get_category_stats()
        result = {}

        for category in EmailCategory:
            cat_emails = db.get_emails_by_category(category)
            result[category.value] = {
                'count': len(cat_emails),
                'unread': sum(1 for e in cat_emails if not e.is_read),
                'emails': [e.to_dict() for e in cat_emails[:50]]  # Limit preview
            }

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/summarize', methods=['POST'])
def api_summarize():
    """Get AI summary for an email or group of emails."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        email_id = data.get('email_id')
        sender_email = data.get('sender_email')

        if email_id:
            # Summarize single email
            email = db.get_email(email_id)
            if not email:
                return jsonify({'error': 'Email not found'}), 404

            summary = summarizer.summarize_email(email)
            email.ai_summary = summary
            db.save_email(email)

            return jsonify({'summary': summary})

        elif sender_email:
            # Summarize all emails from sender
            emails = db.get_emails_by_sender(sender_email)
            if not emails:
                return jsonify({'error': 'No emails from sender'}), 404

            summary = summarizer.summarize_sender_batch(emails, sender_email)

            return jsonify({
                'summary': summary,
                'email_count': len(emails)
            })

        return jsonify({'error': 'email_id or sender_email required'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete', methods=['POST'])
def api_delete_emails():
    """Delete emails (move to trash)."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        email_ids = data.get('email_ids', [])
        permanent = data.get('permanent', False)

        if not email_ids:
            return jsonify({'error': 'No email IDs provided'}), 400

        success, failure = gmail_client.delete_messages_batch(email_ids, permanent=permanent)
        db.mark_emails_deleted(email_ids)

        return jsonify({
            'success': success,
            'failure': failure,
            'total': len(email_ids)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete/by-sender', methods=['POST'])
def api_delete_by_sender():
    """Delete all emails from a sender."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        sender_email = data.get('sender_email')
        permanent = data.get('permanent', False)

        if not sender_email:
            return jsonify({'error': 'sender_email required'}), 400

        emails = db.get_emails_by_sender(sender_email)
        email_ids = [e.id for e in emails]

        success, failure = gmail_client.delete_messages_batch(email_ids, permanent=permanent)
        db.mark_emails_deleted(email_ids)

        return jsonify({
            'sender': sender_email,
            'success': success,
            'failure': failure,
            'total': len(email_ids)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete/by-category', methods=['POST'])
def api_delete_by_category():
    """Delete all emails in a category."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        category = data.get('category')
        permanent = data.get('permanent', False)

        if not category:
            return jsonify({'error': 'category required'}), 400

        # Don't allow deleting important or uncertain
        if category in ['important', 'uncertain']:
            return jsonify({'error': f'Cannot bulk delete {category} category'}), 400

        emails = db.get_emails_by_category(EmailCategory(category))
        email_ids = [e.id for e in emails]

        success, failure = gmail_client.delete_messages_batch(email_ids, permanent=permanent)
        db.mark_emails_deleted(email_ids)

        return jsonify({
            'category': category,
            'success': success,
            'failure': failure,
            'total': len(email_ids)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/unsubscribe', methods=['POST'])
def api_unsubscribe():
    """Unsubscribe from a sender."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        email_id = data.get('email_id')
        sender_email = data.get('sender_email')

        if email_id:
            email = db.get_email(email_id)
            if not email:
                return jsonify({'error': 'Email not found'}), 404
        elif sender_email:
            emails = db.get_emails_by_sender(sender_email)
            if not emails:
                return jsonify({'error': 'No emails from sender'}), 404
            # Use first email with unsubscribe info
            email = next((e for e in emails if e.unsubscribe_link or e.unsubscribe_email), emails[0])
        else:
            return jsonify({'error': 'email_id or sender_email required'}), 400

        success, message = unsubscriber.unsubscribe(email)

        return jsonify({
            'success': success,
            'message': message,
            'sender': email.sender_email
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/feedback', methods=['POST'])
def api_submit_feedback():
    """Submit user feedback for ML training."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        email_id = data.get('email_id')
        decision = data.get('decision')  # 'keep' or 'delete'
        correct_category = data.get('correct_category')

        if not email_id or not decision:
            return jsonify({'error': 'email_id and decision required'}), 400

        email = db.get_email(email_id)
        if not email:
            return jsonify({'error': 'Email not found'}), 404

        # Save feedback
        db.save_user_feedback(
            email_id=email_id,
            sender_email=email.sender_email,
            subject=email.subject,
            original_category=email.category.value if email.category else 'unknown',
            user_decision=correct_category or decision
        )

        # Update email
        email.user_action = decision
        db.save_email(email)

        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/train', methods=['POST'])
def api_train_model():
    """Trigger model retraining from user feedback."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        success = categorizer.train_from_database(db)

        return jsonify({
            'success': success,
            'message': 'Model retrained successfully' if success else 'Training failed or insufficient data'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def api_stats():
    """Get overall statistics."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        category_stats = db.get_category_stats()
        sender_stats = db.get_sender_stats()

        total_emails = sum(s['count'] for s in category_stats.values())
        total_unread = sum(s['unread'] for s in category_stats.values())

        # Calculate deletable (non-important, non-uncertain)
        deletable = sum(
            s['count'] for cat, s in category_stats.items()
            if cat not in ['important', 'uncertain', 'personal']
        )

        return jsonify({
            'total_emails': total_emails,
            'total_unread': total_unread,
            'total_senders': len(sender_stats),
            'deletable': deletable,
            'would_keep': total_emails - deletable,
            'categories': category_stats,
            'top_senders': [
                {
                    'email': s.email,
                    'name': s.name,
                    'count': s.total_emails,
                    'unread': s.unread_count
                }
                for s in sender_stats[:10]
            ]
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def create_app():
    """Create and configure the Flask app."""
    # Create template and static directories
    templates_dir = Path(__file__).parent / 'templates'
    static_dir = Path(__file__).parent / 'static'
    templates_dir.mkdir(exist_ok=True)
    static_dir.mkdir(exist_ok=True)

    # Create .tmp directory
    tmp_dir = BASE_PATH / '.tmp'
    tmp_dir.mkdir(exist_ok=True)

    # Create .env if it doesn't exist
    if not ENV_PATH.exists():
        ENV_PATH.write_text("""# MailCleaner Environment Variables
FLASK_SECRET_KEY=change-this-in-production
# GEMINI_API_KEY=your_key_here
""")

    return app


if __name__ == '__main__':
    create_app()
    app.run(debug=True, port=5000, host='0.0.0.0')
