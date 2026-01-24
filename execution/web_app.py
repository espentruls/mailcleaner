"""
Flask web application for MailCleaner.
Provides a modern UI for email management with onboarding.
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import threading
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
BASE_URL = os.getenv('BASE_URL', 'http://localhost:5000').rstrip('/')
db: Optional[Database] = None
gmail_client = None
categorizer = None
summarizer = None
unsubscriber = None

# Background Sync State
sync_state: Dict = {
    'status': 'idle',  # idle, fetching, completed, stopped, error
    'current': 0,
    'total': 0,
    'error': None
}
sync_stop_event = threading.Event()
sync_thread = None


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

    # Restore service if token exists but service is missing (e.g. after restart)
    if gmail_client.service is None and TOKEN_PATH.exists():
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            from gmail_client import SCOPES

            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(TOKEN_PATH, 'w') as token_file:
                    token_file.write(creds.to_json())

            if creds and creds.valid:
                gmail_client.service = build('gmail', 'v1', credentials=creds)
        except Exception as e:
            print(f"Error restoring Gmail service: {e}")

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

# Performance Timing Decorator
import time
from functools import wraps

def time_execution(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        start_time = time.time()
        response = f(*args, **kwargs)
        duration = time.time() - start_time
        if duration > 0.5:
             print(f"[SLOW] {request.method} {request.path} took {duration:.3f}s")
        else:
             print(f"[TIMING] {request.method} {request.path} took {duration:.3f}s")
        return response
    return decorated_function


@app.route('/')
def index():
    """Main page - show onboarding, login, or dashboard."""
    setup_ok = is_setup_complete()
    
    if not is_authenticated():
        return render_template('login.html', needs_setup=not setup_ok)

    # SSR: Inject stats directly for instant load
    stats = {}
    try:
        if cached_data:
            stats = json.loads(cached_data)
            
            # Self-healing: If cache is inconsistent (emails exist but no senders), force refresh
            if stats.get('total_emails', 0) > 0 and stats.get('total_senders', 0) == 0:
                print("[SSR] Cache inconsistent (0 senders). Healing...")
                db.refresh_all_stats()
                stats = json.loads(db.get_setting('dashboard_cache'))
        else:
            # Fallback for first run
            print("[SSR] No cache found, generating stats...")
            # We must refresh ALL stats to ensure sender_stats table is populated
            db.refresh_all_stats()
            # Now fetch the freshly generated cache
            cached_data = db.get_setting('dashboard_cache')
            if cached_data:
                stats = json.loads(cached_data)
    except Exception as e:
        print(f"SSR Error: {e}")
        # Default empty stats to prevent 500
        stats = {}

    return render_template('dashboard.html', stats=stats)


@app.route('/setup')
def onboarding():
    """Show onboarding/setup page."""
    return render_template('onboarding.html', base_url=BASE_URL)


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
        with open(CREDENTIALS_PATH, 'w', encoding='utf-8') as f:
            f.write(content)

        return jsonify({'success': True})

    except json.JSONDecodeError:
        return jsonify({'success': False, 'error': 'Invalid JSON file'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
        
        # Read credentials as UTF-8
        with open(CREDENTIALS_PATH, 'r', encoding='utf-8') as f:
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
                redirect_uri=f"{BASE_URL}/auth/callback"
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
        # Pass credentials as UTF-8
        flow = Flow.from_client_secrets_file(
            str(CREDENTIALS_PATH),
            scopes=[
                'https://www.googleapis.com/auth/gmail.readonly',
                'https://www.googleapis.com/auth/gmail.modify',
                'https://www.googleapis.com/auth/gmail.send',
            ],
            redirect_uri=f"{BASE_URL}/auth/callback",
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

@app.route('/api/setup/reset', methods=['POST'])
def api_setup_reset():
    """Reset credentials and logout."""
    try:
        if CREDENTIALS_PATH.exists():
            CREDENTIALS_PATH.unlink()
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink()
        
        # Clear session
        session.clear()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


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

    global sync_thread, sync_state

    try:
        data = request.json or {}
        
        # Check if user just wants the total count first
        if data.get('get_total', False):
            profile = gmail_client.get_profile()
            total = profile.get('messagesTotal', 0)
            return jsonify({'total': total})

        # Don't start if already running
        if sync_state['status'] == 'fetching':
            return jsonify({'error': 'Sync already in progress'}), 400

        max_emails = data.get('max_emails') or 500  # Handle None/null explicitly
        query = data.get('query', '')
        read_filter = data.get('read_filter', 'all')
        fresh = data.get('fresh', False)

        # Build query based on filter
        if read_filter == 'unread':
            query = f"{query} is:unread".strip()
        elif read_filter == 'read':
            query = f"{query} -is:unread".strip()

        # Reset sync state
        sync_state.update({
            'status': 'fetching',
            'current': 0,
            'total': max_emails,
            'error': None
        })
        sync_stop_event.clear()

        def background_sync():
            try:
                print(f"[SYNC] Starting background sync: max_emails={max_emails}, fresh={fresh}")
                
                current_count = 0 
                
                # Clear existing data if fresh fetch
                if fresh:
                    print("[SYNC] Clearing existing data...")
                    db.clear_all()
                    db.set_setting('sync_min_date', '')
                    db.set_setting('sync_max_date', '')
                
                # Load sync state
                min_ts_str = db.get_setting('sync_min_date')
                max_ts_str = db.get_setting('sync_max_date')
                min_ts = float(min_ts_str) if min_ts_str else None
                max_ts = float(max_ts_str) if max_ts_str else None
                
                print(f"[SYNC] Resume state: min_ts={min_ts}, max_ts={max_ts}")

                def process_batch(emails, batch_type="history"):
                    if not emails: return
                    
                    nonlocal min_ts, max_ts, current_count
                    
                    # Update min/max dates
                    for e in emails:
                        if e.date:
                            ts = e.date.timestamp()
                            if min_ts is None or ts < min_ts: min_ts = ts
                            if max_ts is None or ts > max_ts: max_ts = ts
                    
                # Save Sync State (Use float for precision)
                    if min_ts: db.set_setting('sync_min_date', str(min_ts))
                    if max_ts: db.set_setting('sync_max_date', str(max_ts))
                    
                    print(f"[SYNC] Categorizing {len(emails)} {batch_type} emails...")
                    categorizer.categorize_batch(emails)
                    
                    print(f"[SYNC] Saving {len(emails)} {batch_type} emails...")
                    db.save_emails_batch(emails)
                    
                    current_count += len(emails)
                    sync_state['current'] = current_count

                # Wrapper callback to adjust for the phase
                def progress_callback(fetched, total):
                    # This is approximate since we have two phases
                    pass 

                # ---------------------------------------------------------
                # Phase 1: Fetch NEW emails (newer than last sync)
                # ---------------------------------------------------------
                if max_ts and not fresh:
                    print(f"[SYNC] Phase 1: Checking for new emails (after {max_ts})...")
                    # Add 1 second to avoid overlap in query, but filter strictly later
                    # Handle float strings safely
                    new_query = f"{query} after:{int(float(max_ts)) + 1}".strip()
                    
                    # Fetch new emails
                    new_emails = gmail_client.fetch_all_emails(
                        query=new_query, 
                        max_emails=max_emails, # Eat into the quota
                        callback=lambda c, t: None,
                        stop_event=sync_stop_event
                    )
                    
                    # Strict Deduplication: Filter out any emails <= max_ts
                    # This handles edge cases where Gmail API might include the boundary second
                    if new_emails:
                        original_count = len(new_emails)
                        max_ts_float = float(max_ts)
                        new_emails = [e for e in new_emails if e.date.timestamp() > max_ts_float]
                        if len(new_emails) < original_count:
                            print(f"[SYNC] Filtered out {original_count - len(new_emails)} overlapping emails")
                    
                    if new_emails:
                        print(f"[SYNC] Found {len(new_emails)} NEW unique emails")
                        process_batch(new_emails, "NEW")
                    else:
                        print("[SYNC] No new emails found")

                # ---------------------------------------------------------
                # Phase 2: Resume History (older than last sync)
                # ---------------------------------------------------------
                remaining_quota = max_emails - current_count
                
                if remaining_quota > 0 and not sync_stop_event.is_set():
                    print(f"[SYNC] Phase 2: Fetching history (quota: {remaining_quota})...")
                    
                    history_query = query
                    if min_ts and not fresh:
                        # Subtract 1 second to avoid overlap
                        history_query = f"{query} before:{int(float(min_ts)) - 1}".strip()
                        print(f"[SYNC] Resuming history from timestamp {min_ts}")
                    
                    def history_callback(fetched, total):
                        sync_state['current'] = current_count + fetched
                        sync_state['total'] = max_emails

                    history_emails = gmail_client.fetch_all_emails(
                        query=history_query,
                        max_emails=remaining_quota,
                        callback=history_callback,
                        stop_event=sync_stop_event
                    )
                    
                    if history_emails:
                        process_batch(history_emails, "history")
                    else:
                        print("[SYNC] No more history emails found")

                # Final Status Update
                if sync_stop_event.is_set():
                    sync_state['status'] = 'stopped'
                    print("[SYNC] Sync was stopped by user")
                else:
                    sync_state['status'] = 'completed'
                    # Refresh cached stats
                    print("[SYNC] Refreshing all statistics caches...")
                    db.refresh_all_stats()
                    
                sync_state['current'] = current_count
                print(f"[SYNC] Sync finished with status: {sync_state['status']}")
                print(f"[SYNC] Total emails processed: {current_count}")
                print(f"[SYNC] New Sync Window: {datetime.fromtimestamp(min_ts) if min_ts else 'N/A'} to {datetime.fromtimestamp(max_ts) if max_ts else 'N/A'}")

            except Exception as e:
                print(f"[SYNC ERROR] {e}")
                import traceback
                traceback.print_exc()
                sync_state['status'] = 'error'
                sync_state['error'] = str(e)

        sync_thread = threading.Thread(target=background_sync)
        sync_thread.start()

        return jsonify({'success': True, 'total_requested': max_emails})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/fetch/status', methods=['GET'])
def api_fetch_status():
    """Get current sync status."""
    return jsonify(sync_state)

@app.route('/api/fetch/stop', methods=['POST'])
def api_stop_sync():
    """Stop the current sync process."""
    sync_stop_event.set()
    return jsonify({'success': True})


@app.route('/api/emails')
def api_get_emails():
    """Get emails, optionally filtered by category or read status."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        category = request.args.get('category')
        sender = request.args.get('sender')
        read_filter = request.args.get('read_filter', 'all')
        limit = min(int(request.args.get('limit', 50)), 100) # Default 50, Max 100 per page
        page = int(request.args.get('page', 1))
        offset = (page - 1) * limit

        if sender:
            emails = db.get_emails_by_sender(sender, limit=limit, offset=offset)
        elif category:
            emails = db.get_emails_by_category(EmailCategory(category), limit=limit, offset=offset)
        else:
            emails = db.get_all_emails(read_filter=read_filter, limit=limit, offset=offset)

        return jsonify({
            'emails': [e.to_dict() for e in emails],
            'total': len(emails)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/senders/top')
def api_get_top_senders():
    """Get top senders directly from DB aggregation."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        senders = db.get_top_sender_groups(limit=limit)
        return jsonify(senders)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/emails/grouped')
def api_get_emails_grouped():
    """DEPRECATED: Use /api/senders/top instead."""
    # Keeping for compatibility but warning
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        read_filter = request.args.get('read_filter', 'all')

        # Optimization: Use SQL-based grouping instead of fetching 2000 emails
        # Fetch top 100 groups, which covers most use cases better than arbitrary 2000 email limit
        groups = db.get_rich_sender_groups(read_filter=read_filter, limit=100)

        total_emails = sum(g['total'] for g in groups)

        return jsonify({
            'groups': groups,
            'total_groups': len(groups),
            'total_emails': total_emails
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/emails/by-category')
def api_get_emails_by_category():
    """Get emails organized by category with counts."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        # Optimized: Use SQL aggregation instead of fetching emails
        # This returns {category_name: {'count': X, 'unread': Y}}
        stats = db.get_category_stats()
        
        # Ensure all categories are present, even if empty
        result = {}
        for category in EmailCategory:
            cat_value = category.value
            if cat_value in stats:
                result[cat_value] = {
                    'count': stats[cat_value]['count'],
                    'unread': stats[cat_value]['unread'],
                    'emails': [] # Frontend fetches these on demand
                }
            else:
                result[cat_value] = {
                    'count': 0,
                    'unread': 0,
                    'emails': []
                }

        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/summarize', methods=['POST'])
def api_summarize():
    """Generate AI summary using Ollama."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        category = data.get('category')
        sender_email = data.get('sender_email')
        email_id = data.get('email_id')
        
        client = get_ollama_client()
        if not client.is_available():
            return jsonify({'error': 'AI Service (Ollama) is not available'}), 503

        summary = ""
        result = {}

        if category:
            # Let's use get_all_emails and filter for simplicity for now
            all_emails = db.get_all_emails() # Returns Email objects
            cat_emails = [e for e in all_emails if e.category and e.category.value == category]
            
            # Convert to dicts for Ollama
            email_dicts = [{
                'sender': e.sender,
                'subject': e.subject,
                'snippet': e.snippet
            } for e in cat_emails[:50]] # Limit to 50 recent
            
            summary = client.summarize_category(category, email_dicts)
            result = {'summary': summary}

        elif sender_email:
            emails = db.get_emails_by_sender(sender_email)
            email_dicts = [{
                'subject': e.subject,
                'snippet': e.snippet
            } for e in emails[:20]]
            
            summary = client.summarize_sender_emails(sender_email, email_dicts)
            result = {'summary': summary}

        elif email_id:
            email = db.get_email(email_id)
            if not email:
                return jsonify({'error': 'Email not found'}), 404
            
            review = client.review_uncertain_email(
                subject=email.subject,
                sender=email.sender,
                snippet=email.snippet
            )
            result = review

        else:
            return jsonify({'error': 'Missing category, sender_email, or email_id'}), 400

        return jsonify(result)

    except Exception as e:
        print(f"Summarize Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/analyze/subscriptions', methods=['POST'])
def api_analyze_subscriptions():
    """Analyze subscriptions and return recommendations."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        # List of {sender_email, sender, total, unread}
        candidates = data.get('candidates', [])
        
        client = get_ollama_client()
        if not client.is_available():
            return jsonify({'error': 'AI Service (Ollama) is not available'}), 503

        results = {}
        
        # Limit to top 5 to avoid timeouts during demo
        top_candidates = candidates[:5]
        sender_emails = [cand.get('sender_email') for cand in top_candidates if cand.get('sender_email')]

        # Batch fetch recent emails
        recent_emails_map = db.get_recent_emails_for_senders(sender_emails)

        for cand in top_candidates:
            sender_email = cand.get('sender_email')
            if not sender_email: continue

            # Get recent subjects for context
            recent_emails = recent_emails_map.get(sender_email, [])
            subjects = [e.subject for e in recent_emails[:5]]
            
            analysis = client.analyze_subscription_value(
                sender=cand.get('sender', 'Unknown'),
                stats={'total': cand.get('count', 0), 'unread': cand.get('unread_count', 0)},
                recent_subjects=subjects
            )
            
            results[sender_email] = analysis

        return jsonify(results)

    except Exception as e:
        print(f"Analysis Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/suggestions/deletion', methods=['POST'])
def api_suggest_deletions():
    """Get AI suggestions for deletion from clutter categories."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
    
    try:
        # Gather candidates from clutter categories
        categories_str = ['spam', 'ads', 'promotions', 'uncertain']
        
        # Convert strings to Enums
        target_categories = []
        for cat in categories_str:
            try:
                target_categories.append(EmailCategory(cat))
            except ValueError:
                pass

        # Optimization: Single query using UNION ALL instead of loop
        # Fetch top 5 for each category efficiently
        all_emails = db.get_emails_by_categories_diverse(target_categories, limit_per_category=5)

        # Process in Python to preserve exact order preference:
        # spam -> ads -> promotions -> uncertain
        # and ensure uniqueness (though IDs should be unique from DB)

        candidates = []
        seen_ids = set()

        # Group by category for easy access
        emails_by_cat = defaultdict(list)
        for e in all_emails:
            if e.category:
                emails_by_cat[e.category.value].append(e)

        # Fill candidates list respecting the category priority order
        for cat_str in categories_str:
            # We already have sorted by date DESC from SQL for each partition
            cat_candidates = emails_by_cat.get(cat_str, [])
            
            for e in cat_candidates:
                if e.id not in seen_ids:
                    candidates.append(e)
                    seen_ids.add(e.id)

                # Check global limit
                if len(candidates) >= 20:
                    break
            
            if len(candidates) >= 20:
                break
        
        if not candidates:
             return jsonify({'suggestions': [], 'count': 0, 'message': 'No clutter emails found'})

        # Convert to dicts
        email_dicts = [{
            'id': e.id,
            'sender': e.sender,
            'subject': e.subject,
            'snippet': e.snippet
        } for e in candidates]
        
        client = get_ollama_client()
        if not client.is_available():
             return jsonify({'error': 'AI Service unavailable'}), 503
             
        delete_ids = client.suggest_deletions(email_dicts)
        
        # Hydrate suggestions with details
        suggestion_details = []
        for e in candidates:
            if e.id in delete_ids:
                suggestion_details.append({
                    'id': e.id,
                    'sender': e.sender or e.sender_email,
                    'sender_email': e.sender_email,
                    'subject': e.subject,
                    'snippet': e.snippet,
                    'category': e.category.value if e.category else 'unknown',
                    'date': e.date.isoformat() if e.date else None,
                    'is_read': e.is_read
                })
        
        return jsonify({
            'suggestions': suggestion_details,
            'count': len(suggestion_details)
        })

    except Exception as e:
        print(f"Suggestion Error: {e}")
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

        # Update dashboard cache in background
        trigger_background_refresh()

        return jsonify({
            'success': success,
            'failure': failure,
            'total': len(email_ids)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/emails/<email_id>', methods=['DELETE'])
def api_delete_single_email(email_id):
    """Delete a single email."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
         print(f"[DELETE DEBUG] Deleting email {email_id}...")
         
         # Ensure service is ready
         if gmail_client.service is None:
             print("[DELETE DEBUG] gmail_client.service is None! Attempting to restore...")
             init_services()
             
             # Double check
             if gmail_client.service is None:
                 print("[DELETE DEBUG] Failed to restore service.")
                 # Try explicit auth as last resort if token exists
                 if gmail_client.authenticate():
                     print("[DELETE DEBUG] Authenticated successfully.")
                 else:
                     return jsonify({'error': 'Gmail service not initialized - Try logging in again'}), 500

         permanent = request.args.get('permanent', 'false').lower() == 'true'
         success, failure = gmail_client.delete_messages_batch([email_id], permanent=permanent)
         print(f"[DELETE DEBUG] Batch result: success={success}, failure={failure}")
         
         if success > 0:
             db.mark_emails_deleted([email_id])
             # Update dashboard cache in background
             trigger_background_refresh()
             return jsonify({'success': True, 'id': email_id})
         else:
             print("[DELETE DEBUG] Failed (success=0)")
             return jsonify({'error': 'Failed to delete email'}), 500

    except Exception as e:
        print(f"[DELETE ERROR] Exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500


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

        email_ids = db.get_email_ids_by_sender(sender_email)

        success, failure = gmail_client.delete_messages_batch(email_ids, permanent=permanent)
        db.mark_emails_deleted(email_ids)

        # Update dashboard cache in background
        trigger_background_refresh()

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

        if category in ['important', 'uncertain']:
            return jsonify({'error': f'Cannot bulk delete {category} category'}), 400

        email_ids = db.get_email_ids_by_category(EmailCategory(category))

        success, failure = gmail_client.delete_messages_batch(email_ids, permanent=permanent)
        db.mark_emails_deleted(email_ids)

        # Update dashboard cache in background
        trigger_background_refresh()

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


from ollama_client import get_ollama_client
import time # Added for time.sleep in the new api_train_model

@app.route('/api/train', methods=['POST'])
def api_train_model():
    """Trigger model retraining from user feedback."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        success = categorizer.train_from_database(db)
        if success:
             return jsonify({'success': True, 'message': 'Model retrained successfully with latest feedback.'})
        else:
             return jsonify({'success': False, 'message': 'Not enough Training Data (need >10 labeled emails). Keep categorizing!'}), 400
    except Exception as e:
        print(f"Training Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/reply', methods=['POST'])
def api_generate_reply():
    """Generate smart reply."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        data = request.json or {}
        email_id = data.get('email_id')
        tone = data.get('tone', 'polite')

        email = db.get_email(email_id)
        if not email:
            return jsonify({'error': 'Email not found'}), 404

        client = get_ollama_client()
        if not client.is_available():
             return jsonify({'error': 'AI unavailable'}), 503
             
        # Combine snippet and body
        context = f"From: {email.sender}\nSubject: {email.subject}\nContent: {email.snippet} {email.body_preview}"
        
        reply = client.generate_reply(context, tone)
        return jsonify({'reply': reply})

    except Exception as e:
        print(f"Reply Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/subscriptions')
def api_subscriptions():
    """Get subscription stats."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401
    try:
        stats = db.get_subscription_stats()
        return jsonify(stats) if stats else jsonify([])
    except Exception as e:
         return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
@time_execution
def api_stats():
    """Get overall statistics (Cached)."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        # Try to get cached stats first
        cached_data = db.get_setting('dashboard_cache')
        
        if cached_data:
            return jsonify(json.loads(cached_data))
            
        # Fallback: Refresh if missing
        print("[CACHE MISS] Generating dashboard stats...")
        # CRITICAL FIX: Must refresh ALL stats (including sender_stats table) not just global
        db.refresh_all_stats()
        # Fetch the newly generated cache
        data = json.loads(db.get_setting('dashboard_cache'))
        return jsonify(data)

    except Exception as e:
        print(f"Stats Error: {e}")
        return jsonify({'error': str(e)}), 500


# ============== AI-Powered Summary Endpoints ==============

@app.route('/api/ai/status')
def api_ai_status():
    """Check if local AI (Ollama) is available."""
    try:
        from ollama_client import get_ollama_client
        client = get_ollama_client()
        return jsonify({
            'available': client.is_available(),
            'model_ready': client.has_model(),
            'model': client.model
        })
    except Exception as e:
        return jsonify({
            'available': False,
            'model_ready': False,
            'error': str(e)
        })





@app.route('/api/ai/summarize/sender', methods=['POST'])
def api_ai_summarize_sender():
    """Get AI summary for all emails from a sender."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        from ollama_client import get_ollama_client
        
        data = request.json or {}
        sender_email = data.get('sender_email')
        
        if not sender_email:
            return jsonify({'error': 'sender_email required'}), 400
        
        # Get emails from this sender
        emails = db.get_emails_by_sender(sender_email)
        if not emails:
            return jsonify({'error': f'No emails from sender: {sender_email}'}), 404
        
        # Convert to dicts for the AI
        email_dicts = [
            {
                'subject': e.subject,
                'snippet': e.snippet
            }
            for e in emails
        ]
        
        # Get sender name
        sender_name = emails[0].sender_name or sender_email
        
        # Get AI summary
        client = get_ollama_client()
        if not client.is_available():
            return jsonify({'error': 'AI service not available', 'fallback': True}), 503
        
        summary = client.summarize_sender_emails(sender_name, email_dicts)
        
        return jsonify({
            'sender': sender_email,
            'sender_name': sender_name,
            'email_count': len(emails),
            'summary': summary
        })
        
    except Exception as e:
        print(f"[AI ERROR] {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/ai/review/uncertain', methods=['POST'])
def api_ai_review_uncertain():
    """Get AI review for an uncertain email."""
    if not is_authenticated():
        return jsonify({'error': 'Not authenticated'}), 401

    try:
        from ollama_client import get_ollama_client
        
        data = request.json or {}
        email_id = data.get('email_id')
        
        if not email_id:
            return jsonify({'error': 'email_id required'}), 400
        
        # Get the email
        email = db.get_email(email_id)
        if not email:
            return jsonify({'error': 'Email not found'}), 404
        
        # Get AI review
        client = get_ollama_client()
        if not client.is_available():
            return jsonify({'error': 'AI service not available', 'fallback': True}), 503
        
        review = client.review_uncertain_email(
            email.subject, 
            email.sender_name or email.sender_email,
            email.snippet
        )
        
        return jsonify({
            'email_id': email_id,
            'current_category': email.category,
            'review': review
        })
        
    except Exception as e:
        print(f"[AI ERROR] {e}")
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




# Helper to get DB connection
def get_db():
    global db
    if db is None:
        init_services()
    return db

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get all settings."""
    if not is_authenticated():
        return jsonify({'error': 'Unauthorized'}), 401
    
    database = get_db()
    # Default settings
    settings = {
        'theme': database.get_setting('theme', 'dark'),
        'accent_color': database.get_setting('accent_color', '#4fd1c5')
    }
    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def save_settings():
    """Save settings."""
    if not is_authenticated():
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json or {}
    database = get_db()
    
    # Save valid settings
    valid_keys = ['theme', 'accent_color']
    for key in valid_keys:
        if key in data:
            database.set_setting(key, data[key])

    return jsonify({'success': True})



# Background Task Helper
refresh_timer = None

def trigger_background_refresh():
    """Run stats refresh in a separate thread to avoid blocking UI, with debounce."""
    global refresh_timer
    
    def run_refresh():
        try:
            print("[BACKGROUND] Starting stats refresh (Debounced)...")
            db.refresh_all_stats()
            print("[BACKGROUND] Stats refresh complete.")
        except Exception as e:
            print(f"[BACKGROUND] Error refreshing stats: {e}")

    # Cancel existing timer if it exists
    if refresh_timer:
        refresh_timer.cancel()
    
    # Start new timer for 2 seconds
    refresh_timer = threading.Timer(2.0, run_refresh)
    refresh_timer.daemon = True
    refresh_timer.start()

# Initialize DB on startup
with app.app_context():
    pass 

if __name__ == '__main__':
    create_app()
    
    # Initial stats refresh in background
    if is_setup_complete():
        def initial_refresh():
            with app.app_context():
                get_db().refresh_all_stats()
                print("[STARTUP] All statistics refreshed and cached")
        threading.Thread(target=initial_refresh).start()

    app.run(debug=True, port=5000, host='0.0.0.0')
