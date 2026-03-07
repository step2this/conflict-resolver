"""TinyDB storage with deduplication."""

import logging
from pathlib import Path

from tinydb import TinyDB, Query

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "items.json"


def get_db(path: Path = DB_PATH) -> TinyDB:
    path.parent.mkdir(parents=True, exist_ok=True)
    return TinyDB(path)


def dedupe_and_store(items: list[dict], db: TinyDB | None = None) -> list[dict]:
    """Store new items in TinyDB, skip duplicates. Returns list of newly inserted items."""
    if db is None:
        db = get_db()

    Item = Query()

    # Build a set of existing IDs for fast lookup
    existing_ids = {doc["id"] for doc in db.search(Item.id.exists())}

    new_items = []
    for item in items:
        if item["id"] in existing_ids:
            continue
        db.insert(item)
        existing_ids.add(item["id"])
        new_items.append(item)

    logger.info(f"Dedup: {len(items)} incoming, {len(new_items)} new, {len(items) - len(new_items)} duplicates")
    return new_items


def get_recent_items(db: TinyDB | None = None, limit: int = 500) -> list[dict]:
    """Get recent items from the database (for cached analysis re-runs)."""
    if db is None:
        db = get_db()
    all_items = db.all()
    # Sort by collected_at descending, return most recent
    all_items.sort(key=lambda x: x.get("collected_at", ""), reverse=True)
    return all_items[:limit]
