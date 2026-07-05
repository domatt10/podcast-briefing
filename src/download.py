"""Download episode audio into the local data directory (gitignored)."""

import re
from pathlib import Path

import requests


def slug(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_len]


def download_audio(episode, data_dir: Path) -> Path:
    """Stream the episode audio to disk; returns the file path.

    Filename embeds show, date and a hash of the dedupe key, so re-downloads
    of the same episode land on the same path.
    """
    dest = data_dir / f"{slug(episode.show)}_{episode.published}_{episode.stamp}.mp3"
    if dest.exists() and dest.stat().st_size > 0:
        return dest  # already downloaded — idempotence starts here

    resp = requests.get(
        episode.audio_url,
        stream=True,
        timeout=120,
        headers={"User-Agent": "podcast-briefing/0.1 (personal, single-user)"},
    )
    resp.raise_for_status()
    tmp = dest.with_suffix(".part")
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest
