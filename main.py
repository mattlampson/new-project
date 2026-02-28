import hashlib
import json
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import markdown as md_lib
import requests

# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

SOURCES = [
    {
        "name": "ChatGPT Release Notes",
        "url": "https://r.jina.ai/https://help.openai.com/en/articles/6825453-chatgpt-release-notes",
        "parser": "openai",
    },
    {
        "name": "OpenAI Model Release Notes",
        "url": "https://r.jina.ai/https://help.openai.com/en/articles/9624314-model-release-notes",
        "parser": "openai",
    },
    {
        "name": "Claude Release Notes",
        "url": "https://r.jina.ai/https://platform.claude.com/docs/en/release-notes/overview",
        "parser": "claude",
    },
]

STATE_FILE = "state.json"
RECIPIENT = "lampsonmatt@gmail.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
}

# Month names for date pattern matching
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August"
    r"|September|October|November|December)"
)

# Matches lines like: "### February 19, 2026" or "## February 2026" or "**February 19, 2026**"
_DATE_LINE_RE = re.compile(
    rf"^({{{{1,3}}}}\s+|[ \t]*\*{{{{1,2}}}}\s*)({_MONTH}[^\n]{{{{0,60}}}}20\d{{{{2}}}}[^\n]{{{{0,20}}}})(\*{{{{0,2}}}})[ \t]*$".format().replace("{{{{", "{").replace("}}}}", "}"),
    re.MULTILINE | re.IGNORECASE,
)

# Simpler, more readable version of the same pattern
_DATE_LINE = re.compile(
    r"^(?:#{1,3}\s+|\*{1,2}\s*)("
    + _MONTH
    + r"[^\n]{0,60}20\d{2}[^\n]{0,20})\*{0,2}[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Site-specific parsers
# ---------------------------------------------------------------------------

def parse_claude(text: str) -> dict:
    """
    Claude release notes format (platform.claude.com):
        ### February 19, 2026
        - Bullet one
        - Bullet two

        ### February 17, 2026
        ...
    """
    # Find all ### Date headers
    pattern = re.compile(
        r"^###\s+("
        + _MONTH
        + r"[^\n]{0,60}20\d{2}[^\n]{0,30})[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return _fallback(text)

    first = matches[0]
    date_str = first.group(1).strip()
    start = first.end()
    end = matches[1].start() if len(matches) > 1 else len(text)
    body = text[start:end].strip()

    # Make relative Anthropic doc links absolute so they work in email
    body = re.sub(
        r"\]\(/docs/",
        r"](https://platform.claude.com/docs/",
        body,
    )

    return {"date": date_str, "title": date_str, "body": body[:3000]}


def parse_openai(text: str) -> dict:
    """
    OpenAI Help Center articles (via Jina Reader).
    Tries several date-header formats in order:
      1.  ### Specific Date, Year   (h3 with full date)
      2.  ## Month YYYY             (h2 month section)
      3.  **Date**                  (bold date)
    """
    # --- Strategy 1: ### Full date (e.g. "### February 20, 2026") ---
    h3_date = re.compile(
        r"^###\s+("
        + _MONTH
        + r"[^\n]{0,60}20\d{2}[^\n]{0,30})[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    matches = list(h3_date.finditer(text))
    if matches:
        first = matches[0]
        date_str = first.group(1).strip()
        start = first.end()
        end = matches[1].start() if len(matches) > 1 else len(text)
        body = text[start:end].strip()
        return {"date": date_str, "title": date_str, "body": body[:3000]}

    # --- Strategy 2: ## Month YYYY (e.g. "## February 2026") ---
    h2_month = re.compile(
        r"^##\s+(" + _MONTH + r"\s+20\d{2})[ \t]*$",
        re.MULTILINE | re.IGNORECASE,
    )
    matches = list(h2_month.finditer(text))
    if matches:
        first = matches[0]
        date_str = first.group(1).strip()
        start = first.end()
        end = matches[1].start() if len(matches) > 1 else len(text)
        body = text[start:end].strip()
        return {"date": date_str, "title": date_str, "body": body[:3000]}

    # --- Strategy 3: **Date** bold header ---
    bold_date = re.compile(
        r"\*\*("
        + _MONTH
        + r"[^*]{0,60}20\d{2}[^*]{0,20})\*\*[ \t]*\n([\s\S]*?)(?=\n\*\*"
        + _MONTH
        + r"|\Z)",
        re.IGNORECASE,
    )
    m = bold_date.search(text)
    if m:
        date_str = m.group(1).strip()
        body = m.group(2).strip()
        return {"date": date_str, "title": date_str, "body": body[:3000]}

    # --- Strategy 4: Generic date line (any heading level) ---
    matches = list(_DATE_LINE.finditer(text))
    if matches:
        first = matches[0]
        date_str = first.group(1).strip()
        start = first.end()
        end = matches[1].start() if len(matches) > 1 else len(text)
        body = text[start:end].strip()
        return {"date": date_str, "title": date_str, "body": body[:3000]}

    return _fallback(text)


def _fallback(text: str) -> dict:
    """Last-resort: grab first 500 chars as body."""
    snippet = text.strip()[:500]
    return {"date": "Latest Update", "title": "Latest Update", "body": snippet}


PARSERS = {
    "claude": parse_claude,
    "openai": parse_openai,
}


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def compute_hash(date: str, title: str, body: str) -> str:
    return hashlib.md5(f"{date}|{title}|{body}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Email builder
# ---------------------------------------------------------------------------

def _style_markdown_html(raw_html: str) -> str:
    """Inject inline styles onto tags produced by the markdown library."""
    replacements = [
        # headings
        ("<h1>", '<h1 style="margin:0 0 12px;font-size:22px;font-weight:700;color:#f5f5f7;line-height:1.3;">'),
        ("<h2>", '<h2 style="margin:20px 0 8px;font-size:18px;font-weight:600;color:#f5f5f7;line-height:1.4;">'),
        ("<h3>", '<h3 style="margin:16px 0 6px;font-size:15px;font-weight:600;color:#d1d1d6;line-height:1.4;">'),
        # paragraphs
        ("<p>",  '<p style="margin:0 0 12px;color:#ebebf0;font-size:15px;line-height:1.65;">'),
        # lists
        ("<ul>", '<ul style="margin:0 0 12px;padding-left:20px;color:#ebebf0;">'),
        ("<ol>", '<ol style="margin:0 0 12px;padding-left:20px;color:#ebebf0;">'),
        ("<li>", '<li style="margin-bottom:6px;font-size:15px;line-height:1.65;">'),
        # links
        ("<a ",  '<a style="color:#2997ff;text-decoration:none;" '),
        # code
        ("<code>", '<code style="background:#2c2c2e;color:#e5e5ea;padding:2px 6px;border-radius:4px;font-size:13px;font-family:\'SF Mono\',Menlo,monospace;">'),
        ("<pre>",  '<pre style="background:#2c2c2e;color:#e5e5ea;padding:12px;border-radius:8px;overflow-x:auto;font-size:13px;font-family:\'SF Mono\',Menlo,monospace;margin:0 0 12px;">'),
        # strong / em
        ("<strong>", '<strong style="color:#f5f5f7;font-weight:600;">'),
        ("<em>",     '<em style="color:#d1d1d6;">'),
        # horizontal rule
        ("<hr />", '<hr style="border:none;border-top:1px solid #3a3a3c;margin:16px 0;" />'),
    ]
    for old, new in replacements:
        raw_html = raw_html.replace(old, new)
    return raw_html


def build_email_html(source_name: str, update: dict) -> str:
    raw_md = update["body"]
    raw_html = md_lib.markdown(raw_md, extensions=["extra", "sane_lists"])
    body_html = _style_markdown_html(raw_html)
    date = update["date"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      margin: 0; padding: 0;
      background-color: #000000;
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text",
                   "Helvetica Neue", Helvetica, Arial, sans-serif;
      -webkit-text-size-adjust: 100%;
    }}
    .outer {{
      background-color: #000000;
      padding: 28px 16px;
    }}
    .inner {{
      max-width: 600px;
      margin: 0 auto;
    }}
    .badge {{
      display: inline-block;
      background: linear-gradient(135deg, #0071e3 0%, #34aadc 100%);
      color: #ffffff;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: 1px;
      text-transform: uppercase;
      padding: 5px 13px;
      border-radius: 20px;
      margin-bottom: 14px;
    }}
    .card {{
      background-color: #1c1c1e;
      border-radius: 16px;
      overflow: hidden;
    }}
    .card-header {{
      padding: 24px 24px 18px;
      border-bottom: 1px solid #3a3a3c;
    }}
    .source-label {{
      margin: 0 0 5px;
      font-size: 11px;
      font-weight: 600;
      color: #8e8e93;
      letter-spacing: 0.4px;
      text-transform: uppercase;
    }}
    .date-title {{
      margin: 0;
      font-size: 24px;
      font-weight: 700;
      color: #f5f5f7;
      line-height: 1.25;
    }}
    .card-body {{
      padding: 20px 24px 24px;
      color: #ebebf0;
      font-size: 15px;
      line-height: 1.65;
    }}
    .card-body h1 {{ margin: 0 0 12px; font-size: 20px; font-weight: 700; color: #f5f5f7; }}
    .card-body h2 {{ margin: 20px 0 8px; font-size: 17px; font-weight: 600; color: #f5f5f7; }}
    .card-body h3 {{ margin: 16px 0 6px; font-size: 14px; font-weight: 600; color: #aeaeb2; text-transform: uppercase; letter-spacing: 0.3px; }}
    .card-body p  {{ margin: 0 0 12px; }}
    .card-body ul, .card-body ol {{ margin: 0 0 12px; padding-left: 20px; }}
    .card-body li {{ margin-bottom: 7px; }}
    .card-body a  {{ color: #2997ff; text-decoration: none; }}
    .card-body a:hover {{ text-decoration: underline; }}
    .card-body code {{
      background: #2c2c2e; color: #e5e5ea;
      padding: 2px 6px; border-radius: 4px;
      font-size: 13px; font-family: "SF Mono", Menlo, monospace;
    }}
    .card-body pre {{
      background: #2c2c2e; color: #e5e5ea;
      padding: 14px; border-radius: 10px;
      overflow-x: auto; font-size: 13px;
      font-family: "SF Mono", Menlo, monospace;
      margin: 0 0 12px;
    }}
    .card-body strong {{ color: #f5f5f7; font-weight: 600; }}
    .card-body hr {{ border: none; border-top: 1px solid #3a3a3c; margin: 16px 0; }}
    .footer {{
      padding: 14px 8px 0;
      text-align: center;
      color: #636366;
      font-size: 11px;
      letter-spacing: 0.2px;
    }}
  </style>
</head>
<body>
<div class="outer">
  <div class="inner">
    <div class="badge">AI Sentinel</div>
    <div class="card">
      <div class="card-header">
        <p class="source-label">{source_name}</p>
        <h1 class="date-title">{date}</h1>
      </div>
      <div class="card-body">
        {body_html}
      </div>
    </div>
    <div class="footer">AI Release Notes Sentinel &mdash; checking every 4 hours</div>
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_email(source_name: str, update: dict) -> None:
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        print("ERROR: GMAIL_USER or GMAIL_APP_PASSWORD not set.", file=sys.stderr)
        sys.exit(1)

    subject = f"[AI SENTINEL] New Update: {source_name}"
    html = build_email_html(source_name, update)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, RECIPIENT, msg.as_string())

    print(f"  ✓ Email sent for: {source_name}")


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def fetch_content(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    state = load_state()
    state_changed = False

    for source in SOURCES:
        name = source["name"]
        url = source["url"]
        parser_key = source["parser"]
        print(f"\nChecking: {name}")

        try:
            content = fetch_content(url)
        except Exception as e:
            print(f"  ✗ Fetch error: {e}", file=sys.stderr)
            continue

        parse_fn = PARSERS[parser_key]
        try:
            update = parse_fn(content)
        except Exception as e:
            print(f"  ✗ Parse error: {e}", file=sys.stderr)
            continue

        print(f"  → Date : {update['date']}")
        print(f"  → Body : {update['body'][:80].strip()!r}…")

        current_hash = compute_hash(update["date"], update["title"], update["body"])
        stored_hash = state.get(name)

        if stored_hash == current_hash:
            print("  → No change detected.")
            continue

        print("  → Change detected — sending alert email.")
        state[name] = current_hash
        state_changed = True

        try:
            send_email(name, update)
        except Exception as e:
            print(f"  ✗ Email error: {e}", file=sys.stderr)

    if state_changed:
        save_state(state)
        print("\nState updated and saved.")
    else:
        print("\nAll sources up to date. No emails sent.")


if __name__ == "__main__":
    main()
