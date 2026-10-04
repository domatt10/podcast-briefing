# Handover — podcast-briefing

For a session with no memory of previous work. Read `CLAUDE.md` (conventions)
and `docs/briefing-spec.md` (original spec) alongside this. Last updated
2026-09-13.

---

## 1. The goal

Dom is External Affairs & Policy Manager at The Crown Estate (marine team,
offshore wind). He wants to know what UK politics and energy people are saying
**before it becomes news** — the speculation layer in podcasts and newsletters.

Three products run from this repo:

1. **Daily briefing** — transcribes UK politics/energy podcasts overnight,
   selects what matters to him, emails it before he wakes.
2. **Archive agent** — the transcripts accumulate in a private repo he can ask
   questions of, plus an offline search page.
3. **Constituency Watch** — weekly digest of *local* offshore-wind/tidal news.

The unifying rule: **quotes are verbatim by construction.** The LLM selects
passages by ID; code reconstitutes the words. Everything else follows from
protecting that.

---

## 2. Architecture

```
  19 podcast RSS feeds                        ← config.toml [[feeds]]
        │  feeds.py → download.py → transcribe.py (faster-whisper "medium")
  transcript JSON   (numbered, timestamped segments = ground truth)
        │  summarise.py — Gemini returns SEGMENT IDs + an anchor, never text
  items.json        (tier / stream / why / segment_ids / anchor)
        │  cluster_items() dedupes a story across shows
        │  render.build_stories() → render_briefing()
  email (HTML + text) ← emailer.py, Gmail SMTP app password
```

| Repo | Visibility | Role |
|---|---|---|
| `domatt10/podcast-briefing` | **public** | all code + workflows. Public because Actions minutes are unlimited on public repos — that is what makes this free. **No transcripts, no secrets, ever.** |
| `domatt10/podcast-briefing-archive` | **private** | transcripts, news, `state.json`, `index.md`. Cloned at `C:\Users\Dom's PC\code\podcast-archive`. |

CI writes to the archive with a write-scoped deploy key (`ARCHIVE_DEPLOY_KEY`).

**src/**: `run.py` (orchestrator) · `config.py` · `feeds.py` · `download.py` ·
`transcribe.py` · `summarise.py` · `render.py` · `emailer.py` · `state.py` ·
`news.py` (BBC RSS) · `politico.py` (Gmail IMAP) · `in_print.py` · `index.py` ·
`constituency.py` · `build_search.py` · `backfill_*.py`.

**Workflows**: `briefing.yml` (daily) · `constituency.yml` (weekly) ·
`backfill.yml` (manual only).

---

## 3. Current state

**Daily briefing** — trigger is **external**: cron-job.org fires a
`workflow_dispatch` at 03:47 UTC. GitHub's own `schedule:` is a single backup
entry only. Email lands ~06:00–07:30 UK. 19 feeds.

**Archive** — ~1,000 transcripts from 2025-12-28, 220+ Politico newsletters from
2026-02-20 (the mailbox's own start), BBC/in-print/constituency news, `index.md`.

**Constituency Watch** — six geographies, Mondays 04:47 + 05:27 UTC.

**Monitoring** — two Healthchecks.io checks (daily + weekly), success ping and
`/fail`. cron-job.org emails Dom if the trigger request itself fails.

**Tests** — `tests/test_briefing.py`, 14 offline tests, no API needed.

Dom **auto-forwards the briefing to his manager**. Keep it presentable; if a
one-off personal email is ever needed, avoid the usual subject wording (see §6).

---

## 4. Decisions that must not be quietly reverted

**Verbatim by construction.** The model returns segment IDs (plus an `anchor`
locator); `render.reconstitute()` joins real transcript text. Validation requires
a **consecutive** run — gaps would splice together words never said together.

**Public code / private archive.** Never move transcripts into the public repo,
never log transcript content (CI logs are public).

**External trigger, not GitHub cron.** GitHub's scheduler was 6–11 hours late
daily. Don't "fix" it by adding cron entries.

**One email per calendar day, enforced in code** (`state.sent_email_today`). A
late backup run **holds** its episodes for tomorrow rather than double-mailing.

**Tier budget in code** (`_enforce_tier_budget`, max 3 significant/episode).
Prompt-only control drifted to 33-of-36. Priority: core patch → institutional
memory → longest.

**Core-patch exemption is gated on policy bearing.** Offshore/grid material gets
a lower altitude bar, but only when it bears on whether projects get built or on
the commercial framework. Operational industry talk (training, crew transfer) is
out. A looser version turned a safety-training episode into 19 items.

**Attribute to the SHOW, not a guessed speaker.** Transcripts have no speaker
labels. "The Rest Is Politics reports that…" A name only when the text removes
doubt (self-identifies, or a single named guest). Never pick between co-hosts.

**Constituency Watch inverts the altitude test.** Low altitude *is* the product.
Its prompt lives in `constituency.py` and must **never** import `profile.md`.

**`baseline.md` stops settled facts reading as news.** Who is in post and what is
already established. **Re-verify against gov.uk/government/ministers after any
reshuffle** — the pipeline warns in the log past 45 days.

**Politico fetch is date-windowed, not unread-based** — the original UNSEEN
design raced Dom's own reading and lost a week of newsletters.

**"In print" extraction must never trust a consent wall.**
`_looks_like_boilerplate()` rejects a fetched body that reads as a cookie
notice. Without it, a Google News link resolves to consent.google.com and
yields ~900 characters of cookie policy — over `MIN_BODY_CHARS`, so the quote
stage would have published Google's cookie notice as an extended quote
attributed to the Institute for Fiscal Studies. Applies to every feed: any
consent-walled publisher can do the same.

**Research feeds are a distinct tier, not just more feeds.** `kind =
"research"` in `config.toml` buys a 168-hour lookback instead of 30, and
exempts *unselected* items from being marked seen (`hashes_to_mark()`), so a
significant report that loses a busy news day gets another look. Daily
commentary stays one-shot. The prompt judges research on its FINDING, not on
what publishing it signals — the opposite of how it reads comment pieces.

**Check research feeds for RECENCY, not just that they parse.** Rejected after
testing, so don't re-add without re-checking: UKERC (649 entries, every title
empty), Cornwall Insight (staff bio pages and a "Form test page"), Green
Alliance (newest 2023, press-clippings feed), Policy Exchange (newest 2020),
`ifs.org.uk/rss.xml` (one entry, "Home", 2022). **IFS, ECIU and IPPR have no
usable RSS at any common path** — reachable only via Google News `site:`
queries, which hit the consent wall above.

**No RAG / GitHub connector for the archive** — it is ~3M words, far beyond a
Project knowledge base. Grep-style search only.

**Deliberately NOT done:** collapsing `state.json` (2 MB of mostly seeded-only
entries) into per-feed watermarks. A bug there could re-transcribe the whole back
catalogue. High risk, no current pain.

---

## 5. Failure modes hit in production, and what guards them now

Each of these cost a real outage. The guard is listed because removing it
re-opens the failure.

| What happened | Guard |
|---|---|
| **Sequential transcription overran the 300-min job timeout.** State is only saved after a successful send, so a timeout banked *nothing* and the backlog compounded 7→13→16. Three days with no briefing (2026-09-11 to 09-13). | `run.py --max-minutes` (default 210): stop starting new episodes, send what's done, defer the rest and name them in the footer. |
| **Gemini free tier is 20 requests/day PER MODEL** — not a high ceiling. A 16-episode morning needs ~20 alone. Both ladder rungs ran dry. | `model_ladder()` with three rungs (~60/day). Each rung is another 20 calls. If this bites again the answer is a paid tier, not more juggling. |
| **Archive push rejected** when the backfill collector pushed concurrently; state was lost, so the next run re-sent and Dom got **two** briefings. | Every archive push retries with `pull --rebase`. Backfill is manual-only — no recurring second writer. |
| **Unparseable Gemini retry escaped** past the fallback-model handler, killing a whole episode. | Parse errors now fall through to the next model. |
| **Mis-pointed quotes** (~13%): a note about party purges attached to a quote about farming. | Each item carries an `anchor`; `repair_anchors()` re-points the segment IDs. **Never drops an item** — Dom's explicit call: a slightly mismatched item beats a missing one. |
| **Whisper mis-hears names**, corrupting quotes and the archive alike. | `config.toml` glossary. Refresh it after a reshuffle alongside `baseline.md`. |
| **An unpinned transitive dependency broke everything, silently.** PyAV 19 landed 2026-09-30; faster-whisper 1.2.1 asks only for `av>=11`, so CI installed it and every episode failed with `TypeError` for three days (30 Sept – 2 Oct). The job reported **success** throughout: per-episode error handling meant a 100% failure rate still sent an email, because news and in-print were fine. Healthchecks got success pings. 24 episodes undelivered, 11 written off at the retry cap. | `requirements.txt` bounds every direct dependency and hard-caps `av<19`. `run.py:is_total_failure()` writes a status file; `briefing.yml` has a **tripwire step after the archive push** that fails the job on a total wipeout so `/fail` fires. Cause-agnostic — it catches the next one too. |
| **A silent outage needs a recovery path that doesn't spam the reader.** The backlog's summaries must reach Dom but must NOT arrive as "Daily podcast summary" — that subject is auto-forwarded to his manager. | `src/catchup.py`: summarises recovered transcripts and sends **one** email under a different brand, never touching `last_email_at`. See §7. |
| **The recovery itself silently delivered nothing** (2026-10-03). `catchup.py` treated a missing `index.md` line as "never emailed", but `backfill_collect.py` writes index lines for every transcript it collects — so recovering the transcripts made all 24 episodes look delivered. The scheduled pass exited with "nothing to recover" and reported success. Two days of believed-fixed, actually-nothing. | Selection now keys off **`items.json` absence** plus failure record plus `--since` (§7). `--dry-run` stops before summarising so the selection can always be checked for free. |

---

## 6. What's left

**Watch, don't pre-empt**
- Whether the time budget + three-rung ladder hold on a heavy morning.
- Whether the ellipsis on clipped quotes reads naturally.

**Known-open, low priority**
- `index.md`: ~283 backfill-era lines lack guests/topics. Cosmetic.
- "In print" sits at the end of the email; Dom skims, so deprioritised.
- Sequential transcription: heavy days are slow. The real fix is a
  parallel-matrix daily run (the `backfill.yml` architecture applied to
  `briefing.yml`). Parked until it annoys him.
- Search page is ~40 MB. Fine, but splitting by year is the fix if it drags.

**If a personal (non-forwarded) email is ever needed**: Dom auto-forwards the
daily briefing to his manager. A one-off must avoid the usual wording — patch
`render.BRAND` and pass a distinct `date_label`. Unknown whether his rule matches
subject or sender; if sender, no subject change will help.

---

## 7. Practical notes

**Run locally** (never commit `.env`):

```bash
cd "C:\Users\Dom's PC\code\podcast-briefing"
ARCHIVE_DIR=/path/to/scratch ./.venv/Scripts/python.exe src/run.py --whisper-model small
```

Always point `ARCHIVE_DIR` at a **scratch** copy when testing. `--whisper-model
small` keeps local runs fast.

**Tests**: `./.venv/Scripts/python.exe tests/test_briefing.py` — offline, 19 of them.

**Recovering a backlog after an outage** (the 2026-09-30 drill, in order):

1. Fix the cause and push it — the backfill installs the same
   `requirements.txt`, so it fails the same way until you do.
2. `gh workflow run backfill.yml -f days=7 -f chunks=12` — transcribes in a
   parallel matrix (~1 h for 24 episodes; serially it would exceed the job
   timeout). Whisper only, no Gemini, no email.
3. `git -C ../podcast-archive pull`
4. **Claim the backlog before the next 03:47 run**:
   `src/catchup.py --claim`, then commit and push the archive. Without this the
   daily briefing finds 24 unprocessed episodes with transcripts sitting ready,
   summarises the lot, and sends the whole backlog in the email that gets
   **auto-forwarded to Dom's manager**. Claiming marks them processed but keeps
   the failure records, so the catch-up can still find them.
5. Deliver it with `catchup.yml` (or `src/catchup.py` locally). Use
   `--max-episodes` to split a big backlog across days: 24 summarise calls plus
   clustering will not fit the Gemini free tier alongside a normal briefing.
   Each pass sends **one** email branded "Archive catch-up", indexes what it
   sent and clears those failure records, so the next pass picks up cleanly.
   `--dry-run` first, always — it is what caught the stale-failure bug below.

`catchup.py` selects on **three** conditions, all required: a recorded failure,
published on or after `--since`, and **no `items.json` beside the transcript**.

Each one is load-bearing, and getting this wrong has already cost a failed
recovery:

- **Failure records alone are not a delivery ledger.** `episode_failures` was
  append-only until 2026-10-02, so it still holds counters for episodes that
  failed once, succeeded, and were delivered months ago.
- **`index.md` is NOT a delivery ledger either**, though it looks like one.
  `run.py` appends a line only after a successful send — but
  `backfill_collect.py` also appends one for *every transcript it collects*. So
  the backfill that recovered the 30 Sept transcripts gave all 24 episodes
  index lines, and the first catch-up excluded the whole backlog as "already
  delivered" and sent nothing. `index.md` records what is *archived*, not what
  was *read*.
- **`items.json` absence is the honest test** — nothing writes it without
  summarising — but on its own it would sweep in the ~1,000 historical backfill
  transcripts, which have never been summarised and never should be. Hence the
  other two bounds.

`--ignore-items` exists for the one case the items.json test gets wrong: a pass
that summarised successfully then failed to *send* leaves items.json without
delivery. `--dry-run` stops before summarising, so it is free — use it every
time; it has now caught two selection bugs.

**Gemini quota is 20/day/model.** Prefer offline verification (cached
`items.json` + render) over re-running the model; a testing spree exhausts the
day's budget and blocks the real briefing.

**Shell:** PowerShell here-strings mangle multi-line commit messages (colons
break them). Use Bash with a heredoc: `git commit -F - <<'EOF' … EOF`.

**Both repos push to `main`.** CI heartbeat commits mean `git pull --rebase`
before pushing is routine.

**Dom's preferences:** plain English, no corporate speak — in the product's
output *and* in how you talk to him. Explain step by step; no big unattended
changes. Say clearly when something needs him to act outside the editor. He is
learning Claude Code, so narrate the reasoning, not just the result.
