"""Processed-episode state — the idempotence backbone (spec §9).

An episode is marked processed only after its briefing email is sent, so a
failed run simply retries next morning; a successful run never re-processes
or double-sends. Keys are feed GUIDs with a title+date fallback (Episode.key).

Locally this is data/state.json; in production it lives in the PRIVATE repo
so fresh CI machines still know what's been done.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"processed": {}}


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def is_processed(state: dict, episode) -> bool:
    return episode.key in state["processed"]


def mark_processed(state: dict, episode) -> None:
    state["processed"][episode.key] = {
        "show": episode.show,
        "title": episode.title,
        "published": episode.published,
        "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --- First-sight seeding -----------------------------------------------------
# A feed's entire back catalogue is marked processed the first time we see it,
# so joining a new feed never triggers a mass backfill (4,300+ episodes across
# the roster). A deliberate backfill is a separate, manual decision (Phase 4).


def is_seeded(state: dict, feed_name: str) -> bool:
    return feed_name in state.setdefault("seeded_feeds", [])


def mark_seeded(state: dict, feed_name: str) -> None:
    state.setdefault("seeded_feeds", []).append(feed_name)


# --- Failure tracking (spec §9: make failure loud) ---------------------------


def record_feed_failure(state: dict, feed_name: str) -> int:
    """Count consecutive failed runs for a feed; returns the new count."""
    d = state.setdefault("feed_failures", {})
    d[feed_name] = d.get(feed_name, 0) + 1
    return d[feed_name]


def clear_feed_failure(state: dict, feed_name: str) -> None:
    state.setdefault("feed_failures", {}).pop(feed_name, None)


def record_episode_failure(state: dict, episode) -> int:
    """Count processing attempts for one episode; returns the new count.
    The caller gives up (marks processed) after the retry cap."""
    d = state.setdefault("episode_failures", {})
    d[episode.key] = d.get(episode.key, 0) + 1
    return d[episode.key]


# --- Email bookkeeping --------------------------------------------------------
# With two cron entries a morning can legitimately run twice; this lets the
# second run skip a redundant quiet-day email while real briefings always send.


def record_email_sent(state: dict) -> None:
    state["last_email_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


def hours_since_last_email(state: dict) -> float:
    last = state.get("last_email_at")
    if not last:
        return float("inf")
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    return delta.total_seconds() / 3600
