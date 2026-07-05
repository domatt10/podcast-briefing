"""Fetch podcast RSS feeds and turn entries into Episode objects.

The metadata captured here is what later gets code-stamped onto every briefing
item (spec §7): the model is never trusted to know which show or episode a
quote came from.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser


@dataclass
class Episode:
    show: str
    title: str
    published: str  # ISO date, e.g. "2026-07-02"
    audio_url: str
    guid: str | None
    duration_secs: int | None
    author: str  # show/episode author from the feed (hosts, typically)
    summary: str  # the feed's own episode description — guest names often live here

    @property
    def key(self) -> str:
        """Dedupe key for the processed-episode state. GUID when the feed
        provides one; title+date fallback because GUIDs can rotate (spec App. B)."""
        return self.guid or f"{self.show}|{self.title}|{self.published}"


def _parse_duration(raw) -> int | None:
    """itunes:duration arrives as plain seconds ('1543') or 'HH:MM:SS'."""
    if not raw:
        return None
    raw = str(raw).strip()
    if ":" in raw:
        secs = 0
        for part in raw.split(":"):
            secs = secs * 60 + int(part)
        return secs
    return int(raw) if raw.isdigit() else None


def _audio_url(entry) -> str | None:
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("audio") or enc.get("href", "").endswith(".mp3"):
            return enc.get("href")
    return None


def fetch_episodes(feed_cfg: dict) -> list[Episode]:
    """Fetch one feed and return its episodes, newest first.

    Entries without an audio enclosure are skipped (they aren't episodes).
    """
    parsed = feedparser.parse(feed_cfg["url"])
    if parsed.bozo and not parsed.entries:
        raise RuntimeError(f"Feed unreadable: {feed_cfg['name']} ({parsed.bozo_exception})")

    show = feed_cfg["name"]
    episodes = []
    for entry in parsed.entries:
        audio = _audio_url(entry)
        if not audio:
            continue
        published = ""
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).date().isoformat()
        episodes.append(
            Episode(
                show=show,
                title=entry.get("title", "(untitled)").strip(),
                published=published,
                audio_url=audio,
                guid=entry.get("id"),
                duration_secs=_parse_duration(entry.get("itunes_duration")),
                author=entry.get("author") or parsed.feed.get("author", ""),
                summary=entry.get("summary", ""),
            )
        )

    episodes.sort(key=lambda e: e.published, reverse=True)
    return episodes
