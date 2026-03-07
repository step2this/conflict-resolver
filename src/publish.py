"""Write digest markdown to MkDocs blog and build the site."""

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent / "docs" / "blog" / "posts"
PROJECT_ROOT = Path(__file__).parent.parent


def _edition_label() -> str:
    """Return 'am' or 'pm' based on current UTC hour."""
    hour = datetime.now(timezone.utc).hour
    return "am" if hour < 12 else "pm"


def write_digest(markdown: str, date: str | None = None, edition: str | None = None) -> Path:
    """Write digest markdown to docs/blog/posts/YYYY-MM-DD-edition.md with frontmatter."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if edition is None:
        edition = _edition_label()

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    slug = f"{date}-{edition}"
    post_path = DOCS_DIR / f"{slug}.md"

    edition_name = "Morning Edition" if edition == "am" else "Evening Edition"

    frontmatter = f"""---
date: {date}
slug: {slug}
---

"""
    post_path.write_text(frontmatter + markdown)
    logger.info(f"Wrote digest ({edition_name}) to {post_path}")
    return post_path


def build_site() -> bool:
    """Run mkdocs build."""
    try:
        result = subprocess.run(
            ["mkdocs", "build"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"mkdocs build failed: {result.stderr}")
            return False
        logger.info("mkdocs build succeeded")
        return True
    except Exception as e:
        logger.error(f"mkdocs build error: {e}")
        return False


def sync_to_s3(bucket: str = "conflict-digest") -> bool:
    """Sync built site to S3."""
    site_dir = PROJECT_ROOT / "site"
    try:
        result = subprocess.run(
            ["aws", "s3", "sync", str(site_dir), f"s3://{bucket}/", "--delete"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"S3 sync failed: {result.stderr}")
            return False
        logger.info(f"Synced to s3://{bucket}/")
        return True
    except Exception as e:
        logger.error(f"S3 sync error: {e}")
        return False
