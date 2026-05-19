# AI Release Notes Sentinel

Automatically monitors AI platform release notes via RSS feeds and sends email alerts when new updates are published.

## Monitored Sources

- **ChatGPT Release Notes** — via [RSSHub](https://rsshub.app/openai/chatgpt/release-notes)
- **OpenAI Developer Changelog** — native RSS at `developers.openai.com/changelog/rss.xml`
- **OpenAI News** — native RSS at `openai.com/news/rss.xml`

## How It Works

1. A GitHub Actions workflow runs every 4 hours.
2. Each source's RSS feed is fetched with `requests` and parsed with Python's built-in `xml.etree.ElementTree` (supports both RSS 2.0 and Atom).
3. Item GUIDs are compared against `state.json` — deterministic, no hash oscillation possible.
4. New items trigger an HTML email (dark-mode, inline CSS) sent to the configured recipient.
5. On first run for a source, all current GUIDs are recorded silently (no email spam).
6. `state.json` is committed back to the repository to persist state between runs.

## Setup

### 1. Add GitHub Actions Secrets

Navigate to your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** and add:

| Secret Name         | Description                                              |
|---------------------|----------------------------------------------------------|
| `GMAIL_USER`        | Your full Gmail address (e.g. `you@gmail.com`)          |
| `GMAIL_APP_PASSWORD`| A Gmail [App Password](https://myaccount.google.com/apppasswords) (not your regular password) |

> **Note:** You must have 2-Step Verification enabled on your Google account to generate an App Password.

### 2. Enable the Workflow

The workflow triggers automatically on schedule (`0 */4 * * *`) or you can run it manually from the **Actions** tab using **workflow_dispatch**.

## Files

| File | Purpose |
|------|---------|
| `main.py` | RSS feed fetching, GUID comparison, and email logic |
| `state.json` | Persisted GUIDs of seen items per source |
| `requirements.txt` | Python dependency (`feedparser`) |
| `.github/workflows/sentinel.yml` | GitHub Actions workflow definition |

## Maintenance Note

This project may be a candidate for future archive or removal. Do not delete it opportunistically; review and re-discuss with Codex or Claude first so the GitHub Actions workflow, repository state, and any useful release-monitoring logic can be evaluated deliberately.
