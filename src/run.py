"""Pipeline orchestrator.

Thin-slice build: stages appear here one at a time as they're built.
LOG DISCIPLINE (spec §7): in production this repo's Actions logs are public.
Print feed metadata (titles, dates, counts, durations) only — never transcript
text, quotes, or briefing content.
"""

import argparse

from config import load_config, data_dir
from download import download_audio
from feeds import fetch_episodes
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

    print(f"[feeds] fetching: {feed_cfg['name']}")
    episodes = fetch_episodes(feed_cfg)
    print(f"[feeds] {len(episodes)} episodes in feed")

    latest = episodes[0]
    mins = f"~{latest.duration_secs // 60} min" if latest.duration_secs else "unknown length"
    print(f"[feeds] newest: '{latest.title}' ({latest.published}, {mins})")

    print("[download] fetching audio...")
    audio = download_audio(latest, data_dir(cfg))
    print(f"[download] saved: {audio.name} ({audio.stat().st_size / (1 << 20):.1f} MB)")

    transcribe(audio, latest, cfg["whisper"], model_name=args.whisper_model)


if __name__ == "__main__":
    main()
