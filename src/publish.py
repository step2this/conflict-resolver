"""Write digest markdown to MkDocs blog and build the site."""

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).parent.parent / "docs" / "blog" / "posts"
PROJECT_ROOT = Path(__file__).parent.parent


def write_digest(markdown: str, date: str | None = None) -> Path:
    """Write digest markdown to docs/blog/posts/YYYY-MM-DD.md with frontmatter."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    post_path = DOCS_DIR / f"{date}.md"

    frontmatter = f"""---
date: {date}
---

"""
    post_path.write_text(frontmatter + markdown)
    logger.info(f"Wrote digest to {post_path}")
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
