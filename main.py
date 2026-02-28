import hashlib
import json
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

SOURCES = [
    {
        "name": "ChatGPT Release Notes",
        "url": "https://r.jina.ai/https://help.openai.com/en/articles/6825453-chatgpt-release-notes",
    },
    {
        "name": "OpenAI Model Release Notes",
        "url": "https://r.jina.ai/https://help.openai.com/en/articles/9624314-model-release-notes",
    },
    {
        "name": "Claude Release Notes",
        "url": "https://r.jina.ai/https://platform.claude.com/docs/en/release-notes/overview",
    },
]

STATE_FILE = "state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def fetch_content(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def extract_latest_update(markdown, source_name):
    """Extract the most recent update block from Markdown content."""
    # Try to match a date-headed section (common patterns: ## Date, **Date**, or bare date lines)
    # Pattern 1: Markdown heading followed by content until next heading
    heading_pattern = re.compile(
        r"(?:^|\n)(#{1,3}\s+.{0,80}(?:20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec).{0,80})\n([\s\S]*?)(?=\n#{1,3}\s|\Z)",
        re.IGNORECASE,
    )

    # Pattern 2: Bold date lines
    bold_date_pattern = re.compile(
        r"\*\*([^*]*(?:20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[^*]*)\*\*\s*\n([\s\S]*?)(?=\n\*\*[^*]*(?:20\d{2}|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[^*]*\*\*|\Z)",
        re.IGNORECASE,
    )

    # Pattern 3: Plain date at line start (YYYY-MM-DD or Month Day, Year)
    plain_date_pattern = re.compile(
        r"(?:^|\n)((?:\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}))\s*\n([\s\S]*?)(?=\n(?:\d{4}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2})|\Z)",
        re.IGNORECASE,
    )

    for pattern in [heading_pattern, bold_date_pattern, plain_date_pattern]:
        matches = list(pattern.finditer(markdown))
        if matches:
            first = matches[0]
            title_or_date = first.group(1).strip().lstrip("#").strip()
            body = first.group(2).strip()
            # Limit body to first 3000 chars to keep emails readable
            body = body[:3000]
            return {"date": title_or_date, "title": title_or_date, "body": body}

    # Fallback: take first 500 chars of content
    snippet = markdown.strip()[:500]
    return {"date": "Unknown", "title": source_name, "body": snippet}


def compute_hash(date, title, body):
    raw = f"{date}|{title}|{body}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def markdown_to_html(text):
    """Convert basic Markdown to HTML."""
    # Escape HTML special chars first
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"__(.+?)__", r"<strong>\1</strong>", text)

    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)

    # Inline code
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)

    # Headings
    text = re.sub(r"^### (.+)$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<h2>\1</h2>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$", r"<h1>\1</h1>", text, flags=re.MULTILINE)

    # Unordered lists
    text = re.sub(r"^[-*] (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
    text = re.sub(r"(<li>.*</li>)", r"<ul>\1</ul>", text, flags=re.DOTALL)

    # Paragraphs / line breaks
    paragraphs = re.split(r"\n{2,}", text)
    html_parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if para.startswith("<h") or para.startswith("<ul"):
            html_parts.append(para)
        else:
            para = para.replace("\n", "<br>")
            html_parts.append(f"<p>{para}</p>")

    return "\n".join(html_parts)


def build_email_html(source_name, update):
    body_html = markdown_to_html(update["body"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 16px;
  }}
  .container {{
    max-width: 680px;
    margin: 0 auto;
    background-color: #2a2a2a;
    border-radius: 8px;
    padding: 24px;
  }}
  .badge {{
    display: inline-block;
    background-color: #4a90e2;
    color: #fff;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 12px;
  }}
  h1 {{
    color: #ffffff;
    font-size: 22px;
    margin: 0 0 4px 0;
  }}
  .date {{
    color: #888;
    font-size: 14px;
    margin-bottom: 20px;
  }}
  .divider {{
    border: none;
    border-top: 1px solid #444;
    margin: 20px 0;
  }}
  .body-content {{
    color: #d0d0d0;
    font-size: 15px;
    line-height: 1.7;
  }}
  h2, h3 {{
    color: #ffffff;
  }}
  code {{
    background-color: #3a3a3a;
    color: #e0e0e0;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: 'Courier New', monospace;
    font-size: 13px;
  }}
  ul {{
    padding-left: 20px;
  }}
  li {{
    margin-bottom: 6px;
  }}
  .footer {{
    margin-top: 24px;
    color: #666;
    font-size: 12px;
    text-align: center;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="badge">AI Sentinel</div>
  <h1>{source_name}</h1>
  <div class="date">{update['date']}</div>
  <hr class="divider">
  <div class="body-content">
    {body_html}
  </div>
  <div class="footer">
    You are receiving this because you monitor AI release notes via AI Release Notes Sentinel.
  </div>
</div>
</body>
</html>"""


def send_email(source_name, update):
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        print("ERROR: GMAIL_USER or GMAIL_APP_PASSWORD environment variables not set.", file=sys.stderr)
        sys.exit(1)

    recipient = "lampsonmatt@gmail.com"
    subject = f"[AI SENTINEL] New Update: {source_name}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = recipient

    html_body = build_email_html(source_name, update)
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, recipient, msg.as_string())

    print(f"Email sent for: {source_name}")


def main():
    state = load_state()
    state_changed = False

    for source in SOURCES:
        name = source["name"]
        url = source["url"]
        print(f"Checking: {name}")

        try:
            content = fetch_content(url)
        except Exception as e:
            print(f"ERROR fetching {name}: {e}", file=sys.stderr)
            continue

        update = extract_latest_update(content, name)
        current_hash = compute_hash(update["date"], update["title"], update["body"])
        stored_hash = state.get(name)

        if stored_hash == current_hash:
            print(f"No change detected for: {name}")
            continue

        print(f"Change detected for: {name} — sending alert.")
        state[name] = current_hash
        state_changed = True

        try:
            send_email(name, update)
        except Exception as e:
            print(f"ERROR sending email for {name}: {e}", file=sys.stderr)

    if state_changed:
        save_state(state)
        print("State updated.")
    else:
        print("All sources up to date. No emails sent.")


if __name__ == "__main__":
    main()
