from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from hn_job_agent.config import Settings

logger = logging.getLogger(__name__)

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"
FIREBASE_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


@dataclass
class Posting:
    id: str
    author: str
    posted_at: datetime
    text: str
    hn_url: str


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    # HN uses <p> tags between paragraphs and <a href>...</a> for links.
    # Preserve URLs by replacing <a href="X">Y</a> with "Y (X)".
    raw = re.sub(
        r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        lambda m: f"{m.group(2)} ({m.group(1)})",
        raw,
        flags=re.IGNORECASE | re.DOTALL,
    )
    raw = raw.replace("<p>", "\n\n").replace("</p>", "")
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


async def _find_latest_thread_id(client: httpx.AsyncClient, settings: Settings) -> int:
    params = {
        "tags": f"story,author_{settings.hn_hiring_user}",
        "query": "Ask HN: Who is hiring",
        "hitsPerPage": "20",
    }
    resp = await client.get(ALGOLIA_URL, params=params)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    # Filter to only "Who is hiring" stories (exclude "Who wants to be hired" and "Freelancer").
    hits = [
        h for h in hits
        if "who is hiring" in (h.get("title") or "").lower()
    ]
    if not hits:
        raise RuntimeError("no 'Who is hiring' story found on Algolia")
    hits.sort(key=lambda h: h.get("created_at_i", 0), reverse=True)
    story_id = int(hits[0]["objectID"])
    logger.info(
        "latest_hiring_thread id=%s title=%r",
        story_id,
        hits[0].get("title"),
    )
    return story_id


async def _fetch_item(client: httpx.AsyncClient, item_id: int) -> dict | None:
    try:
        resp = await client.get(FIREBASE_ITEM_URL.format(id=item_id))
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("hn_item_fetch_failed id=%s error=%s", item_id, exc)
        return None


async def fetch_latest_hiring_postings(
    client: httpx.AsyncClient, settings: Settings
) -> list[Posting]:
    story_id = await _find_latest_thread_id(client, settings)
    story = await _fetch_item(client, story_id)
    if not story:
        return []
    kids = (story.get("kids") or [])[: settings.max_comments]
    logger.info("top_level_comments=%d", len(kids))

    sem = asyncio.Semaphore(20)

    async def _bounded(kid: int) -> dict | None:
        async with sem:
            return await _fetch_item(client, kid)

    raw_items = await asyncio.gather(*[_bounded(k) for k in kids])

    postings: list[Posting] = []
    for item in raw_items:
        if not item or item.get("deleted") or item.get("dead"):
            continue
        if not item.get("text"):
            continue
        postings.append(
            Posting(
                id=str(item["id"]),
                author=item.get("by", ""),
                posted_at=datetime.fromtimestamp(
                    item.get("time", 0), tz=timezone.utc
                ),
                text=_strip_html(item["text"]),
                hn_url=f"https://news.ycombinator.com/item?id={item['id']}",
            )
        )

    logger.info("postings_loaded=%d", len(postings))
    return postings
