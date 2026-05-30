from __future__ import annotations

import csv
import email.utils
import html
import json
import os
import re
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).with_name("config.json")
USER_AGENT = "DailyBrief/1.0 (+local VS Code brief generator)"
TIMEOUT_SECONDS = 12
FETCH_CACHE: dict[str, str] = {}


@dataclass(frozen=True)
class FeedItem:
    title: str
    link: str
    source: str
    published: datetime | None
    summary: str


@dataclass(frozen=True)
class MarketQuote:
    label: str
    symbol: str
    close_price: float
    open_price: float
    change: float
    percent: float
    quote_date: str


def fetch_text(url: str) -> str:
    if url in FETCH_CACHE:
        return FETCH_CACHE[url]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read()
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            charset = response.headers.get_content_charset() or "utf-8"
            text = body.decode(charset, errors="replace")
        FETCH_CACHE[url] = text
        return text


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    value = repair_mojibake(value)
    return re.sub(r"\s+", " ", value).strip()


def repair_mojibake(value: str) -> str:
    replacements = {
        "Ã¢â‚¬â„¢": "'",
        "Ã¢â‚¬Ëœ": "'",
        "Ã¢â‚¬Å“": '"',
        "Ã¢â‚¬Â": '"',
        "Ã¢â‚¬": '"',
        "Ã¢â‚¬â€œ": "-",
        "Ã¢â‚¬â€": "-",
        "Ã¢â‚¬Â¦": "...",
        "Ã‚": "",
    }
    for broken, fixed in replacements.items():
        value = value.replace(broken, fixed)
    return value


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "section"


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass

    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def short_summary(value: str, max_sentences: int = 2, max_chars: int = 320) -> str:
    value = clean_text(value)
    if not value:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", value)
    summary = " ".join(sentence for sentence in sentences[:max_sentences] if sentence).strip()
    if not summary:
        summary = value
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3].rsplit(" ", 1)[0].rstrip(".,;:") + "..."
    return summary


def child_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for child in element.iter():
        tag = child.tag.rsplit("}", 1)[-1].lower()
        if tag in names and child.text:
            return clean_text(child.text)
    return ""


def parse_feed(xml_text: str, fallback_source: str) -> list[FeedItem]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    channel_title = child_text(channel if channel is not None else root, ("title",)) or fallback_source
    items: list[FeedItem] = []

    rss_items = root.findall(".//item")
    atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    entries = rss_items or atom_items

    for entry in entries:
        title = child_text(entry, ("title",))
        link = child_text(entry, ("link",))
        if not link:
            link_node = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_node.attrib.get("href", "") if link_node is not None else ""
        published = parse_date(
            child_text(entry, ("pubdate", "published", "updated", "date"))
        )
        summary = short_summary(child_text(entry, ("description", "summary", "content", "encoded")))
        if title and link:
            items.append(
                FeedItem(
                    title=title,
                    link=link,
                    source=channel_title,
                    published=published,
                    summary=summary,
                )
            )
    return items


def collect_section(feeds: list[str], max_items: int) -> tuple[list[FeedItem], list[str]]:
    seen: set[str] = set()
    items: list[FeedItem] = []
    errors: list[str] = []

    for feed in feeds:
        try:
            parsed_url = urllib.parse.urlparse(feed)
            parsed_items = parse_feed(fetch_text(feed), parsed_url.netloc)
            for item in parsed_items:
                key = re.sub(r"\W+", "", item.title.lower())
                if key and key not in seen:
                    seen.add(key)
                    items.append(item)
        except (ET.ParseError, urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(f"{feed}: {exc}")

    items.sort(key=lambda item: item.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return items[:max_items], errors


def fetch_stooq_quote(symbol: str) -> dict[str, str] | None:
    url = f"https://stooq.com/q/l/?s={urllib.parse.quote(symbol)}&f=sd2t2ohlcv&h&e=csv"
    rows = list(csv.DictReader(fetch_text(url).splitlines()))
    if not rows:
        return None
    row = rows[0]
    if row.get("Close") in {"", "N/D", None}:
        return None
    return row


def fetch_market_quote(label: str, symbol: str) -> MarketQuote | None:
    row = fetch_stooq_quote(symbol)
    if not row:
        return None
    open_price = float(row["Open"])
    close_price = float(row["Close"])
    change = close_price - open_price
    percent = (change / open_price) * 100 if open_price else 0
    return MarketQuote(
        label=label,
        symbol=symbol,
        close_price=close_price,
        open_price=open_price,
        change=change,
        percent=percent,
        quote_date=row.get("Date", ""),
    )


def collect_market_quotes(symbols: dict[str, str]) -> tuple[list[MarketQuote], list[str]]:
    quotes: list[MarketQuote] = []
    errors: list[str] = []
    for label, symbol in symbols.items():
        try:
            quote = fetch_market_quote(label, symbol)
            if quote:
                quotes.append(quote)
            else:
                errors.append(f"{label}: no market data returned")
        except (ValueError, KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
            errors.append(f"{label}: {exc}")
    return quotes, errors


def quote_markdown(quote: MarketQuote) -> str:
    direction = "+" if quote.change >= 0 else ""
    return (
        f"- **{quote.label}**: {quote.close_price:,.2f} "
        f"({direction}{quote.change:,.2f}, {direction}{quote.percent:.2f}% latest session)"
    )


def quote_html(quote: MarketQuote) -> str:
    status = "up" if quote.change >= 0 else "down"
    direction = "+" if quote.change >= 0 else ""
    return "\n".join(
        [
            f'<article class="market-card {status}">',
            f"  <span>{html.escape(quote.label)}</span>",
            f"  <strong>{quote.close_price:,.2f}</strong>",
            f"  <em>{direction}{quote.change:,.2f} ({direction}{quote.percent:.2f}%) latest session</em>",
            "</article>",
        ]
    )


def market_snapshot(symbols: dict[str, str]) -> tuple[list[str], list[str]]:
    quotes, errors = collect_market_quotes(symbols)
    return [quote_markdown(quote) for quote in quotes], errors


def market_snapshot_html(symbols: dict[str, str]) -> tuple[list[str], list[str]]:
    quotes, errors = collect_market_quotes(symbols)
    return [quote_html(quote) for quote in quotes], errors


def big_movers(symbols: dict[str, str], limit: int) -> tuple[list[MarketQuote], list[str]]:
    quotes, errors = collect_market_quotes(symbols)
    quotes.sort(key=lambda quote: abs(quote.percent), reverse=True)
    return quotes[:limit], errors


def local_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return datetime.now().astimezone().tzinfo or timezone.utc


def format_item(item: FeedItem, local_tz) -> str:
    timestamp = ""
    if item.published:
        if sys.platform.startswith("win"):
            timestamp = item.published.astimezone(local_tz).strftime("%b %#d, %#I:%M %p")
        else:
            timestamp = item.published.astimezone(local_tz).strftime("%b %-d, %I:%M %p")
        timestamp = f" _{timestamp}_"
    line = f"- [{item.title}]({item.link}) - {item.source}{timestamp}"
    if item.summary:
        line += f"\n  {item.summary}"
    return line


def format_item_html(item: FeedItem, local_tz) -> str:
    timestamp = ""
    if item.published:
        if sys.platform.startswith("win"):
            timestamp = item.published.astimezone(local_tz).strftime("%b %#d, %#I:%M %p")
        else:
            timestamp = item.published.astimezone(local_tz).strftime("%b %-d, %I:%M %p")
        timestamp = f"<time>{html.escape(timestamp)}</time>"
    return "\n".join(
        [
            '<article class="story">',
            f'  <a href="{html.escape(item.link, quote=True)}">{html.escape(item.title)}</a>',
            f"  <div><span>{html.escape(item.source)}</span>{timestamp}</div>",
            f"  <p>{html.escape(item.summary or 'No summary was provided by this source.')}</p>",
            "</article>",
        ]
    )


def build_brief() -> str:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    local_tz = local_timezone(config.get("timezone", "America/New_York"))
    now = datetime.now(local_tz)
    max_items = int(config.get("max_items_per_section", 7))
    errors: list[str] = []

    lines = [
        f"# {config.get('brief_title', 'Morning Brief')}",
        "",
        f"_Updated {now.strftime('%A, %B %d, %Y at %I:%M %p %Z')}_",
        "",
        "## Market Snapshot",
        "",
    ]

    market_lines, market_errors = market_snapshot(config.get("market_symbols", {}))
    lines.extend(market_lines or ["- Market data was unavailable during this refresh."])
    errors.extend(market_errors)

    mover_quotes, mover_errors = big_movers(
        config.get("big_mover_symbols", {}),
        int(config.get("big_mover_limit", 8)),
    )
    lines.extend(["", "## Big Movers Watchlist", ""])
    lines.extend([quote_markdown(quote) for quote in mover_quotes] or ["- Mover data was unavailable during this refresh."])
    errors.extend(mover_errors)

    for section in config.get("rss_sections", []):
        lines.extend(["", f"## {section['name']}", ""])
        items, section_errors = collect_section(section.get("feeds", []), max_items)
        lines.extend(format_item(item, local_tz) for item in items)
        if not items:
            lines.append("- No items were available during this refresh.")
        errors.extend(section_errors)

    lines.extend(
        [
            "",
            "## Refresh Notes",
            "",
            "- This brief is generated from RSS feeds and delayed public market data.",
            "- For trading, legal, mortgage, or investment decisions, verify against primary sources.",
        ]
    )
    if errors:
        lines.extend(["", "<details>", "<summary>Sources that failed this refresh</summary>", ""])
        lines.extend(f"- {error}" for error in errors[:20])
        lines.extend(["", "</details>"])

    return "\n".join(lines) + "\n"


def build_html_brief() -> str:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    local_tz = local_timezone(config.get("timezone", "America/New_York"))
    now = datetime.now(local_tz)
    max_items = int(config.get("max_items_per_section", 7))
    errors: list[str] = []

    market_cards, market_errors = market_snapshot_html(config.get("market_symbols", {}))
    errors.extend(market_errors)
    mover_quotes, mover_errors = big_movers(
        config.get("big_mover_symbols", {}),
        int(config.get("big_mover_limit", 8)),
    )
    errors.extend(mover_errors)

    sections: list[str] = []
    for section in config.get("rss_sections", []):
        items, section_errors = collect_section(section.get("feeds", []), max_items)
        errors.extend(section_errors)
        stories = "\n".join(format_item_html(item, local_tz) for item in items)
        if not stories:
            stories = '<p class="empty">No items were available during this refresh.</p>'
        sections.append(
            "\n".join(
                [
                    f'<section id="{slugify(section["name"])}" class="panel">',
                    f"  <h2>{html.escape(section['name'])}</h2>",
                    f'  <div class="stories">{stories}</div>',
                    "</section>",
                ]
            )
        )

    error_details = ""
    if errors:
        error_items = "\n".join(f"<li>{html.escape(error)}</li>" for error in errors[:20])
        error_details = (
            '<details class="errors"><summary>Sources that failed this refresh</summary>'
            f"<ul>{error_items}</ul></details>"
        )

    title = html.escape(config.get("brief_title", "Morning Brief"))
    updated = html.escape(now.strftime("%A, %B %d, %Y at %I:%M %p %Z"))
    market_html = "\n".join(market_cards) or '<p class="empty">Market data was unavailable during this refresh.</p>'
    movers_html = "\n".join(quote_html(quote) for quote in mover_quotes)
    if not movers_html:
        movers_html = '<p class="empty">Mover data was unavailable during this refresh.</p>'
    section_html = "\n".join(sections)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #18212f;
      --muted: #667085;
      --line: #d8dee8;
      --paper: #f5f7fb;
      --panel: #ffffff;
      --accent: #2563eb;
      --up: #087443;
      --down: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: var(--paper);
      line-height: 1.45;
    }}
    header {{
      padding: 32px 24px 22px;
      background: #0f172a;
      color: white;
      border-bottom: 4px solid var(--accent);
    }}
    main {{
      min-width: 0;
    }}
    h1, h2, p {{ margin-top: 0; }}
    h1 {{ margin-bottom: 6px; font-size: 34px; letter-spacing: 0; }}
    .site-shell {{
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      gap: 22px;
      width: min(1240px, calc(100% - 32px));
      margin: 24px auto 48px;
    }}
    nav {{
      position: sticky;
      top: 16px;
      align-self: start;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
    }}
    nav a {{
      display: block;
      color: var(--ink);
      text-decoration: none;
      padding: 8px 10px;
      border-radius: 6px;
      font-size: 14px;
    }}
    nav a:hover {{ background: #eef4ff; color: var(--accent); }}
    .section-title {{
      margin: 22px 0 10px;
      font-size: 18px;
    }}
    header p {{ margin-bottom: 0; color: #cbd5e1; }}
    .market-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }}
    .market-card, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
    }}
    .market-card {{
      padding: 14px;
      border-left-width: 4px;
    }}
    .market-card.up {{ border-left-color: var(--up); }}
    .market-card.down {{ border-left-color: var(--down); }}
    .market-card span, .story div, .empty, .note, .errors {{
      color: var(--muted);
      font-size: 13px;
    }}
    .market-card strong {{
      display: block;
      margin: 7px 0 3px;
      font-size: 24px;
    }}
    .market-card em {{ font-style: normal; font-size: 13px; }}
    .market-card.up em {{ color: var(--up); }}
    .market-card.down em {{ color: var(--down); }}
    .panel {{
      padding: 18px;
      margin: 14px 0;
      scroll-margin-top: 18px;
    }}
    .panel h2 {{
      margin-bottom: 12px;
      font-size: 20px;
    }}
    .stories {{
      display: grid;
      gap: 10px;
    }}
    .story {{
      padding: 0 0 10px;
      border-bottom: 1px solid #edf0f5;
    }}
    .story:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    .story a {{
      color: var(--ink);
      font-weight: 650;
      text-decoration: none;
    }}
    .story a:hover {{ color: var(--accent); text-decoration: underline; }}
    .story div {{
      margin-top: 4px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .story p {{
      margin: 7px 0 0;
      color: #344054;
      font-size: 14px;
    }}
    .note {{
      margin: 18px 0 0;
    }}
    .errors {{
      margin-top: 12px;
    }}
    @media (max-width: 640px) {{
      header {{ padding: 24px 16px 18px; }}
      h1 {{ font-size: 28px; }}
      main {{ width: 100%; margin-top: 0; }}
      .site-shell {{ display: block; width: min(100% - 20px, 1120px); margin-top: 14px; }}
      nav {{ position: static; margin-bottom: 14px; }}
      .panel {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p>Updated {updated}</p>
  </header>
  <div class="site-shell">
    <nav aria-label="Brief sections">
      <a href="#markets">Market Snapshot</a>
      <a href="#movers">Big Movers</a>
      <a href="#financial-news">Financial News</a>
      <a href="#breaking-world-news">World News</a>
      <a href="#political-events">Political Events</a>
      <a href="#ai-news">AI News</a>
      <a href="#new-ai-models-and-research">AI Models</a>
      <a href="#housing-market">Housing Market</a>
    </nav>
    <main>
      <section id="markets" class="panel">
        <h2>Market Snapshot</h2>
        <div class="market-grid" aria-label="Market snapshot">
          {market_html}
        </div>
      </section>
      <section id="movers" class="panel">
        <h2>Big Movers Watchlist</h2>
        <div class="market-grid" aria-label="Big movers watchlist">
          {movers_html}
        </div>
      </section>
      {section_html}
      <p class="note">Generated from RSS feeds and delayed public market data. Verify primary sources before making trading, legal, mortgage, or investment decisions.</p>
      {error_details}
    </main>
  </div>
</body>
</html>
"""


def send_email_brief(config: dict, plain_text: str, html_text: str) -> None:
    email_config = config.get("email", {})
    if not email_config.get("enabled", False):
        return

    password_env_var = email_config.get("password_env_var", "ICLOUD_APP_PASSWORD")
    sender_env_var = email_config.get("sender_env_var", "BRIEF_EMAIL_SENDER")
    recipient_env_var = email_config.get("recipient_env_var", "BRIEF_EMAIL_RECIPIENT")
    password = os.environ.get(password_env_var)
    sender = os.environ.get(sender_env_var) or email_config.get("sender", "")
    recipient = os.environ.get(recipient_env_var) or email_config.get("recipient", "")

    if not password:
        print(f"Skipped email: set the {password_env_var} environment variable first.")
        return
    if not sender or not recipient:
        print(
            "Skipped email: set sender/recipient in config.json or with "
            f"{sender_env_var}/{recipient_env_var}."
        )
        return

    now = datetime.now(local_timezone(config.get("timezone", "America/New_York")))
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"{email_config.get('subject', 'Morning Brief')} - {now.strftime('%B %d, %Y')}"
    message.set_content(plain_text)
    message.add_alternative(html_text, subtype="html")

    smtp_server = email_config.get("smtp_server", "smtp.mail.me.com")
    smtp_port = int(email_config.get("smtp_port", 587))
    with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)
    print(f"Emailed brief to {recipient}")


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    output_path = ROOT / config.get("output_file", "DAILY_BRIEF.md")
    html_output_path = ROOT / config.get("html_output_file", "DAILY_BRIEF.html")
    website_output_path = ROOT / config.get("website_output_file", "morning_brief_site/index.html")
    brief = build_brief()
    html_brief = build_html_brief()
    website_output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(brief, encoding="utf-8")
    html_output_path.write_text(html_brief, encoding="utf-8")
    website_output_path.write_text(html_brief, encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"Wrote {html_output_path}")
    print(f"Wrote {website_output_path}")
    send_email_brief(config, brief, html_brief)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


