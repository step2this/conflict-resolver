"""Collectors for RSS feeds, Telegram channels, and APIs."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SOURCES_PATH = Path(__file__).parent.parent / "sources.yaml"


def load_sources(path: Path = SOURCES_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _make_id(url: str | None, body: str | None) -> str:
    """SHA256 hash of URL, falling back to body content."""
    content = url or body or ""
    return hashlib.sha256(content.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_date(entry) -> str | None:
    """Extract published date from a feedparser entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return None


def collect_rss(sources: list[dict]) -> list[dict]:
    """Fetch and parse all RSS feeds, return raw items."""
    items = []
    now = _now_iso()

    for source in sources:
        name = source["name"]
        url = source["url"]
        logger.info(f"Fetching RSS: {name}")

        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                logger.warning(f"RSS parse error for {name}: {feed.bozo_exception}")
                continue

            for entry in feed.entries:
                link = getattr(entry, "link", None)
                title = getattr(entry, "title", None)
                body = getattr(entry, "summary", None) or getattr(entry, "description", None)

                items.append({
                    "id": _make_id(link, body),
                    "collected_at": now,
                    "source_name": name,
                    "source_type": source.get("type", "unknown"),
                    "bias": source.get("bias", "unknown"),
                    "channel": "rss",
                    "url": link,
                    "title": title,
                    "body": body,
                    "published_at": _parse_date(entry),
                    "has_media": False,
                    "media_urls": [],
                    "digest_included": False,
                    "confidence_score": None,
                    "event_group_id": None,
                    "geolocation": None,
                    "satellite_verified": None,
                })

            logger.info(f"  {name}: {len(feed.entries)} entries")

        except Exception as e:
            logger.error(f"Failed to fetch RSS {name}: {e}")

    return items


def collect_telegram_public(sources: list[dict]) -> list[dict]:
    """Scrape Telegram public preview pages (t.me/s/) for channels that support it."""
    items = []
    now = _now_iso()

    for source in sources:
        name = source["name"]
        channel = source["channel"]
        url = f"https://t.me/s/{channel}"
        logger.info(f"Fetching Telegram public: {name} ({channel})")

        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            messages = soup.find_all("div", class_="tgme_widget_message_wrap")

            if not messages:
                logger.warning(f"  {name}: no messages found (public preview may be disabled)")
                continue

            for msg_wrap in messages:
                msg = msg_wrap.find("div", class_="tgme_widget_message")
                if not msg:
                    continue

                # Extract message link
                msg_link = msg.get("data-post", "")
                post_url = f"https://t.me/{msg_link}" if msg_link else None

                # Extract text
                text_el = msg.find("div", class_="tgme_widget_message_text")
                body = text_el.get_text(separator="\n").strip() if text_el else None

                # Extract timestamp
                time_el = msg.find("time")
                published_at = time_el.get("datetime") if time_el else None

                # Check for media
                media_els = msg.find_all("a", class_="tgme_widget_message_photo_wrap")
                video_els = msg.find_all("video")
                has_media = bool(media_els or video_els)
                media_urls = [a.get("style", "").split("url('")[-1].rstrip("')") for a in media_els if "url(" in a.get("style", "")]

                if not body and not has_media:
                    continue

                items.append({
                    "id": _make_id(post_url, body),
                    "collected_at": now,
                    "source_name": name,
                    "source_type": source.get("type", "unknown"),
                    "bias": source.get("bias", "unknown"),
                    "channel": "telegram_public",
                    "url": post_url,
                    "title": None,
                    "body": body,
                    "published_at": published_at,
                    "has_media": has_media,
                    "media_urls": media_urls,
                    "digest_included": False,
                    "confidence_score": None,
                    "event_group_id": None,
                    "geolocation": None,
                    "satellite_verified": None,
                })

            logger.info(f"  {name}: {len(messages)} messages scraped")

        except Exception as e:
            logger.error(f"Failed to scrape Telegram {name}: {e}")

    return items


async def collect_telegram_mtproto(sources: list[dict], api_id: int, api_hash: str, session_path: str = "telegram.session") -> list[dict]:
    """Fetch messages from Telegram channels via MTProto (Telethon)."""
    from telethon import TelegramClient

    items = []
    now = _now_iso()

    client = TelegramClient(session_path, api_id, api_hash)
    await client.start()

    for source in sources:
        name = source["name"]
        channel = source["channel"]
        logger.info(f"Fetching Telegram MTProto: {name} ({channel})")

        try:
            entity = await client.get_entity(channel)
            messages = await client.get_messages(entity, limit=100)

            for msg in messages:
                if not msg.text and not msg.media:
                    continue

                post_url = f"https://t.me/{channel}/{msg.id}"
                body = msg.text or ""
                has_media = msg.media is not None

                items.append({
                    "id": _make_id(post_url, body),
                    "collected_at": now,
                    "source_name": name,
                    "source_type": source.get("type", "unknown"),
                    "bias": source.get("bias", "unknown"),
                    "channel": "telegram_mtproto",
                    "url": post_url,
                    "title": None,
                    "body": body,
                    "published_at": msg.date.isoformat() if msg.date else None,
                    "has_media": has_media,
                    "media_urls": [],
                    "digest_included": False,
                    "confidence_score": None,
                    "event_group_id": None,
                    "geolocation": None,
                    "satellite_verified": None,
                })

            logger.info(f"  {name}: {len(messages)} messages fetched")

        except Exception as e:
            logger.error(f"Failed to fetch Telegram MTProto {name}: {e}")

    await client.disconnect()
    return items


def collect_api(sources: list[dict]) -> list[dict]:
    """Fetch structured data from JSON APIs (e.g., Tech for Palestine)."""
    items = []
    now = _now_iso()

    for source in sources:
        name = source["name"]
        url = source["url"]
        logger.info(f"Fetching API: {name}")

        try:
            resp = httpx.get(url, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            # Store the entire API response as a single item
            body = json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data)

            items.append({
                "id": _make_id(url, body),
                "collected_at": now,
                "source_name": name,
                "source_type": source.get("type", "unknown"),
                "bias": source.get("bias", "unknown"),
                "channel": "api",
                "url": url,
                "title": f"{name} snapshot",
                "body": body if len(body) < 50000 else body[:50000],
                "published_at": now,
                "has_media": False,
                "media_urls": [],
                "digest_included": False,
                "confidence_score": None,
                "event_group_id": None,
                "geolocation": None,
                "satellite_verified": None,
            })

            logger.info(f"  {name}: fetched successfully")

        except Exception as e:
            logger.error(f"Failed to fetch API {name}: {e}")

    return items
