# AI Release Notes Sentinel

Automatically monitors AI platform release notes and sends email alerts when new updates are detected.

## Monitored Sources

- **ChatGPT Release Notes** — OpenAI's ChatGPT changelog
- **OpenAI Model Release Notes** — OpenAI's model-specific changelog
- **Claude Release Notes** — Anthropic's Claude platform changelog

## How It Works

1. A GitHub Actions workflow runs every 4 hours.
2. Each source URL is fetched via [Jina Reader](https://jina.ai/) (`r.jina.ai`) to obtain clean Markdown, bypassing Cloudflare.
3. The most recent update block (date, title, body) is extracted from each page.
4. An MD5 hash of the extracted content is compared against `state.json`.
5. If a change is detected, an HTML email with a dark-mode layout is sent to the configured recipient.
6. `state.json` is committed back to the repository to persist state between runs.

## Setup

### 1. Add GitHub Actions Secrets

Navigate to your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** and add the following two secrets:

| Secret Name         | Description                                              |
|---------------------|----------------------------------------------------------|
| `GMAIL_USER`        | Your full Gmail address (e.g. `you@gmail.com`)          |
| `GMAIL_APP_PASSWORD`| A Gmail [App Password](https://myaccount.google.com/apppasswords) (not your regular password) |

> **Note:** You must have 2-Step Verification enabled on your Google account to generate an App Password.

### 2. Enable the Workflow

Once the secrets are added, the workflow will trigger automatically on schedule (`0 */4 * * *`) or you can run it manually from the **Actions** tab using **workflow_dispatch**.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Core monitoring, parsing, hashing, and email logic |
| `state.json` | Persisted MD5 hashes of last-seen content per source |
| `requirements.txt` | Python dependencies (`requests`) |
| `.github/workflows/sentinel.yml` | GitHub Actions workflow definition |
