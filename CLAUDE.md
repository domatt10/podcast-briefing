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

Phase 1 (thin end-to-end slice): one feed (How We Build Britain) → download → transcribe →
summarise → email, with the state file. Full roster, five sections, tiering and archive
come after the slice works.
