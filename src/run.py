"""Pipeline orchestrator.

Reliability model (spec §9): degrade gracefully — one broken feed or episode
never sinks the run; be idempotent — the state file governs everything; fail
loud — problems surface in the briefing footer and the Healthchecks pings,
never silently.

LOG DISCIPLINE (spec §7): this repo's Actions logs are public. Print feed
metadata (titles, dates, counts, durations) only — never transcript text,
quotes, or briefing content.
"""

import argparse
import json
import os
import sys
from datetime import date

from config import archive_dir, data_dir, load_config
from download import download_audio, slug
from emailer import send_email
from feeds import fetch_episodes
from news import fetch_news
from render import render_briefing, render_fallback, render_quiet
from state import (
    clear_feed_failure,
    hours_since_last_email,
    is_processed,
    is_seeded,
    load_state,
    mark_processed,
    mark_seeded,
    record_email_sent,
    record_episode_failure,
    record_feed_failure,
    save_state,
)
from summarise import select_top_line, summarise
from transcribe import ensure_readable, transcribe

EPISODE_RETRY_CAP = 3


def gather_new_episodes(cfg, state) -> tuple[list, list[str]]:
    """Check every feed independently; returns (new episodes, footer notes).

    A feed seen for the first time has its whole back catalogue marked
    processed (seeding) — joining a feed must never trigger a mass backfill.
    """
    new, footer = [], []
    for feed_cfg in cfg["feeds"]:
        name = feed_cfg["name"]
        try:
            episodes = fetch_episodes(feed_cfg, cfg["filtering"])
        except Exception as e:
            runs = record_feed_failure(state, name)
            print(f"[feeds] FAILED: {name} ({type(e).__name__}) - {runs} run(s) in a row")
            if runs >= cfg["filtering"]["flag_feed_after_failures"]:
                footer.append(f"Feed unreachable {runs} runs in a row: {name}")
            continue
        clear_feed_failure(state, name)

        if not is_seeded(state, name):
            for ep in episodes:
                mark_processed(state, ep)
            mark_seeded(state, name)
            print(f"[feeds] {name}: first sight - seeded {len(episodes)} existing episodes")
            continue

        fresh = [ep for ep in episodes if not is_processed(state, ep)]
        if fresh:
            print(f"[feeds] {name}: {len(fresh)} new episode(s)")
        new.extend(fresh)
    return new, footer


def process_episode(ep, cfg, archive, scratch, whisper_model) -> dict:
    """One episode, end to end: download → transcribe → summarise.
    Each stage skips itself if its output already exists (idempotence)."""
    audio = download_audio(ep, scratch)
    print(f"[download] {audio.name} ({audio.stat().st_size / (1 << 20):.1f} MB)")

    tpath = archive / "transcripts" / slug(ep.show) / f"{ep.published}_{ep.stamp}.transcript.json"
    transcribe(audio, ep, cfg["whisper"], tpath, model_name=whisper_model)
    ensure_readable(tpath)  # markdown companion for humans + future archive agents
    transcript = json.loads(tpath.read_text(encoding="utf-8"))

    ipath = tpath.with_suffix("").with_suffix(".items.json")
    if ipath.exists():
        items = json.loads(ipath.read_text(encoding="utf-8"))
        print(f"[summarise] already done: {ipath.name}")
    else:
        items = summarise(transcript, cfg["gemini"])
        ipath.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    sig = sum(1 for i in items if i["tier"] == "significant")
    print(f"[summarise] '{ep.title}': {len(items)} item(s), {sig} significant")
    return {"transcript": transcript, "items": items}


def transcript_url(cfg, ep) -> str | None:
    base = cfg["storage"].get("archive_repo_url", "").rstrip("/")
    if not base:
        return None
    return f"{base}/blob/main/transcripts/{slug(ep.show)}/{ep.published}_{ep.stamp}.transcript.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--whisper-model",
        help="override config.toml whisper model (e.g. 'small' for fast local tests)",
    )
    args = ap.parse_args()

    cfg = load_config()
    archive = archive_dir(cfg)
    scratch = data_dir(cfg)
    state_file = archive / "state.json"
    state = load_state(state_file)

    new_eps, footer = gather_new_episodes(cfg, state)
    print(f"[pipeline] {len(new_eps)} new episode(s) to process")

    briefed, failed = [], []
    for ep in new_eps:
        try:
            briefed.append((ep, process_episode(ep, cfg, archive, scratch, args.whisper_model)))
        except Exception as e:
            tries = record_episode_failure(state, ep)
            print(f"[pipeline] FAILED '{ep.title}' ({type(e).__name__}) - attempt {tries}")
            if tries >= EPISODE_RETRY_CAP:
                mark_processed(state, ep)
                footer.append(f"Gave up on “{ep.title}” ({ep.show}) after {tries} attempts")
            else:
                failed.append(ep)

    # News layer (agent brief A.1) — archive-only, never fatal to the briefing.
    try:
        n_news = fetch_news(cfg, archive)
        print(f"[news] {n_news} new stor{'y' if n_news == 1 else 'ies'} saved")
    except Exception as e:
        print(f"[news] stage failed ({type(e).__name__}) - continuing without news")
        footer.append("News fetch failed this run")

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("[config] GEMINI_API_KEY is not set")
    missing = [v for v in ("BRIEFING_FROM", "BRIEFING_TO", "GMAIL_APP_PASSWORD") if not os.environ.get(v)]
    if missing:
        sys.exit(f"[email] missing in .env: {', '.join(missing)}")

    today = date.today()
    date_label = f"{today:%A} {today.day} {today:%B %Y}"

    for ep in failed:
        footer.append(f"Couldn't process “{ep.title}” ({ep.show}) - will retry next run")

    if briefed:
        episodes_data = [result for _, result in briefed]
        top = select_top_line(episodes_data, cfg["gemini"])
        print(f"[render] top line: {len(top)} item(s)")
        subject, text, html = render_briefing(date_label, episodes_data, top=top, footer_notes=footer)
    elif failed:
        subject, text, html = render_fallback(
            date_label, [(ep, transcript_url(cfg, ep)) for ep in failed], footer
        )
    elif (
        cfg["behaviour"]["quiet_day_email"]
        and hours_since_last_email(state) >= cfg["behaviour"]["quiet_suppress_hours"]
    ):
        subject, text, html = render_quiet(date_label, footer)
    else:
        save_state(state, state_file)
        print("[email] quiet day (or recent email exists) - skipping email")
        return

    send_email(subject, text, html, cfg["email"])
    record_email_sent(state)

    # Only after a successful send do briefed episodes count as done.
    for ep, _ in briefed:
        mark_processed(state, ep)
    save_state(state, state_file)
    print(f"[state] saved ({len(state['processed'])} processed total)")


if __name__ == "__main__":
    main()
