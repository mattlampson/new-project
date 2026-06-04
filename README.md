# AI Release Notes Sentinel

> ## ⛔ STATUS: DISABLED (2026-06-04)
>
> **This is the project that sends the `[AI SENTINEL] OpenAI News: …` emails to `lampsonmatt@gmail.com`.**
> It is a **GitHub Actions cron workflow** (NOT an Apps Script). The emails go out via Python
> `smtplib` → `smtp.gmail.com:587` using the `GMAIL_USER` + `GMAIL_APP_PASSWORD` repo secrets,
> which is why they appear in the Gmail **Sent** folder and why `clasp` never found a script.
>
> The workflow was **manually disabled** on 2026-06-04 because the emails were unwanted.
> Everything (code, history, secrets, branches) is intact — nothing was deleted.
>
> **Default branch is `claude/bootstrap-sentinel-project-SqmgU`, not `main`.**
>
> | Action | Command |
> |--------|---------|
> | Check status | `gh workflow list --repo mattlampson/new-project --all` |
> | Re-enable | `gh workflow enable "AI Release Notes Sentinel" --repo mattlampson/new-project` |
> | Disable again | `gh workflow disable "AI Release Notes Sentinel" --repo mattlampson/new-project` |
> | Workflow page | https://github.com/mattlampson/new-project/actions/workflows/sentinel.yml |
>
> Every email footer now links to that workflow page (added 2026-06-04) so the source is one
> click away if mail ever reappears.

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

