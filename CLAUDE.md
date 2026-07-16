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

Three products run from this repo, all LIVE:

1. **Daily briefing** (external trigger 03:47 UTC + backup cron): 18 feeds (expanded 2026-07-16), back catalogues seeded,
   news layer (BBC ×3 + Politico IMAP) feeding the archive, index.md lines.
2. **Archive agent** (docs/archive-agent-brief.md): private archive + rich
   CLAUDE.md there; ~90-day transcript backfill in progress via backfill.yml
   (self-limiting chunks; collector always banks).
3. **Constituency Watch** (docs/constituency-watch-brief.md): weekly local
   offshore-wind/tidal digest, Mondays 04:47 + 05:27 UTC. ⚠️ Its prompt INVERTS
   the altitude test — never wire profile.md into it. Slice geography: Celtic
   Sea & Welsh waters. CW-2 (Planning Inspectorate DCO watch) deliberately
   DEFERRED until an English DCO-heavy geography (East Anglia/Humber) joins —
   Welsh projects route via NRW/Welsh consenting, not the PI register.

Both email products are Healthchecks-monitored (cron-type checks; success ping +
/fail ping). Still open: official-transcript-first (no roster show publishes
one); institutional-memory + tiering iteration during soak (spec App. B).
