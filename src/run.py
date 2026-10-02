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
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from config import archive_dir, data_dir, load_config
from download import download_audio, slug
from emailer import send_email
from feeds import fetch_episodes
from in_print import fetch_in_print
from index import append_index_line
from news import fetch_news
from politico import fetch_politico
from render import build_stories, render_briefing, render_fallback, render_quiet
from state import (
    clear_episode_failure,
    clear_feed_failure,
    is_processed,
    is_seeded,
    load_state,
    mark_processed,
    mark_seeded,
    record_email_sent,
    record_episode_failure,
    record_feed_failure,
    save_state,
    sent_email_today,
)
from summarise import cluster_items, select_top_line, summarise
from transcribe import ensure_readable, transcribe

EPISODE_RETRY_CAP = 3


def is_total_failure(n_new: int, n_briefed: int, n_failed: int, n_gave_up: int) -> bool:
    """True when there was podcast work to do and none of it survived.

    Not 'some episodes failed' — that is normal and the footer covers it. This
    is the shape of a systemic break: a dependency, the API, the audio host.
    A quiet day (no new episodes) is healthy, and a day where everything was
    deferred by the time budget is healthy too — the work is banked, not lost.
    """
    return bool(n_new) and not n_briefed and bool(n_failed or n_gave_up)


def _innermost(exc: BaseException) -> str:
    """'file.py:123' for the deepest frame in the traceback, or '?'.

    Deliberately location only — never the exception message, which for a
    Gemini error can echo back the prompt, and the prompt contains transcript
    text. These logs are public (spec §7).
    """
    tb, where = exc.__traceback__, "?"
    while tb:
        where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}"
        tb = tb.tb_next
    return where


def write_status(path: str | None, **fields) -> None:
    """Machine-readable outcome for CI to inspect AFTER the archive push.

    Why a file and not an exit code: exiting non-zero from this script skips
    the workflow's push step, so state.json would never persist and the next
    run would re-process and re-email everything (that is how 2026-07-29
    produced two briefings). The workflow reads this instead and fails the job
    once the push is safely done. A missing file means 'nothing to report'.
    """
    if not path:
        return
    Path(path).write_text(json.dumps(fields, indent=1), encoding="utf-8")


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
        cached = json.loads(ipath.read_text(encoding="utf-8"))
        # Files from before the guests/topics fields are a bare item list.
        result = cached if isinstance(cached, dict) else {"items": cached, "guests": [], "topics": []}
        print(f"[summarise] already done: {ipath.name}")
    else:
        result = summarise(transcript, cfg["gemini"])
        ipath.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    items = result["items"]
    sig = sum(1 for i in items if i["tier"] == "significant")
    print(f"[summarise] '{ep.title}': {len(items)} item(s), {sig} significant")
    return {"transcript": transcript, **result}


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
    ap.add_argument(
        "--max-minutes",
        type=int,
        default=210,
        help="stop STARTING new episodes past this; send what's done and leave the "
        "rest for tomorrow. Keeps a heavy morning inside the job timeout (300 min) "
        "with room for the episode in flight, the email and the archive push.",
    )
    ap.add_argument(
        "--status-file",
        help="write a JSON outcome summary here for CI to check after the push",
    )
    args = ap.parse_args()
    started = time.time()

    cfg = load_config()
    archive = archive_dir(cfg)
    scratch = data_dir(cfg)
    state_file = archive / "state.json"
    state = load_state(state_file)

    # The backup trigger fires hours after the primary has already delivered.
    # Bail out before doing an hour of work the one-email gate would discard.
    if sent_email_today(state):
        print("[pipeline] today's briefing already sent - nothing to do")
        return

    new_eps, footer = gather_new_episodes(cfg, state)
    print(f"[pipeline] {len(new_eps)} new episode(s) to process")

    briefed, failed, deferred, gave_up = [], [], [], []
    for ep in new_eps:
        # TIME BUDGET. Transcription runs at ~2x realtime, so a 70-minute
        # episode costs 35 minutes; a heavy morning can exceed the job timeout.
        # Before this existed, a timed-out run banked NOTHING (state is only
        # saved after a successful send), so its episodes rolled into the next
        # day and the backlog compounded: 7 -> 13 -> 16 and stuck, three days
        # with no briefing (2026-09-11 to 09-13). Now we stop starting new
        # episodes at the budget, send what we have, and leave the rest for
        # tomorrow — the same ratchet the backfill uses.
        if (time.time() - started) / 60 > args.max_minutes:
            deferred.append(ep)
            continue
        try:
            briefed.append((ep, process_episode(ep, cfg, archive, scratch, args.whisper_model)))
            clear_episode_failure(state, ep)
        except Exception as e:
            tries = record_episode_failure(state, ep)
            # Log WHERE it broke, not just the type. A filename and line number
            # carry no transcript text, so this stays inside the public-log
            # rule — and it is the difference between diagnosing a dependency
            # break in minutes and bisecting pip output for an afternoon.
            print(
                f"[pipeline] FAILED '{ep.title}' "
                f"({type(e).__name__} at {_innermost(e)}) - attempt {tries}"
            )
            if tries >= EPISODE_RETRY_CAP:
                mark_processed(state, ep)
                gave_up.append(ep)
                footer.append(f"Gave up on “{ep.title}” ({ep.show}) after {tries} attempts")
            else:
                failed.append(ep)

    # FAIL LOUD ON A TOTAL WIPEOUT (spec §9).
    #
    # Per-episode error handling is right: one bad download must never sink the
    # briefing. But it also meant a 100% failure rate still reported success.
    # PyAV 19 broke faster-whisper's decoder on 2026-09-30 and every episode
    # failed with TypeError for three days while the job stayed green, the
    # news and in-print layers kept the email looking normal, and Healthchecks
    # kept receiving success pings. If there was podcast work and none of it
    # survived, the run is not healthy, whatever the email looks like.
    total_wipeout = is_total_failure(len(new_eps), len(briefed), len(failed), len(gave_up))
    if total_wipeout:
        print(
            f"[pipeline] TOTAL FAILURE: {len(new_eps)} episode(s) found, none processed "
            f"({len(failed)} retryable, {len(gave_up)} written off)"
        )
        footer.insert(
            0,
            f"No podcasts could be processed at all today — {len(new_eps)} episode(s) "
            "failed. The pipeline needs attention; this email is news-only.",
        )
    write_status(
        args.status_file,
        new=len(new_eps),
        briefed=len(briefed),
        failed=len(failed),
        gave_up=len(gave_up),
        deferred=len(deferred),
        total_episode_failure=total_wipeout,
    )

    # News layer (agent brief A.1) — archive-only, never fatal to the briefing.
    try:
        n_news = fetch_news(cfg, archive)
        print(f"[news] {n_news} new stor{'y' if n_news == 1 else 'ies'} saved")
    except Exception as e:
        print(f"[news] stage failed ({type(e).__name__}) - continuing without news")
        footer.append("News fetch failed this run")
    try:
        n_pol = fetch_politico(cfg, archive)
        print(f"[politico] {n_pol} newsletter(s) saved")
    except Exception as e:
        print(f"[politico] stage failed ({type(e).__name__}) - continuing")
        footer.append("Politico fetch failed this run")

    # "In print" — under-the-radar online news for the briefing email itself.
    in_print_items, print_hashes = [], []
    try:
        in_print_items, print_hashes = fetch_in_print(cfg, archive, state)
    except Exception as e:
        print(f"[in-print] stage failed ({type(e).__name__}) - continuing without it")
        footer.append("In-print scan failed this run")

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("[config] GEMINI_API_KEY is not set")
    missing = [v for v in ("BRIEFING_FROM", "BRIEFING_TO", "GMAIL_APP_PASSWORD") if not os.environ.get(v)]
    if missing:
        sys.exit(f"[email] missing in .env: {', '.join(missing)}")

    today = date.today()
    date_label = f"{today:%A} {today.day} {today:%B %Y}"

    for ep in failed:
        footer.append(f"Couldn't process “{ep.title}” ({ep.show}) - will retry next run")
    if deferred:
        shows = ", ".join(sorted({ep.show for ep in deferred}))
        footer.append(
            f"Ran out of time for {len(deferred)} episode(s) ({shows}) - they're first in line tomorrow"
        )
        print(f"[pipeline] time budget reached - deferring {len(deferred)} episode(s) to tomorrow")

    # ONE EMAIL PER DAY, hard rule: a cron that fires hours late after a
    # briefing already went out must not send again. Work isn't wasted —
    # transcripts/items are cached in the archive, and held episodes stay
    # unmarked so tomorrow's briefing carries them.
    if sent_email_today(state):
        if briefed or in_print_items:
            print(
                f"[email] already emailed today - holding {len(briefed)} episode(s) "
                f"and {len(in_print_items)} print item(s) for tomorrow"
            )
        else:
            print("[email] already emailed today - nothing more to send")
        save_state(state, state_file)
        return

    if briefed or in_print_items:
        episodes_data = [result for _, result in briefed]
        # Dedupe the same story across shows before anything is ranked or rendered.
        flat = [(item, ep["transcript"]) for ep in episodes_data for item in ep["items"]]
        groups = cluster_items(flat, cfg["gemini"]) if flat else []
        stories = build_stories(episodes_data, groups)
        top = select_top_line(stories, cfg["gemini"]) if stories else []
        print(f"[render] {len(stories)} story/stories, top line: {len(top)}, in-print: {len(in_print_items)}")
        subject, text, html = render_briefing(
            date_label, stories, top=top, footer_notes=footer, in_print=in_print_items
        )
    elif failed:
        subject, text, html = render_fallback(
            date_label, [(ep, transcript_url(cfg, ep)) for ep in failed], footer
        )
    elif cfg["behaviour"]["quiet_day_email"]:
        subject, text, html = render_quiet(date_label, footer)
    else:
        save_state(state, state_file)
        print("[email] quiet day - skipping email")
        return

    send_email(subject, text, html, cfg["email"])
    record_email_sent(state)

    # Only after a successful send do briefed episodes count as done.
    for ep, result in briefed:
        mark_processed(state, ep)
        append_index_line(archive, ep, result["guests"], result["topics"])
    # All considered print candidates (selected or not) are done for good;
    # prune the seen-store so it can't grow without bound.
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    seen = state.setdefault("print_seen", {})
    for h in print_hashes:
        seen[h] = now_iso
    horizon = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    state["print_seen"] = {h: t for h, t in seen.items() if t >= horizon}
    save_state(state, state_file)
    print(f"[state] saved ({len(state['processed'])} processed total)")


if __name__ == "__main__":
    main()
