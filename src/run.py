"""Pipeline orchestrator.

Thin-slice build: stages appear here one at a time as they're built.
LOG DISCIPLINE (spec §7): in production this repo's Actions logs are public.
Print feed metadata (titles, dates, counts, durations) only — never transcript
text, quotes, or briefing content.
"""

import argparse
import json
import os
import sys
from datetime import date

from config import ROOT, load_config, data_dir
from download import download_audio
from emailer import send_email
from feeds import fetch_episodes
from render import render_briefing
from state import is_processed, load_state, mark_processed, save_state
from summarise import summarise
from transcribe import transcribe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--whisper-model",
        help="override config.toml whisper model (e.g. 'small' for fast local tests)",
    )
    args = ap.parse_args()

    cfg = load_config()
    feed_cfg = cfg["feeds"][0]  # thin slice: single feed

    state_file = ROOT / cfg["storage"]["state_file"]
    state = load_state(state_file)

    print(f"[feeds] fetching: {feed_cfg['name']}")
    episodes = fetch_episodes(feed_cfg)
    print(f"[feeds] {len(episodes)} episodes in feed")

    # Thin slice: newest episode only. (Phase 3 processes every unprocessed
    # episode across the roster; the launch-backfill decision governs seeding.)
    latest = episodes[0]
    if is_processed(state, latest):
        print(f"[state] newest episode already processed ({latest.published}) - nothing new today")
        return

    mins = f"~{latest.duration_secs // 60} min" if latest.duration_secs else "unknown length"
    print(f"[feeds] newest: '{latest.title}' ({latest.published}, {mins})")

    print("[download] fetching audio...")
    audio = download_audio(latest, data_dir(cfg))
    print(f"[download] saved: {audio.name} ({audio.stat().st_size / (1 << 20):.1f} MB)")

    transcript_file = transcribe(audio, latest, cfg["whisper"], model_name=args.whisper_model)

    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit(
            "[summarise] GEMINI_API_KEY is not set. Create a file named .env in the "
            "project root containing:\n  GEMINI_API_KEY=your-key-here\n"
            "(.env is gitignored — the key never reaches the repo.)"
        )

    transcript = json.loads(transcript_file.read_text(encoding="utf-8"))
    items_file = transcript_file.with_suffix("").with_suffix(".items.json")
    if items_file.exists():
        print(f"[summarise] already done: {items_file.name}")
        items = json.loads(items_file.read_text(encoding="utf-8"))
    else:
        items = summarise(transcript, cfg["gemini"])
        items_file.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    # Log discipline: counts only, never item content.
    sig = sum(1 for i in items if i["tier"] == "significant")
    print(f"[summarise] {len(items)} item(s): {sig} significant, {len(items) - sig} fragments")

    missing = [v for v in ("BRIEFING_FROM", "BRIEFING_TO", "GMAIL_APP_PASSWORD") if not os.environ.get(v)]
    if missing:
        sys.exit(f"[email] missing in .env: {', '.join(missing)} — fill them in and re-run.")

    today = date.today()
    date_label = f"{today:%A} {today.day} {today:%B %Y}"
    subject, text, html = render_briefing(date_label, [{"transcript": transcript, "items": items}])
    print(f"[render] briefing assembled ({len(text.splitlines())} lines)")

    send_email(subject, text, html, cfg["email"])

    # Only now — after a successful send — does the episode count as done.
    mark_processed(state, latest)
    save_state(state, state_file)
    print(f"[state] marked processed ({len(state['processed'])} episode(s) in state)")


if __name__ == "__main__":
    main()
