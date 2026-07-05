# Podcast Signals Briefing

Automated daily email digest: UK politics + energy podcasts → Whisper transcription →
Gemini summarisation → morning email. Full specification in `docs/briefing-spec.md`;
target output format in `docs/example-briefing.md` (also the few-shot example inside
the summarisation prompt).

## Architecture (locked — see spec §7)

- **This repo becomes PUBLIC** (free unlimited GitHub Actions). Transcripts + processed-episode
  state live in a separate PRIVATE repo, written via a fine-grained token.
- Scheduled GitHub Actions workflow (~05:30 UTC, odd minute) + `workflow_dispatch`.
- Transcription: self-hosted Whisper (faster-whisper engine), segment-level timestamps,
  domain glossary in `initial_prompt`. Official show transcripts preferred where published.
- Synthesis: Gemini API free tier, strongest available model, model name in `config.toml`.
- Delivery: Gmail SMTP app password. Monitoring: Healthchecks.io dead-man's-switch.

## Non-negotiable invariants

1. **Verbatim quotes are reconstituted by code** from numbered transcript segment IDs.
   Gemini returns segment IDs + relevance notes, NEVER quote text as prose.
2. **Attribution is stamped by code** from feed metadata (show, episode title, date, hosts,
   guests), one episode per Gemini call — the model cannot misattribute across episodes.
3. **Idempotent**: processed-episode state file (GUID, fallback title+date) checked before
   any transcription or email; never re-process, never double-send.
4. **Nothing sensitive to stdout/logs**: this repo's Actions logs are world-readable.
   No transcript text, no quotes, no briefing content — only counts and timestamps.
5. **Fail loud, degrade gracefully**: per-feed and per-episode isolation; Healthchecks ping
   on full success only; fallback email (raw episode list) if synthesis fails.

## Conventions

- Python 3.12 (`.venv\Scripts\python`). Windows dev machine; production is ubuntu-latest.
- All tunables (models, feeds, schedule) in `config.toml` — no magic constants in code.
- Secrets from environment variables (local: `.env`, gitignored; CI: GitHub Secrets).
- The briefer profile (spec §8) is the relevance arbiter — prompt changes should be
  tested against it, not against intuition.

## Status

LIVE: scheduled daily at 05:37 UTC, one feed (How We Build Britain), monitored by
Healthchecks.io (ping on success, /fail on breakage). Private archive receives
transcripts + state via deploy key.

Next (Phase 3): the full 13-feed roster with per-feed isolation and junk filtering,
top-line selection across episodes, the fallback email path (raw episode list if
synthesis fails), N-runs-failed feed flag in the footer, official-transcript-first
for shows that publish one. Then Phase 4: a week of soak + the backfill decision.
