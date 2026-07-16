"""Politico backfill: same fetch as the daily pipeline, wider window.

Run locally: ARCHIVE_DIR=<archive clone> python src/politico_backfill.py --days 90
Idempotent — existing files are skipped, so any window is safe to re-run.
"""

import argparse

from config import archive_dir, load_config
from politico import fetch_politico


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    cfg = load_config()
    fetch_politico(cfg, archive_dir(cfg), days=args.days)


if __name__ == "__main__":
    main()
