<p align="center">
  <img src="assets/banner.png" alt="MailCleaner" width="600">
</p>

<p align="center">
  <strong>AI-powered email management for Gmail</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#unraid-setup">Unraid Setup</a> •
  <a href="#docker">Docker</a> •
  <a href="#features">Features</a>
</p>

---

## Features

- **AI Categorization** - Automatically sorts emails into: Important, Personal, Newsletter, Promotions, Social, Ads, Spam
- **Local AI (Ollama)** - Built-in Privacy-First AI for summaries and cleanup (Runs offline!)
- **AI Cleanup** - Identifies and suggests deletion for bulk spam/ads
- **Feedback Loop** - Train the model by correcting categories
- **Bulk Actions** - Delete spam and promotional emails in one click
- **Smart Unsubscribe** - One-click unsubscribe from newsletters
- **Sender Analysis** - See who sends you the most email
- **Privacy First** - Your data never leaves your machine (Local DB + Local AI)

---

## Quick Start

```bash
# Clone and start
git clone https://github.com/espentruls/mailcleaner.git
cd mailcleaner
docker-compose up -d

# Open in browser
open http://localhost:5000
```

**That's it!** The app includes a step-by-step onboarding wizard that guides you through:
1. Creating a Google Cloud project
2. Enabling Gmail API
3. Setting up OAuth credentials
4. Connecting your Gmail account

No manual configuration needed - just follow the in-app instructions.

---

## Unraid Setup

### Add Container Method

1. Go to **Docker** → **Add Container**
2. Configure:

| Field | Value |
|-------|-------|
| Name | `mailcleaner` |
| Repository | `ghcr.io/espentruls/mailcleaner:latest` |
| Port | `5000` → `5000` |
| Path | `/mnt/user/appdata/mailcleaner` → `/app/data` |

3. Add environment variables:
   - `OAUTHLIB_INSECURE_TRANSPORT` = `1`
   - `DOCKER_CONTAINER` = `1`

4. Click **Apply** and access at `http://YOUR_UNRAID_IP:5000`

### XML Template

Download [mailcleaner-unraid.xml](docs/mailcleaner-unraid.xml) and import via Community Applications.

---

## Docker Compose

```yaml
services:
  mailcleaner:
    image: ghcr.io/espentruls/mailcleaner:latest
    container_name: mailcleaner
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
    environment:
      - OAUTHLIB_INSECURE_TRANSPORT=1
      - DOCKER_CONTAINER=1
    restart: unless-stopped
```

---

## Local AI (Ollama)

This application now comes with **Ollama** built-in, running the `qwen2.5:3b` model locally.

- **No API Key Required**: All processing happens on your device.
- **Privacy**: No email data is sent to external cloud providers for AI processing.
- **Requirements**: Allocates ~2-4GB RAM for the model.

### AI Features:
1.  **Summarization**: Click "Ask AI" on any email.
2.  **AI Cleanup**: Scan your inbox for junk (Spam/Ads) and delete in bulk.
3.  **Training**: Correct email categories to train the model over time.

---

## License

MIT License - see [LICENSE](LICENSE)
