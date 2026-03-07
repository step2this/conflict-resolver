"""Claude analysis pass — groups events, produces structured digest markdown."""

import logging
import os
from datetime import datetime, timezone

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_ITEMS_PER_CALL = 80

SYSTEM_PROMPT = """You are producing a structured conflict damage digest for a reader who \
consumes sources across all sides of the conflict and wants to draw their \
own conclusions.

You will receive a batch of raw items from the last 24 hours. Each item \
includes its source name, bias tag, and raw text.

Your task:

1. GROUP items that appear to describe the same event (same location, time, \
   and incident type). Assign each group an event ID.

2. For each event group, produce a structured entry:
   - CLAIM: What is claimed, in neutral language, stripped of all framing
   - SOURCES: Which sources report it, with their bias tags
   - CORROBORATION: Are any two editorially independent sources reporting it?
   - CONFLICT: Does any source contradict another? Note the contradiction.
   - MEDIA FLAG: Does any item include attached video or imagery? \
     (Flag as: HUMAN REVIEW NEEDED)
   - CONFIDENCE: [SINGLE SOURCE | MULTI-SOURCE SAME BIAS | MULTI-SOURCE \
     INDEPENDENT | CONFLICTING]

3. Surface the 5-10 highest-confidence events at the top of the digest.

4. List remaining events below in a secondary section.

Rules:
- Never say a claim is true or false
- Always attribute: "X claims...", "Y reports...", "Corroborated by..."
- Flag but do not resolve conflicts between sources
- Keep language dry and factual throughout
- If an item is clearly not about damage or military action, exclude it

Output format: structured markdown."""


def _format_items_for_prompt(items: list[dict]) -> str:
    """Format raw items into text for the Claude prompt."""
    parts = []
    for i, item in enumerate(items, 1):
        parts.append(f"--- ITEM {i} ---")
        parts.append(f"Source: {item.get('source_name', 'Unknown')}")
        parts.append(f"Bias: {item.get('bias', 'unknown')}")
        parts.append(f"Type: {item.get('source_type', 'unknown')}")
        parts.append(f"Published: {item.get('published_at', 'unknown')}")
        if item.get("title"):
            parts.append(f"Title: {item['title']}")
        if item.get("body"):
            # Truncate very long bodies
            body = item["body"][:2000] if len(item["body"]) > 2000 else item["body"]
            parts.append(f"Body: {body}")
        if item.get("has_media"):
            parts.append("Media: attached (HUMAN REVIEW NEEDED)")
        parts.append("")
    return "\n".join(parts)


def _chunk_items(items: list[dict], max_per_chunk: int = MAX_ITEMS_PER_CALL) -> list[list[dict]]:
    """Split items into chunks, grouped by source type to keep related items together."""
    if len(items) <= max_per_chunk:
        return [items]

    # Group by source_type
    by_type: dict[str, list[dict]] = {}
    for item in items:
        st = item.get("source_type", "unknown")
        by_type.setdefault(st, []).append(item)

    chunks = []
    current_chunk = []
    for source_type, type_items in by_type.items():
        for item in type_items:
            current_chunk.append(item)
            if len(current_chunk) >= max_per_chunk:
                chunks.append(current_chunk)
                current_chunk = []
    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def analyse(items: list[dict]) -> str:
    """Run Claude analysis on items and return digest markdown."""
    if not items:
        return "# Conflict Digest\n\nNo new items to analyse today."

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    chunks = _chunk_items(items)

    logger.info(f"Analysis: {len(items)} items in {len(chunks)} chunk(s)")

    digest_parts = []
    for i, chunk in enumerate(chunks, 1):
        logger.info(f"  Calling Claude for chunk {i}/{len(chunks)} ({len(chunk)} items)")

        formatted = _format_items_for_prompt(chunk)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        message = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Today's date: {today}\n\nHere are the raw items to analyse:\n\n{formatted}",
                }
            ],
        )

        digest_parts.append(message.content[0].text)

    if len(digest_parts) == 1:
        return digest_parts[0]

    # Multiple chunks: combine with section headers
    combined = []
    for i, part in enumerate(digest_parts, 1):
        if len(digest_parts) > 1:
            combined.append(f"\n## Batch {i}\n")
        combined.append(part)
    return "\n".join(combined)
