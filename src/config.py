"""Load configuration (config.toml) and local secrets (.env).

Secrets are only ever read from environment variables so the same code works
locally (.env file, gitignored) and in GitHub Actions (encrypted Secrets).
"""

import tomllib
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    load_dotenv(ROOT / ".env")  # no-op if the file doesn't exist (e.g. in CI)
    with open(ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def data_dir(cfg: dict) -> Path:
    d = ROOT / cfg["storage"]["data_dir"]
    d.mkdir(parents=True, exist_ok=True)
    return d
