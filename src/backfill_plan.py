"""Backfill planner (agent brief C).

Inventories the last N days across every feed, drops episodes whose
transcripts already exist in the archive, and splits the rest into
duration-balanced chunks for parallel transcription. Writes plan.json and,
in CI, the matrix outputs.
"""

import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

from config import load_config
from download import slug
from feeds import fetch_episodes

FALLBACK_SECS = 2400  # assume ~40 min when a feed omits duration


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=0, help="cap total episodes (dry runs); 0 = no cap")
    ap.add_argument("--chunks", type=int, default=20)
    ap.add_argument("--archive", required=True, help="path to the archive clone")
    ap.add_argument("--out", default="plan.json")
    args = ap.parse_args()

    cfg = load_config()
    archive = Path(args.archive)
    cutoff = (date.today() - timedelta(days=args.days)).isoformat()

    todo = []
    for feed_cfg in cfg["feeds"]:
        try:
            episodes = fetch_episodes(feed_cfg, cfg["filtering"])
        except Exception as e:
            print(f"[plan] {feed_cfg['name']} FAILED ({type(e).__name__}) - skipping feed")
            continue
        in_window = [e for e in episodes if e.published >= cutoff]
        new = [
            e
            for e in in_window
            if not (archive / "transcripts" / slug(e.show) / f"{e.published}_{e.stamp}.transcript.json").exists()
        ]
        print(f"[plan] {feed_cfg['name']}: {len(in_window)} in window, {len(new)} to transcribe")
        todo.extend(new)

    todo.sort(key=lambda e: e.published)
    if args.limit:
        todo = todo[: args.limit]

    # Greedy balance: biggest episodes first, each into the lightest chunk.
    n_chunks = max(1, min(args.chunks, len(todo)))
    chunks: list[list[dict]] = [[] for _ in range(n_chunks)]
    loads = [0] * n_chunks
    for ep in sorted(todo, key=lambda e: -(e.duration_secs or FALLBACK_SECS)):
        i = loads.index(min(loads))
        chunks[i].append(
            {
                "show": ep.show,
                "title": ep.title,
                "published": ep.published,
                "audio_url": ep.audio_url,
                "guid": ep.guid,
                "duration_secs": ep.duration_secs,
                "author": ep.author,
                "summary": "",
            }
        )
        loads[i] += ep.duration_secs or FALLBACK_SECS

    Path(args.out).write_text(json.dumps({"chunks": chunks}, ensure_ascii=False, indent=1), encoding="utf-8")
    total_h = sum(e.duration_secs or FALLBACK_SECS for e in todo) / 3600
    print(f"[plan] TOTAL: {len(todo)} episode(s), ~{total_h:.1f}h audio, {n_chunks} chunk(s)")

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"chunk_ids={json.dumps(list(range(n_chunks)))}\n")
            f.write(f"has_work={'true' if todo else 'false'}\n")


if __name__ == "__main__":
    main()
