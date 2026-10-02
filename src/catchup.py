"""One-off catch-up: summarise a recovered backlog and email it SEPARATELY.

Why this exists. When transcription breaks, the daily briefing keeps sending
(news and in-print still work) while episodes pile up and eventually hit the
retry cap. Once their transcripts have been recovered — normally via
backfill.yml, which transcribes in parallel chunks — the summaries still need
to reach the reader. But NOT in a "Daily podcast summary" email: that subject
is auto-forwarded to his manager, and a catch-up is for him alone.

So this script:
  - sends under a DIFFERENT brand and subject (nothing matching the forward rule)
  - never touches last_email_at, so the daily briefing is unaffected either way
  - marks episodes processed only AFTER the email actually sends
  - caches like the main pipeline: re-running skips anything already summarised

Whisper is never invoked here. Run it once the transcripts exist; episodes
whose transcript is still missing are reported and left alone.

    ARCHIVE_DIR=../podcast-archive .venv/Scripts/python.exe src/catchup.py

LOG DISCIPLINE (spec §7): counts, titles and dates only — never transcript text.
"""

import argparse
import json
import os
import sys

import render
from config import archive_dir, load_config
from download import slug
from emailer import send_email
from feeds import fetch_episodes
from index import append_index_line
from render import build_stories, render_briefing
from state import load_state, mark_processed, save_state
from summarise import cluster_items, select_top_line, summarise

BRAND = "Archive catch-up"  # deliberately NOT the daily brand — see module docstring

MONTHS = (
    "January February March April May June "
    "July August September October November December"
).split()


def _pretty(iso: str) -> str:
    y, m, d = (int(p) for p in iso.split("-"))
    return f"{d} {MONTHS[m - 1]}"


def span_label(dates: list[str]) -> str:
    """'30 September to 2 October 2026' from the episodes actually recovered."""
    lo, hi = min(dates), max(dates)
    year = hi.split("-")[0]
    return f"{_pretty(lo)} to {_pretty(hi)} {year}" if lo != hi else f"{_pretty(lo)} {year}"


def transcript_path(archive, ep):
    return archive / "transcripts" / slug(ep.show) / f"{ep.published}_{ep.stamp}.transcript.json"


def summarise_existing(ep, cfg, archive) -> dict | None:
    """Summarise from the archived transcript. None if it isn't there yet.

    Mirrors run.process_episode's caching: an existing items.json is reused, so
    a second pass after a quota stop costs nothing for work already done.
    """
    tpath = transcript_path(archive, ep)
    if not tpath.exists():
        return None
    transcript = json.loads(tpath.read_text(encoding="utf-8"))

    ipath = tpath.with_suffix("").with_suffix(".items.json")
    if ipath.exists():
        cached = json.loads(ipath.read_text(encoding="utf-8"))
        result = cached if isinstance(cached, dict) else {"items": cached, "guests": [], "topics": []}
        print(f"[catchup] already summarised: {ipath.name}")
    else:
        result = summarise(transcript, cfg["gemini"])
        ipath.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"transcript": transcript, **result}


def delivered_stamps(archive) -> str:
    """index.md as raw text, to test episode stamps against.

    This file IS the delivery ledger: append_index_line runs only after a
    briefing has actually been emailed, and is idempotent on the stamp. So a
    missing stamp means 'never reached the reader', which is the only thing
    that qualifies an episode for a catch-up.
    """
    path = archive / "index.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def recovery_set(cfg, state, archive, since: str) -> tuple[list, list[str]]:
    """Episodes the pipeline failed on AND never delivered, from the feeds.

    Two conditions, both needed:

      - a recorded failure, which bounds the set to episodes the pipeline
        actually choked on rather than the whole archive; and
      - no index.md line, i.e. never emailed.

    The second is essential. state['episode_failures'] is append-only — an
    episode that failed once and succeeded next run keeps its counter forever,
    so the raw failure list contains long-delivered episodes going back months.
    Emailing those would re-send things the reader has already read.

    `since` is a final guard: a catch-up should never reach back further than
    the break it is recovering from.
    """
    wanted = set(state.get("episode_failures", {}))
    if not wanted:
        return [], []
    index_txt = delivered_stamps(archive)
    found, notes = [], []
    for feed_cfg in cfg["feeds"]:
        try:
            episodes = fetch_episodes(feed_cfg, cfg["filtering"])
        except Exception as e:
            notes.append(f"Feed unreachable, may have missed episodes: {feed_cfg['name']}")
            print(f"[catchup] {feed_cfg['name']} FAILED ({type(e).__name__}) - skipping feed")
            continue
        found.extend(
            ep
            for ep in episodes
            if ep.key in wanted and ep.published >= since and ep.stamp not in index_txt
        )

    stale = len(wanted) - len(found)
    if stale > 0:
        # Mostly counters left on episodes that failed once, succeeded next run
        # and were delivered normally; some have aged out of their feed window.
        print(f"[catchup] ignoring {stale} failure record(s) already delivered or out of window")
    found.sort(key=lambda e: (e.published, e.show))
    return found, notes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-episodes", type=int, default=0,
        help="cap how many to summarise this pass (0 = all). Gemini's free tier is "
        "20 requests per day PER MODEL, so a very large backlog may need two passes; "
        "anything already summarised is cached and free the second time.",
    )
    ap.add_argument("--dry-run", action="store_true", help="report what would be sent, email nothing")
    ap.add_argument(
        "--claim", action="store_true",
        help="mark the recovery set processed and exit, emailing nothing. Run this as "
        "soon as the transcripts land: otherwise the next daily briefing sees 24 "
        "unprocessed episodes with transcripts sitting ready, summarises the lot, and "
        "sends the whole backlog in the email that gets auto-forwarded. Failure "
        "records are kept, so the catch-up can still find them afterwards.",
    )
    ap.add_argument(
        "--since", default="2026-09-29",
        help="ignore failures published before this ISO date. Guard against a catch-up "
        "reaching further back than the break it is recovering (default: the day "
        "before the PyAV break of 2026-09-30).",
    )
    args = ap.parse_args()

    cfg = load_config()
    archive = archive_dir(cfg)
    state_file = archive / "state.json"
    state = load_state(state_file)

    eps, footer = recovery_set(cfg, state, archive, args.since)
    if not eps:
        print("[catchup] nothing to recover - no recorded episode failures")
        return
    print(f"[catchup] {len(eps)} episode(s) in the recovery set")

    if args.claim:
        # Take the backlog out of the daily pipeline's sight WITHOUT delivering
        # it. mark_processed only touches state['processed']; the failure record
        # and the absent index.md line are what the catch-up keys off, so both
        # survive and a later pass still finds these episodes.
        for ep in eps:
            mark_processed(state, ep)
        save_state(state, state_file)
        print(f"[catchup] claimed {len(eps)} episode(s) - the daily briefing will now skip them")
        print("[catchup] commit and push the archive, then run the catch-up when ready")
        return

    pending = [ep for ep in eps if not transcript_path(archive, ep).exists()]
    if pending:
        shows = ", ".join(sorted({ep.show for ep in pending}))
        print(f"[catchup] {len(pending)} still have no transcript ({shows})")
        print("[catchup] run backfill.yml first, then pull the archive and re-run this")
        footer.append(f"{len(pending)} episode(s) had no transcript yet and were left for a later pass")

    blocked = {ep.key for ep in pending}
    todo = [ep for ep in eps if ep.key not in blocked]
    if args.max_episodes:
        todo = todo[: args.max_episodes]
    if not todo:
        sys.exit("[catchup] no transcripts available yet - nothing to summarise")

    recovered, lost = [], []
    for ep in todo:
        try:
            result = summarise_existing(ep, cfg, archive)
            sig = sum(1 for i in result["items"] if i["tier"] == "significant")
            print(f"[catchup] '{ep.title}': {len(result['items'])} item(s), {sig} significant")
            recovered.append((ep, result))
        except Exception as e:
            print(f"[catchup] FAILED to summarise '{ep.title}' ({type(e).__name__})")
            lost.append(ep)
    for ep in lost:
        footer.append(f"Couldn't summarise “{ep.title}” ({ep.show}) - still pending")

    if not recovered:
        sys.exit("[catchup] nothing summarised successfully - sending no email")

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("[config] GEMINI_API_KEY is not set")
    missing = [v for v in ("BRIEFING_FROM", "BRIEFING_TO", "GMAIL_APP_PASSWORD") if not os.environ.get(v)]
    if missing and not args.dry_run:
        sys.exit(f"[email] missing in .env: {', '.join(missing)}")

    episodes_data = [result for _, result in recovered]
    flat = [(item, ep["transcript"]) for ep in episodes_data for item in ep["items"]]
    groups = cluster_items(flat, cfg["gemini"]) if flat else []
    stories = build_stories(episodes_data, groups)
    top = select_top_line(stories, cfg["gemini"]) if stories else []

    label = f"{span_label([ep.published for ep, _ in recovered])} ({len(recovered)} episodes)"
    footer.append(
        "One-off recovery of the episodes lost to the transcription break of "
        "30 September to 2 October. Normal service resumes with the next daily email."
    )

    # Swap the brand for this send only. The daily subject is what triggers the
    # auto-forward to his manager; a catch-up is for him alone.
    render.BRAND = BRAND
    subject, text, html = render_briefing(label, stories, top=top, footer_notes=footer)
    print(f"[catchup] {len(stories)} story/stories, top line: {len(top)}")
    print(f"[catchup] subject: {subject}")

    if args.dry_run:
        print("[catchup] dry run - no email sent, no state changed")
        return

    send_email(subject, text, html, cfg["email"])
    print(f"[catchup] emailed {len(recovered)} episode(s)")

    # Only now are they done. Deliberately NOT record_email_sent(): this send is
    # out of band and must never suppress a daily briefing.
    failures = state.setdefault("episode_failures", {})
    for ep, result in recovered:
        mark_processed(state, ep)
        append_index_line(archive, ep, result["guests"], result["topics"])
        failures.pop(ep.key, None)
    save_state(state, state_file)
    print(f"[catchup] state saved ({len(failures)} failure record(s) left)")
    print("[catchup] commit and push the archive to keep the transcripts and state")


if __name__ == "__main__":
    main()
