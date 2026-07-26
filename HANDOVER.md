# Handover — podcast-briefing

Written 2026-07-26. For a fresh Claude Code session with no memory of previous
work. Read `CLAUDE.md` (repo conventions + status) and `docs/briefing-spec.md`
(the original spec) alongside this.

---

## 1. The overall goal

Dom is External Affairs & Policy Manager at The Crown Estate (marine team,
offshore wind). He wants to know what UK politics and energy people are saying
**before it becomes news** — the speculation layer that lives in podcasts and
newsletters rather than in official channels.

Three products now run from this one repo, all live and automated:

1. **Daily briefing** — transcribes UK politics/energy podcasts overnight,
   selects what matters to him, emails a briefing before he wakes up.
2. **Archive agent** — the transcripts accumulate in a private repo that he can
   ask questions of ("trace how the reshuffle chatter evolved").
3. **Constituency Watch** — a weekly digest of *local* offshore-wind/tidal news
   for the geographies where his leases actually get built.

The unifying design rule: **quotes are always verbatim.** The LLM selects
passages by ID; code reconstitutes the exact words. The model never writes a
quote. Everything else follows from protecting that.

---

## 2. Architecture in one page

```
  podcasts (18 RSS feeds)                    ← config.toml [[feeds]]
        │
        ▼  feeds.py → download.py → transcribe.py (faster-whisper "medium")
  transcript JSON  (numbered, timestamped segments = ground truth)
        │
        ▼  summarise.py — Gemini picks SEGMENT IDs, never text
  items.json  (tier / stream / why-line / segment_ids)
        │
        ▼  summarise.cluster_items() — dedupes the same story across shows
        ▼  render.build_stories() → render.render_briefing()
  email (HTML + plain text)  ← emailer.py, Gmail SMTP app password
```

Two repos:

| Repo | Visibility | Role |
|---|---|---|
| `domatt10/podcast-briefing` | **public** | all code + workflows. Public because GitHub Actions minutes are unlimited on public repos — that's what makes this free. **No transcripts, no secrets, ever.** |
| `domatt10/podcast-briefing-archive` | **private** | transcripts, news, `state.json`, `index.md`. Copyrighted material stays here. Cloned locally at `C:\Users\Dom's PC\code\podcast-archive`. |

CI writes to the archive with a write-scoped **deploy key** (`ARCHIVE_DEPLOY_KEY`).

**Source files** (`src/`): `run.py` (orchestrator) · `config.py` · `feeds.py` ·
`download.py` · `transcribe.py` · `summarise.py` · `render.py` · `emailer.py` ·
`state.py` · `news.py` (BBC RSS) · `politico.py` (Gmail IMAP) · `in_print.py`
(under-the-radar news) · `index.py` · `constituency.py` (weekly digest, separate
product) · `backfill_*.py` (one-off history) · `politico_backfill.py`.

**Workflows**: `briefing.yml` (daily) · `constituency.yml` (weekly) ·
`backfill.yml` (manual).

---

## 3. Current state — all green as of 2026-07-26

**Daily briefing.** Runs every morning. Trigger is **external**: cron-job.org
fires a `workflow_dispatch` at **03:47 UTC** on the dot. GitHub's own `schedule:`
cron proved 6–11 hours late every day, so it's demoted to a single backup entry
(`17 6 * * *`). Emails land ~06:00–07:30 UK. 18 feeds, ~8,881 episodes marked
processed.

**Archive.** ~330 transcripts (`.md` + `.transcript.json` + `.items.json`),
562 news files including 154 Politico newsletters, `index.md`. Coverage starts
**2026-04-08** (a 90-day backfill) — before that, nothing exists.

**Constituency Watch.** Six geographies, Mondays 04:47 + 05:27 UTC. Last ran
2026-07-20; **next run 2026-07-27 is the first since the summarise.py changes**
(imports verified clean, but it hasn't executed since — worth watching).

**Monitoring.** Two Healthchecks.io checks (daily + weekly), each pinged on
success and `/fail` on error. cron-job.org emails Dom if the trigger request
itself fails.

**Working tree:** both repos clean and pushed. `tests/test_briefing.py` — 7
tests, all passing, no API calls needed (`.venv/Scripts/python.exe tests/test_briefing.py`).

---

## 4. Key decisions and why

Understanding these prevents "fixing" things that are deliberate.

**Verbatim by construction, not by instruction.** The model returns segment IDs;
`render.reconstitute()` joins the actual transcript text. A model *cannot*
paraphrase a quote because it never handles quote text. This is the spec's
central rule — never loosen it. Validation enforces that IDs are a **consecutive
run**: skipping segments would splice together words never said together.

**Public code repo / private archive.** The split exists so Actions stay free
while copyrighted transcripts stay off the open web. Never move transcripts into
the public repo, and never log transcript content (CI logs are public).

**External trigger, not GitHub cron.** GitHub's scheduler has no delivery
guarantee. Documented behaviour, not a bug. Don't "fix" it by adding more cron
entries; the external dispatch is the fix.

**One email per calendar day, enforced in code** (`state.sent_email_today`).
Late-firing backup runs must never double-mail. A second run **holds** its
episodes for tomorrow rather than discarding them. As of 2026-07-25 the backup
run also exits within seconds instead of doing an hour of discarded work.

**Tier budget enforced in code, not just the prompt** (`_enforce_tier_budget`,
max 3 "significant" per episode). The prompt asks for restraint and drifts
badly — one day returned 33 of 36 items as significant, flattening the hierarchy.
Priority when choosing which keep full treatment: core patch (energy/Crown
Estate) → institutional memory → longest passage. Demoted items stay verbatim,
just trimmed.

**Cross-episode dedup** (`cluster_items` → `build_stories`). The same story
arrived from up to five shows at full length. Now one primary passage plus an
"Also on:" line — which doubles as the spec's *attribution density* signal: a
bare item visibly means one source, a corroborated one means the lobby is talking.

**Core-patch exemption, gated on policy bearing.** Offshore/grid material gets a
*lower* altitude bar (it needn't have crossed a minister's desk), but only when
it bears on whether projects get built or on the commercial/political framework.
Operational industry talk (training standards, crew transfer, vessel logistics)
is **out**. First attempt at this exemption was too loose and turned a
safety-training episode into 19 items; the gated version returns 0 for that
episode and 4 for a floating-wind policy episode. Don't loosen it back.

**Constituency Watch inverts the altitude test.** Low altitude *is* the product
there — parish-council objections, cable-landfall rows. Its prompt lives in
`constituency.py` and must **never** import `profile.md`. If you wire the shared
briefer profile into it, you will silently destroy the thing it exists to catch.

**Politico fetch is date-windowed, not unread-based.** The original design
fetched UNSEEN mail and marked it read — which raced Dom's own reading and lost
a week of newsletters. Now: read-only mailbox, `SINCE` window
(`lookback_days = 3`), `BODY.PEEK`, dedupe by Message-ID hash in the filename.
Read flags are never touched.

**No RAG, no GitHub connector for the archive.** Grep-style agentic search over
files is more robust for a fast-growing archive. The archive is ~3.1M words —
roughly 20× what a Project knowledge base holds — so RAG was never viable.

**Deliberately NOT done:** collapsing `state.json` (2 MB, ~8,000 seeded-only
entries) into per-feed watermarks. A bug there could trigger re-transcription of
the entire back catalogue. High risk, no current pain. Leave it unless it bites.

---

## 5. Most recent work (2026-07-25) — first production exposure is imminent

Dom asked for a critical review of two weeks of output. Findings and fixes, all
shipped:

| Problem found | Fix | Verified how |
|---|---|---|
| Same story from 3–5 shows, each at full length | `cluster_items` + "Also on:" | Live: 36 items → 21 stories |
| 76% of items flagged "significant" — flat hierarchy | Prompt rules **+ code cap** | Unit tests; live re-runs |
| Energy specialists contributing almost nothing | Core-patch exemption, policy-gated | Live: 0→4 on a floating-wind ep |
| Quotes arriving as walls of text | Paragraph breaks (whitespace only) | Real-data render |
| Unparseable retry killed a whole episode | Falls through to fallback model | Code path corrected |
| Stale glossary ("Miata Fambula") | Burnham cabinet added | Config |
| "In print" 30/35 items from 3 political sites | Spread prompt + `max_per_source = 2` | Config |
| Backup run did an hour of discarded work | Early exit | **Live 2026-07-26 ✓** |
| Plain presentation | Design system + lane colours | Preview emailed to Dom |

**Presentation**: serif for reading, sans for chrome, tinted quote blocks, inbox
preheader, and per-lane colour coding at Dom's request — Energy green, Crown
Estate navy, Treasury red, Top of government orange, Parliamentary colour plum,
In print slate. Headings read `Crown Estate lane (2)` in the lane colour.
Tokens live at the top of `render.py`.

⚠️ **Important nuance for the next session:** the 2026-07-26 run reused a
**cached** `items.json`, so the **new summarise prompt has not yet run on a fresh
episode in production.** The cluster, render, in-print and early-exit paths have.
The first genuine test of the new selection prompt is the next run that
transcribes a new episode (likely Monday 2026-07-27, a busy day). **Check that
run's output**: tier split should be roughly one third significant, energy
specialists should produce policy-bearing items rather than operational chatter,
and no episode should return an unexpected zero.

---

## 6. What's left to do

**Watch first (no action needed unless it misbehaves)**
- Monday 2026-07-27: first busy-day run on the new prompt, and the first
  Constituency Watch since `summarise.py` changed.
- Whether the tier budget's cap of 3 feels right on heavy days. Dom is a fast
  reader and **does not want length cut** — the goal is hierarchy for skimming,
  not brevity. Don't add quote-length caps.

**Known-open, low priority**
- `index.md`: 283 of 322 lines lack guests/topics (backfill-era placeholders).
  Cosmetic; new episodes fill in correctly.
- "In print" sits at the end of the email. Dom skims, so deprioritised.
- Sequential transcription: heavy days take 4–6 h wall-clock. The fix is a
  parallel-matrix daily run (the `backfill.yml` architecture applied to
  `briefing.yml`). Parked until lateness actually annoys him.
- `state.json` growth — see "deliberately NOT done" above.

**Possible next projects Dom has raised**
- A **rolling digest file** (one paragraph per episode, last 90 days, ~25k words)
  small enough for a Claude Project — so he can browse the archive in the Claude
  mobile app rather than claude.ai/code.
- A **new analysis project** on podcast agendas and prediction accuracy. Dom has
  the starter prompt already; it lives outside this repo and reads the archive
  read-only. The archive's `README.md` documents the three access patterns.

**No blockers.** Nothing is broken, nothing is waiting on Dom, both repos are
clean and pushed.

---

## 7. Practical notes for working here

**Run locally** (never commit `.env`):

```bash
cd "C:\Users\Dom's PC\code\podcast-briefing"
ARCHIVE_DIR=/path/to/scratch/archive ./.venv/Scripts/python.exe src/run.py --whisper-model small
```

Always point `ARCHIVE_DIR` at a **scratch** copy when testing, or you will write
test artefacts into the real archive. `--whisper-model small` keeps local runs
fast. `--no-email` exists on `constituency.py` (not on `run.py` — for the daily
briefing, control sending via `last_email_at` in the scratch state file).

**Tests**: `./.venv/Scripts/python.exe tests/test_briefing.py` — offline, no API.

**Gemini free tier exhausts quickly.** ~40 test calls in an afternoon hit 429s on
both models. Production uses ~8/day. Prefer offline verification (cached
`items.json` + render) over re-running the model.

**Shell gotcha:** PowerShell here-strings mangle multi-line commit messages
(colons break them). Use Bash with a heredoc:
`git commit -F - <<'EOF' ... EOF`.

**Both repos push to `main` directly.** Heartbeat commits from CI mean you often
need `git pull --rebase` before pushing.

**Dom's working preferences:** plain English, no corporate speak — in the code's
output *and* in how you talk to him. Explain what you're doing, step by step. No
big unattended changes. Tell him clearly when something needs him to act outside
the editor. He is learning Claude Code, so narrate the reasoning, not just the
result.
