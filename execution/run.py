"""
Main entry point for MailCleaner application.
Run this file to start the web application.
"""

import os
import sys
import webbrowser
from pathlib import Path
from threading import Timer

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)


def open_browser():
    """Open browser after server starts."""
    webbrowser.open('http://localhost:5000')


def main():
    """Run the MailCleaner web application."""
    from web_app import create_app, app

    # Create template directories if they don't exist
    templates_dir = Path(__file__).parent / 'templates'
    static_dir = Path(__file__).parent / 'static'
    templates_dir.mkdir(exist_ok=True)
    static_dir.mkdir(exist_ok=True)
    (static_dir / 'css').mkdir(exist_ok=True)
    (static_dir / 'js').mkdir(exist_ok=True)

    # Create .tmp directory for database and cache
    tmp_dir = Path(__file__).parent.parent / '.tmp'
    tmp_dir.mkdir(exist_ok=True)

    # Also create data dir (for Docker volume mount)
    data_dir = Path(__file__).parent.parent / 'data'
    data_dir.mkdir(exist_ok=True)

    print("""
    ╔══════════════════════════════════════════════════════════════╗
    ║                                                              ║
    ║   MailCleaner - Intelligent Email Management                 ║
    ║                                                              ║
    ║   Starting web server at http://localhost:5000               ║
    ║                                                              ║
    ║   Open your browser and go to: http://localhost:5000         ║
    ║                                                              ║
    ╚══════════════════════════════════════════════════════════════╝
    """)

    # Check for credentials
    creds_path = Path(__file__).parent.parent / "credentials.json"
    if not creds_path.exists():
        print("""
    ℹ️  First time setup detected!

    The onboarding wizard will guide you through:
    1. Creating a Google Cloud project
    2. Enabling Gmail API
    3. Setting up OAuth credentials
    4. (Optional) Adding Gemini AI key

    Open http://localhost:5000 to begin setup.
        """)

    # Check for Gemini API key
    if os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY'):
        print("    ✓ Gemini API key configured\n")

    # Determine if we should auto-open browser
    # Don't auto-open in Docker (no display) or when DEBUG=true
    debug_mode = os.getenv('DEBUG', 'false').lower() == 'true'
    in_docker = os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER', False)

    if not debug_mode and not in_docker:
        Timer(1.5, open_browser).start()

    # Run Flask app
    create_app()
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=debug_mode
    )


if __name__ == '__main__':
    main()
