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
