"""Orchestrator — runs the full conflict digest pipeline."""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")

from src.collect import (
    collect_api,
    collect_rss,
    collect_telegram_mtproto,
    collect_telegram_public,
    load_sources,
)
from src.dedupe import dedupe_and_store, get_db, get_recent_items
from src.analyse import analyse
from src.publish import build_site, sync_to_s3, write_digest

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def run_collectors(sources: dict, use_mtproto: bool = False) -> list[dict]:
    """Run all collectors and return combined items."""
    all_items = []

    # RSS
    if "rss" in sources:
        all_items.extend(collect_rss(sources["rss"]))

    # Telegram
    if "telegram" in sources:
        if use_mtproto:
            api_id = os.environ.get("TELEGRAM_API_ID")
            api_hash = os.environ.get("TELEGRAM_API_HASH")
            if api_id and api_hash:
                tg_items = asyncio.run(
                    collect_telegram_mtproto(
                        sources["telegram"], int(api_id), api_hash
                    )
                )
                all_items.extend(tg_items)
            else:
                logger.warning("TELEGRAM_API_ID/HASH not set, falling back to public scrape")
                all_items.extend(collect_telegram_public(sources["telegram"]))
        else:
            all_items.extend(collect_telegram_public(sources["telegram"]))

    # APIs
    if "api" in sources:
        all_items.extend(collect_api(sources["api"]))

    return all_items


def main():
    parser = argparse.ArgumentParser(description="Conflict Digest pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Collect and store only, skip analysis and publishing")
    parser.add_argument("--analyse-cached", action="store_true", help="Re-analyse stored items (skip collection)")
    parser.add_argument("--no-s3", action="store_true", help="Skip S3 sync")
    parser.add_argument("--mtproto", action="store_true", help="Use Telethon MTProto for Telegram")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)
    logger.info("=== Conflict Digest Pipeline ===")

    db = get_db()

    if args.analyse_cached:
        # Re-run analysis on stored items
        logger.info("Using cached items from database")
        new_items = get_recent_items(db)
        logger.info(f"Loaded {len(new_items)} recent items from DB")
    else:
        # Collect fresh items
        sources = load_sources()
        all_items = run_collectors(sources, use_mtproto=args.mtproto)
        logger.info(f"Collected {len(all_items)} total items")

        # Deduplicate and store
        new_items = dedupe_and_store(all_items, db)

    if args.dry_run:
        logger.info("Dry run — skipping analysis and publishing")
        return

    if not new_items:
        logger.info("No new items to analyse")
        return

    # Claude analysis
    digest_md = analyse(new_items)

    # Write digest post
    post_path = write_digest(digest_md)
    logger.info(f"Digest written to {post_path}")

    # Build site
    if not build_site():
        logger.error("Site build failed, skipping S3 sync")
        return

    # S3 sync
    if not args.no_s3:
        sync_to_s3()
    else:
        logger.info("Skipping S3 sync (--no-s3)")

    logger.info("=== Pipeline complete ===")


if __name__ == "__main__":
    main()
