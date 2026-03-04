import json
import logging
import os
import smtplib
import time
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sources — pure RSS feeds, no scraping
# ---------------------------------------------------------------------------

SOURCES = [
    {
        "name": "ChatGPT Release Notes",
        "url": "https://rsshub.app/openai/chatgpt/release-notes",
    },
    {
        "name": "OpenAI Developer Changelog",
        "url": "https://developers.openai.com/changelog/rss.xml",
    },
    {
        "name": "OpenAI News",
        "url": "https://openai.com/news/rss.xml",
    },
]

STATE_FILE = "state.json"
RECIPIENT = "lampsonmatt@gmail.com"
MAX_STORED_GUIDS = 200

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; AISentinel/2.0; "
        "+https://github.com/mattlampson/new-project)"
    )
}

# Namespace map for Atom feeds
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
}


# ---------------------------------------------------------------------------
# RSS / Atom parser
# ---------------------------------------------------------------------------

def _parse_rss_items(root: ET.Element) -> list[dict]:
    """Parse RSS 2.0 <channel><item> elements."""
    items = []
    for item in root.iter("item"):
        guid_el = item.find("guid")
        link_el = item.find("link")
        items.append({
            "guid": guid_el.text.strip() if guid_el is not None and guid_el.text else
                    (link_el.text.strip() if link_el is not None and link_el.text else ""),
            "title": (item.findtext("title") or "").strip(),
            "link": (link_el.text.strip() if link_el is not None and link_el.text else ""),
            "published": (item.findtext("pubDate") or "").strip(),
            "body": (item.findtext("content:encoded", namespaces=_NS)
                     or item.findtext("description") or "").strip(),
        })
    return items


def _parse_atom_entries(root: ET.Element) -> list[dict]:
    """Parse Atom <feed><entry> elements."""
    ns = _NS["atom"]
    items = []
    for entry in root.findall(f"{{{ns}}}entry"):
        id_el = entry.find(f"{{{ns}}}id")
        link_el = entry.find(f"{{{ns}}}link")
        link_href = link_el.get("href", "") if link_el is not None else ""

        # Atom content can live in <content> or <summary>
        content_el = entry.find(f"{{{ns}}}content")
        summary_el = entry.find(f"{{{ns}}}summary")
        body = ""
        if content_el is not None and content_el.text:
            body = content_el.text.strip()
        elif summary_el is not None and summary_el.text:
            body = summary_el.text.strip()

        items.append({
            "guid": id_el.text.strip() if id_el is not None and id_el.text else link_href,
            "title": (entry.findtext(f"{{{ns}}}title") or "").strip(),
            "link": link_href,
            "published": (entry.findtext(f"{{{ns}}}published")
                          or entry.findtext(f"{{{ns}}}updated") or "").strip(),
            "body": body,
        })
    return items


def parse_feed(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 or Atom XML into a list of item dicts."""
    root = ET.fromstring(xml_text)
    tag = root.tag.lower().split("}")[-1]  # strip namespace
    if tag == "rss":
        return _parse_rss_items(root)
    if tag == "feed":
        return _parse_atom_entries(root)
    raise ValueError(f"Unknown feed format: root tag is <{root.tag}>")


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


# ---------------------------------------------------------------------------
# HTTP fetch (3-attempt retry, 5 s between attempts)
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = 3
_RETRY_DELAY = 5  # seconds


def fetch_feed_xml(url: str) -> str:
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            last_exc = exc
            if attempt < _RETRY_ATTEMPTS:
                log.warning(
                    "Fetch attempt %d/%d failed (%s) — retrying in %ds",
                    attempt, _RETRY_ATTEMPTS, exc, _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)
    raise last_exc


# ---------------------------------------------------------------------------
# Email builder — inline CSS only (Gmail-safe)
# ---------------------------------------------------------------------------

def _apply_inline_styles(html: str) -> str:
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


def _build_entry_block(entry: dict) -> str:
    title = entry.get("title", "New Update")
    link = entry.get("link", "")
    published = entry.get("published", "")
    body_html = _apply_inline_styles(entry.get("body", ""))

    title_html = (
        f'<a style="color:#2997ff;text-decoration:none;font-size:20px;'
        f'font-weight:700;line-height:1.3;" href="{link}">{title}</a>'
        if link else
        f'<span style="font-size:20px;font-weight:700;color:#f5f5f7;'
        f'line-height:1.3;">{title}</span>'
    )

    date_html = (
        f'<div style="font-size:12px;color:#aeaeb2;margin-bottom:14px;'
        f'letter-spacing:0.3px;">{published}</div>'
        if published else ""
    )

    return (
        f'<div style="margin-bottom:28px;padding-bottom:28px;'
        f'border-bottom:1px solid #3a3a3c;">'
        f'<div style="margin-bottom:6px;">{title_html}</div>'
        f'{date_html}'
        f'<div style="font-size:15px;color:#ebebf0;line-height:1.65;">'
        f'{body_html}</div>'
        f'</div>'
    )


def build_email_html(source_name: str, entries: list[dict]) -> str:
    head = (
        '<head>'
        '<meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<meta name="color-scheme" content="light dark">'
        '<meta name="supported-color-schemes" content="light dark">'
        '</head>'
    )

    masthead = (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#000000;">'
        '<tr><td style="padding:28px 24px 20px 24px;">'
        '<div style="display:inline-block;background-color:#0071e3;color:#ffffff;'
        'font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;'
        'padding:5px 14px;border-radius:20px;margin-bottom:14px;">'
        'AI&nbsp;SENTINEL'
        '</div>'
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        f'Roboto,\'Helvetica Neue\',Arial,sans-serif;font-size:28px;font-weight:700;'
        f'color:#f5f5f7;line-height:1.2;letter-spacing:-0.3px;">{source_name}</div>'
        '<div style="margin-top:18px;height:1px;background-color:#3a3a3c;"></div>'
        '</td></tr>'
        '</table>'
    )

    entry_blocks = "".join(_build_entry_block(e) for e in entries)

    card = (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#1c1c1e;">'
        '<tr><td style="padding:24px 24px 32px 24px;background-color:#1c1c1e;'
        'color:#ebebf0;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        'Roboto,\'Helvetica Neue\',Arial,sans-serif;font-size:15px;line-height:1.65;">'
        f'{entry_blocks}'
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

def send_email(source_name: str, entries: list[dict]) -> None:
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_password:
        raise RuntimeError("GMAIL_USER or GMAIL_APP_PASSWORD env vars are not set")

    count = len(entries)
    subject = (
        f"[AI SENTINEL] {source_name}: {entries[0].get('title', 'New Update')}"
        if count == 1
        else f"[AI SENTINEL] {source_name}: {count} new updates"
    )

    html = build_email_html(source_name, entries)

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

    log.info("Email sent for %s (%d entries)", source_name, count)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("AI Sentinel starting — checking %d source(s)", len(SOURCES))
    state = load_state()
    state_changed = False

    for source in SOURCES:
        name = source["name"]
        url = source["url"]
        log.info("Checking: %s", name)

        try:
            xml_text = fetch_feed_xml(url)
            items = parse_feed(xml_text)
            log.info("  Parsed %d item(s) from feed.", len(items))

            seen_guids = set(state.get(name, []))
            first_run = name not in state

            new_items = []
            all_guids = set(seen_guids)

            for item in items:
                guid = item["guid"]
                if guid and guid not in seen_guids:
                    new_items.append(item)
                all_guids.add(guid)

            # First run: record current GUIDs without sending emails
            if first_run:
                log.info("  First run — recording %d GUIDs, no emails.", len(all_guids))
                state[name] = list(all_guids)[-MAX_STORED_GUIDS:]
                state_changed = True
                continue

            if not new_items:
                log.info("  No new entries.")
                continue

            log.info("  %d new entry(ies) — sending alert.", len(new_items))
            send_email(name, new_items)
            state[name] = list(all_guids)[-MAX_STORED_GUIDS:]
            state_changed = True

        except Exception as exc:
            log.error("  Failed to process '%s': %s", name, exc, exc_info=True)
            continue

    if state_changed:
        save_state(state)
        log.info("State updated and saved.")
    else:
        log.info("All sources up to date. No emails sent.")


if __name__ == "__main__":
    main()
