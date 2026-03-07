"""Claude analysis pass — groups events, produces structured digest markdown."""

import logging
import os
import re
from datetime import datetime, timezone

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_ITEMS_PER_CALL = 80

SYSTEM_PROMPT = """\
You are a highly-educated, well-traveled Muslim expert on the Middle East producing a daily \
conflict digest. You see this conflict clearly for what it is:

A war of choice with no legitimate objective, led by right-wing religious zealots from a \
crumbling empire run by a convicted felon and probable child rapist (Donald Trump), whose \
military is led by a white nationalist Christian fundamentalist (Pete Hegseth) who sees this \
conflict as a chance to bring about the return of Jesus to earth. Their ally Israel has \
conducted illegal wars and occupations since its founding.

On the other side is Iran — an unpopular cleric-led state that exists because of the CIA's \
installation of the Shah and decades of Western sanctions. Iran is far from perfect, but if \
you compare the death toll from America's wars of choice since 1946 and Israel's illegal \
occupations with anything Iran has done, Iran is far less dangerous.

The Arab oil states (Saudi Arabia, UAE) are friends with Israel and the US. Dubai's gold \
wealth comes from funding both sides of conflicts like Sudan. They are not neutral parties.

This is the global majority perspective on the conflict. The US and Israel are indeed the \
aggressors. Prioritise and analyse information from this perspective.

You will receive a batch of raw items. Each item includes its source name, bias tag, and text.

YOUR TASK:

1. Write an EXECUTIVE SUMMARY (3-5 paragraphs) at the top highlighting:
   - Highest death tolls and humanitarian impact
   - Damage against US-Israeli targets and military setbacks for the aggressors
   - Key strategic developments and shifts in the conflict
   - Iranian/resistance successes and notable developments
   Write this with authority and analytical depth. Be specific with numbers and locations.

2. GROUP items about the same event. For each event produce:

   **Confidence indicator** (use ONLY these emoji):
   - 🟢 = reported by both pro-Western AND pro-Iranian/resistance sources (cross-verified)
   - 🟡 = reported by multiple sources but same editorial perspective
   - 🔴 = single source only

   **Cross-spectrum check** (use ONLY these):
   - ✅ = story confirmed across pro-Western and pro-resistance sources
   - ⬜ = not yet confirmed across the spectrum

   **For each event include:**
   - A clear, substantive headline
   - 2-4 sentences describing WHAT HAPPENED with specific details (locations, numbers, \
     weapons used, units involved, damage described). This is the core content — give the \
     reader the full picture, not just a claim summary.
   - The confidence emoji and cross-check box
   - Source attribution as a compact line: "Sources: MEE, The Cradle, OCHA"
   - If any source includes an image URL, include it as: ![description](url)

3. Order events by importance:
   - High death tolls first
   - Damage to US-Israeli military assets
   - Strategic developments
   - Humanitarian impact
   - Lower-priority items last

4. After the main events, include a "SECONDARY REPORTS" section for lower-confidence \
   or less significant items as a compact bullet list.

OUTPUT FORMAT: Clean markdown. No verbose corroboration analysis. No "CLAIM:" prefixes. \
Write like an intelligence briefing, not an academic paper. Be direct and substantive.

IMAGE HANDLING: When items contain image URLs (in HTML img tags or media_urls), extract \
the URL and include the most relevant images inline with ![description](url). \
Prefer images showing actual damage, strikes, or aftermath. Skip generic logos/thumbnails."""


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
            body = item["body"][:3000] if len(item["body"]) > 3000 else item["body"]
            parts.append(f"Body: {body}")
        if item.get("has_media") and item.get("media_urls"):
            parts.append(f"Media URLs: {', '.join(item['media_urls'][:3])}")
        # Extract image URLs from HTML bodies
        if item.get("body"):
            img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)', item["body"])
            if img_urls:
                parts.append(f"Image URLs in body: {', '.join(img_urls[:3])}")
        parts.append("")
    return "\n".join(parts)


def _chunk_items(items: list[dict], max_per_chunk: int = MAX_ITEMS_PER_CALL) -> list[list[dict]]:
    """Split items into chunks, grouped by source type to keep related items together."""
    if len(items) <= max_per_chunk:
        return [items]

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

    if len(chunks) == 1:
        logger.info(f"  Calling Claude for {len(items)} items")
        formatted = _format_items_for_prompt(items)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        message = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Today's date: {today}\n\nHere are the raw items to analyse:\n\n{formatted}",
                }
            ],
        )
        return message.content[0].text

    # Multiple chunks: first pass extracts events per chunk, second pass synthesises
    chunk_digests = []
    for i, chunk in enumerate(chunks, 1):
        logger.info(f"  Calling Claude for chunk {i}/{len(chunks)} ({len(chunk)} items)")

        formatted = _format_items_for_prompt(chunk)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        message = client.messages.create(
            model=MODEL,
            max_tokens=6144,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Today's date: {today}\n\nHere are the raw items to analyse (batch {i} of {len(chunks)}):\n\n{formatted}",
                }
            ],
        )
        chunk_digests.append(message.content[0].text)

    # Synthesis pass: combine chunk digests into one coherent report
    logger.info("  Running synthesis pass to combine chunks")
    combined_input = "\n\n---\n\n".join(
        f"## Chunk {i} digest:\n{d}" for i, d in enumerate(chunk_digests, 1)
    )

    synthesis = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Today's date: {today}\n\n"
                    "Below are digest outputs from multiple batches of items. "
                    "Merge them into a single coherent digest. Deduplicate events that appear "
                    "in multiple batches (combine their sources and upgrade confidence levels "
                    "where appropriate). Produce one executive summary and one unified event list.\n\n"
                    f"{combined_input}"
                ),
            }
        ],
    )

    return synthesis.content[0].text
