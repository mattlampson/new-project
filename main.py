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

# ---------------------------------------------------------------------------
# Smart-slice helpers
# ---------------------------------------------------------------------------

# Matches any markdown heading line (##, ###, ####) that contains a month name
# and a 4-digit year — e.g. "### February 25, 2026" or "## February 2026"
_DATE_HEADING = re.compile(
    r"^#{1,4}\s+[^\n]*"
    r"(?:January|February|March|April|May|June|July|August"
    r"|September|October|November|December)"
    r"[^\n]*20\d{2}[^\n]*$",
    re.MULTILINE | re.IGNORECASE,
)

# Jina Reader always ends its metadata block with a line of ≥10 '=' chars.
# Matching past it gives us the clean page markdown, skipping Published Time etc.
_JINA_SEP = re.compile(r"={10,}[ \t]*[\r\n]+", re.MULTILINE)


def _jina_content(text: str) -> str:
    """
    Strip Jina's injected metadata header (Title / URL Source / Published Time).
    Jina always ends its header with a line of '===...===' separators.
    Falls back to skipping the first 500 chars if the separator is absent.
    """
    m = _JINA_SEP.search(text)
    if m:
        return text[m.end():]
    return text[500:]


def _smart_slice(text: str) -> tuple[str, str]:
    """
    Skip the Jina metadata header, then find the first two date-headings.
    Returns (date_string, body) where body *includes* the heading line so
    the rendered email starts with the ### Date heading, not a floating paragraph.
    Returns ("", "") if no date headings are found.
    """
    content = _jina_content(text)

    matches = list(_DATE_HEADING.finditer(content))
    if not matches:
        return "", ""

    first = matches[0]
    date_str = first.group(0).lstrip("#").strip()
    start = first.start()   # include the heading itself in the body
    end = matches[1].start() if len(matches) > 1 else len(content)

    body = content[start:end].strip()
    return date_str, body


# ---------------------------------------------------------------------------
# Site-specific parsers
# ---------------------------------------------------------------------------

def _fix_relative_links(body: str, base_url: str) -> str:
    """
    Convert any markdown link whose target starts with '/' into an absolute URL.
    e.g. ](/docs/foo)  →  ](https://platform.claude.com/docs/foo)
         ](/en/articles/bar) → ](https://help.openai.com/en/articles/bar)
    """
    return re.sub(r"\]\(/", f"]({base_url}/", body)


def parse_claude(text: str) -> dict:
    date_str, body = _smart_slice(text)
    if not date_str:
        return _fallback(text)

    body = _fix_relative_links(body, "https://platform.claude.com")
    return {"date": date_str, "title": date_str, "body": body[:3000]}


def parse_openai(text: str) -> dict:
    date_str, body = _smart_slice(text)
    if not date_str:
        return _fallback(text)

    body = _fix_relative_links(body, "https://help.openai.com")
    return {"date": date_str, "title": date_str, "body": body[:3000]}


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
# Email builder — inline CSS only (Gmail-safe)
# ---------------------------------------------------------------------------

def _apply_inline_styles(html: str) -> str:
    """
    Replace every HTML tag produced by the markdown library with an equivalent
    tag carrying explicit inline styles.  No class names, no <style> block —
    Gmail renders all of this correctly across all clients and platforms.

    h1/h2/h3 use progressively lighter colours so the date heading (###) reads
    as a clear sub-title beneath the masthead source name.
    """
    replacements = [
        ("<h1>", '<h1 style="margin:0 0 14px 0;font-size:22px;font-weight:700;color:#f5f5f7;line-height:1.3;">'),
        ("<h2>", '<h2 style="margin:18px 0 8px 0;font-size:18px;font-weight:600;color:#f5f5f7;line-height:1.4;">'),
        ("<h3>", '<h3 style="margin:0 0 16px 0;font-size:20px;font-weight:700;color:#f5f5f7;line-height:1.3;border-bottom:1px solid #3a3a3c;padding-bottom:10px;">'),
        ("<h4>", '<h4 style="margin:14px 0 5px 0;font-size:13px;font-weight:600;color:#aeaeb2;line-height:1.4;">'),
        ("<p>",  '<p style="margin:0 0 12px 0;font-size:15px;color:#ebebf0;line-height:1.65;">'),
        ("<ul>", '<ul style="margin:0 0 14px 0;padding-left:22px;color:#ebebf0;">'),
        ("<ol>", '<ol style="margin:0 0 14px 0;padding-left:22px;color:#ebebf0;">'),
        ("<li>", '<li style="margin-bottom:8px;font-size:15px;line-height:1.65;color:#ebebf0;">'),
        ("<a ",  '<a style="color:#2997ff;text-decoration:none;" '),
        ("<code>", '<code style="background-color:#2c2c2e;color:#e5e5ea;padding:2px 6px;border-radius:4px;font-size:13px;font-family:\'SF Mono\',Menlo,Consolas,monospace;">'),
        ("<pre>",  '<pre style="background-color:#2c2c2e;color:#e5e5ea;padding:14px 16px;border-radius:8px;font-size:13px;font-family:\'SF Mono\',Menlo,Consolas,monospace;margin:0 0 14px 0;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">'),
        ("<strong>", '<strong style="font-weight:600;color:#f5f5f7;">'),
        ("<em>",     '<em style="color:#d1d1d6;font-style:italic;">'),
        ("<blockquote>", '<blockquote style="margin:0 0 12px 0;padding:10px 14px;border-left:3px solid #3a3a3c;color:#aeaeb2;font-style:italic;">'),
        ("<hr />",  '<hr style="border:none;border-top:1px solid #3a3a3c;margin:16px 0;" />'),
        ("<hr>",    '<hr style="border:none;border-top:1px solid #3a3a3c;margin:16px 0;" />'),
    ]
    for old, new in replacements:
        html = html.replace(old, new)
    return html


def build_email_html(source_name: str, update: dict) -> str:
    """
    Build a fully inline-CSS HTML email safe for Gmail on all platforms.

    Layout
    ──────
    [masthead]  branded header: AI SENTINEL pill + source name
    [card]      rendered Markdown body, which now starts with the ### Date
                heading so the content is properly anchored
    [footer]
    """
    raw_html = md_lib.markdown(update["body"], extensions=["extra", "sane_lists"])
    body_html = _apply_inline_styles(raw_html)

    # colour-scheme hints stop iOS Gmail auto-inverting the dark background
    head = (
        '<head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        '</head>'
    )

    # masthead — always light text on dark, explicit hex so Gmail can't guess wrong
    masthead = (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#000000;">'
        '<tr><td style="padding:28px 24px 20px 24px;">'

        # AI SENTINEL pill badge
        '<div style="display:inline-block;background-color:#0071e3;color:#ffffff;'
        'font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;'
        'padding:5px 14px;border-radius:20px;margin-bottom:14px;">'
        'AI&nbsp;SENTINEL'
        '</div>'

        # source name (the "newsletter title")
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        f'Roboto,\'Helvetica Neue\',Arial,sans-serif;font-size:28px;font-weight:700;'
        f'color:#f5f5f7;line-height:1.2;letter-spacing:-0.3px;">{source_name}</div>'

        # thin divider
        '<div style="margin-top:18px;height:1px;background-color:#3a3a3c;"></div>'

        '</td></tr>'
        '</table>'
    )

    # content card — explicit background + text colours on every wrapper
    card = (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#1c1c1e;">'
        '<tr><td style="padding:24px 24px 32px 24px;background-color:#1c1c1e;'
        'color:#ebebf0;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        'Roboto,\'Helvetica Neue\',Arial,sans-serif;font-size:15px;line-height:1.65;">'
        f'{body_html}'
        '</td></tr>'
        '</table>'
    )

    footer = (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#000000;">'
        '<tr><td style="padding:16px 24px 28px 24px;text-align:center;'
        'color:#636366;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        'Roboto,\'Helvetica Neue\',Arial,sans-serif;font-size:11px;letter-spacing:0.2px;">'
        'AI Release Notes Sentinel &mdash; checking every 4 hours'
        '</td></tr>'
        '</table>'
    )

    return (
        '<!DOCTYPE html>'
        '<html lang="en">'
        + head +
        '<body style="margin:0;padding:0;background-color:#000000;'
        '-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#000000;">'
        '<tr><td align="center" style="padding:0;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="max-width:600px;margin:0 auto;background-color:#000000;">'
        '<tr><td>'
        + masthead
        + '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#1c1c1e;border-radius:0 0 16px 16px;overflow:hidden;">'
        '<tr><td>'
        + card
        + '</td></tr>'
        '</table>'
        + footer +
        '</td></tr>'
        '</table>'
        '</td></tr>'
        '</table>'
        '</body></html>'
    )


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
