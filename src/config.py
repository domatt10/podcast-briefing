"""Load configuration (config.toml) and local secrets (.env).

Secrets are only ever read from environment variables so the same code works
locally (.env file, gitignored) and in GitHub Actions (encrypted Secrets).
"""

import os
import tomllib
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    load_dotenv(ROOT / ".env")  # no-op if the file doesn't exist (e.g. in CI)
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def data_dir(cfg: dict) -> Path:
    """Scratch space: downloaded audio. Never archived, never committed."""
    d = ROOT / cfg["storage"]["data_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def archive_dir(cfg: dict) -> Path:
    """Durable home of transcripts + processed-episode state.

    In CI, ARCHIVE_DIR points at the checked-out PRIVATE repo; locally it's
    unset and falls back to data/ (same gitignored folder as the audio).
    """
    d = Path(os.environ.get("ARCHIVE_DIR") or data_dir(cfg))
    d.mkdir(parents=True, exist_ok=True)
    return d
