# Working conventions

Context for an AI coding assistant working in this repository. For what the
system is and does, read `README.md`; for why it is shaped this way, and the
production failures behind each guard, read `HANDOVER.md`.

## Architecture (settled — do not re-litigate without reading HANDOVER §4)

- **This repository is PUBLIC.** GitHub Actions minutes are unlimited on public
  repositories, which is what makes the project free to run. Transcripts and
  processed-episode state live in a **separate private repository**, written by
  CI through a write-scoped deploy key (`ARCHIVE_DEPLOY_KEY`).
- **Trigger is external**: cron-job.org fires a `workflow_dispatch` at 03:47
  UTC. GitHub's own `schedule:` entry is a backup only — its scheduler ran
  6–11 hours late daily.
- **Transcription**: self-hosted faster-whisper, "medium" model, segment-level
  timestamps, domain glossary passed as `initial_prompt`.
- **Selection**: Gemini free tier. Five models in `config.toml`, ordered by
  capability — a quota pool, not a failover chain, because the free tier allows
  20 requests per day *per model*.
- **Delivery**: Gmail SMTP app password. **Monitoring**: Healthchecks.io
  dead-man's-switch, plus a tripwire that fails the job when episodes were
  found and none could be processed.

## Non-negotiable invariants

1. **Verbatim quotes are reconstituted by code** from numbered transcript
   segment IDs. The model returns segment IDs and relevance notes, never quote
   text as prose. Validation requires a consecutive run of segments.
2. **Attribution is stamped by code** from feed metadata — show, episode title,
   date, hosts, guests — one episode per model call, so the model cannot
   misattribute across episodes. Attribute to the show, never to a guessed
   speaker: transcripts carry no speaker labels.
3. **Idempotent.** The processed-episode state file (GUID, falling back to
   title and date) is checked before any transcription or email. Never
   re-process, never double-send.
4. **Nothing sensitive to stdout or logs.** This repository's Actions logs are
   world-readable. Counts, titles and timings only — no transcript text, no
   quotes, no briefing content, no email addresses. Error logging prints the
   exception type and innermost file and line, never the message: a model error
   can echo the prompt, and the prompt contains transcript text.
5. **Fail loud, degrade gracefully.** Per-feed and per-episode isolation, so one
   broken thing never sinks a run — but a run where *everything* failed fails
   the job deliberately, so monitoring fires.

## Conventions

- Python 3.12. Development on Windows (`.venv\Scripts\python`); production is
  `ubuntu-latest`.
- All tunables — models, feeds, thresholds, glossary — live in `config.toml`.
  No magic constants in code.
- Dependencies are **bounded, including transitive ones**. `av<19` is a
  load-bearing cap, not tidiness: see HANDOVER §5.
- Secrets come from environment variables: `.env` locally (gitignored,
  documented in `.env.example`), GitHub Secrets in CI.
- `profile.md` is the relevance arbiter. Prompt changes should be tested
  against it, not against intuition. It names roles, never individuals, so it
  does not go stale.
- `baseline.md` is the current-landscape file — what is already established, so
  recaps are not reported as news. It is the one file that goes stale by
  itself: **re-verify against gov.uk/government/ministers after any reshuffle**.
  The pipeline warns in the log once it is 45 days old.
- Tests are offline and need no API access: `python tests/test_briefing.py`.
  Add one for any logic that has failed in production.

## Status

Three products run from this repository, all live:

1. **Daily briefing** — 20 feeds, external trigger plus backup cron. News layer
   (BBC RSS ×3, Politico via IMAP) feeding the archive; "In print" layer over
   14 commentary and research feeds; `index.md` updated per episode.
2. **Archive and search** — private archive repository, 1,387 transcripts from
   2025-12-28, with `build_search.py` producing an offline search page.
3. **Constituency Watch** — weekly local offshore wind and tidal digest across
   six geographies. ⚠️ Its prompt deliberately **inverts** the altitude test —
   never wire `profile.md` into it.

Recovery tooling: `backfill.yml` (manual, parallel transcription) and
`catchup.py` / `catchup.yml` (summarise a recovered backlog and send it
separately from the daily product). The drill is in HANDOVER §6.
