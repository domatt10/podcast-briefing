# Design notes and operational handover

Why this system is built the way it is. The README covers what it does and how
to run it; this file covers the decisions, and the production failures that
caused them. Read `docs/briefing-spec.md` for the original specification.

Last updated 2026-10-31.

---

## 1. What it is for

An external affairs role in offshore wind needs to know what government and
industry people are saying **before it becomes news** — the speculation layer
that lives in podcasts and newsletters rather than in official publications.
Listening to twenty shows a week is not feasible; reading the twenty minutes of
each that matter is.

Three products run from this repository:

1. **Daily briefing** — transcribes UK politics and energy podcasts overnight,
   selects what matters against a stated relevance test, and emails it before
   the working day starts.
2. **Archive and search** — transcripts accumulate in a private repository,
   with an offline search page built over them.
3. **Constituency Watch** — a weekly digest of *local* offshore wind and tidal
   news across six coastal geographies.

The unifying rule: **quotes are verbatim by construction.** The model selects
passages by segment number; code reconstitutes the words. Almost every other
design decision follows from protecting that.

---

## 2. Architecture

```
  20 podcast RSS feeds                        ← config.toml [[feeds]]
        │  feeds.py → download.py → transcribe.py (faster-whisper "medium")
  transcript JSON   (numbered, timestamped segments = ground truth)
        │  summarise.py — the model returns SEGMENT IDs + an anchor, never text
  items.json        (tier / stream / why / segment_ids / anchor)
        │  cluster_items() dedupes a story across shows
        │  render.build_stories() → render_briefing()
  email (HTML + text) ← emailer.py, Gmail SMTP
```

| Repository | Visibility | Role |
|---|---|---|
| code (this one) | **public** | All code and workflows. Public because GitHub Actions minutes are unlimited on public repositories — that is what makes the project free to run. **No transcripts, no secrets, ever.** |
| archive | **private** | Transcripts, archived news, `state.json`, `index.md`. Written by CI using a write-scoped deploy key. |

**`src/`**: `run.py` (orchestrator) · `config.py` · `feeds.py` · `download.py` ·
`transcribe.py` · `summarise.py` · `render.py` · `emailer.py` · `state.py` ·
`news.py` (BBC RSS) · `politico.py` (Gmail IMAP) · `in_print.py` · `index.py` ·
`constituency.py` · `build_search.py` · `catchup.py` · `backfill_*.py`.

**Workflows**: `briefing.yml` (daily) · `constituency.yml` (weekly) ·
`catchup.yml` (recovery) · `backfill.yml` (manual only).

**Relevance inputs**: `profile.md` (who the reader is and what clears the bar)
and `baseline.md` (what is already established, so recaps are not reported as
news). Both are plain Markdown read into the prompt at run time. Tuning the
briefing usually means editing these, not the code.

---

## 3. Current state

**Daily briefing** — the trigger is **external**: cron-job.org fires a
`workflow_dispatch` at 03:47 UTC. GitHub's own `schedule:` is a single backup
entry. Email lands 06:00–07:30 UK. 20 feeds.

**Archive** — 1,387 transcripts from 2025-12-28, roughly 9.8 million words;
324 Politico newsletters from 2026-02-20 (the mailbox's own start); 1,224 BBC
items; 215 "In print" articles; `index.md` with one line per episode.

**Constituency Watch** — six geographies, Mondays.

**Monitoring** — two Healthchecks.io dead-man's-switch checks (daily and
weekly), success ping plus `/fail`. cron-job.org emails if the trigger request
itself fails.

**Tests** — `tests/test_briefing.py`, 27 offline tests, no API access needed.

---

## 4. Decisions that must not be quietly reverted

**Verbatim by construction.** The model returns segment IDs plus an `anchor`
locator; `render.reconstitute()` joins real transcript text. Validation requires
a **consecutive** run — gaps would splice together words never said together.

**Public code, private archive.** Never move transcripts into the public
repository, and never log transcript content: CI logs on a public repository
are world-readable. Error logging prints the exception type and the innermost
file and line, never the message, because a model error can echo the prompt
back and the prompt contains transcript text.

**External trigger, not GitHub cron.** GitHub's scheduler ran 6–11 hours late
daily. Do not "fix" it by adding cron entries.

**One email per calendar day, enforced in code** (`state.sent_email_today`). A
late backup run **holds** its episodes for the next day rather than
double-mailing.

**Tier budget enforced in code** (`_enforce_tier_budget`, maximum three
significant items per episode). Prompt-only control drifted to 33 of 36 items
marked significant. Priority order: core patch → institutional memory →
longest.

**The core-patch exemption is gated on policy bearing.** Offshore and grid
material gets a lower altitude bar, but only where it bears on whether projects
get built or on the commercial framework. Operational industry talk — training,
crew transfer — is out. A looser version turned a safety-training episode into
19 items.

**Attribute to the SHOW, not a guessed speaker.** Transcripts carry no speaker
labels. "The Rest Is Politics reports that…" A name is used only where the text
removes doubt: the speaker self-identifies, or there is a single named guest.
Never pick between co-hosts.

**Constituency Watch inverts the altitude test.** Low altitude *is* the product
there. Its prompt lives in `constituency.py` and must **never** import
`profile.md`.

**`baseline.md` stops settled facts reading as news.** It is the one file that
goes stale by itself. Re-verify against gov.uk/government/ministers after any
reshuffle; the pipeline warns in the log once it is 45 days old.

**Politico fetch is date-windowed, not unread-based.** The original UNSEEN
design raced the reader's own mail client and lost a week of newsletters.

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
significant report that loses out on a busy news day gets another look. Daily
commentary stays one-shot. The prompt judges research on its finding, not on
what publishing it signals — the opposite of how it reads comment pieces.

**`headline_only = true` exists for sources with no usable RSS.** The IFS is
reached through a Google News `site:` query, whose links redirect to a consent
page. The flag skips body extraction entirely — flag and link, no quote —
rather than relying on `_looks_like_boilerplate()` to catch it afterwards.
`clean_title()` strips the " - <Publisher>" suffix Google News appends. Use it
sparingly: a flag-only item competes for the same six slots as a fully quoted
one, so it has to earn a slot on its finding alone.

**Check research feeds for RECENCY, not just that they parse.** Rejected after
testing, so do not re-add without re-checking: UKERC (649 entries, every title
empty), Cornwall Insight (staff bio pages and a "Form test page"), Green
Alliance (newest item 2023, and a press-clippings feed), Policy Exchange
(newest 2020), `ifs.org.uk/rss.xml` (one entry, "Home", 2022). The IFS, ECIU
and IPPR publish no usable RSS at any common path.

**No retrieval-augmented generation over the archive.** At ~9.8 million words
it is far beyond a model's context or a hosted knowledge base. Search is
grep-style, over a pre-built index.

**Deliberately not done:** collapsing `state.json` (2 MB, mostly seeded-only
entries) into per-feed watermarks. A bug there could re-transcribe the entire
back catalogue. High risk, no current pain.

---

## 5. Failure modes hit in production, and what guards them now

Each of these cost a real outage. The guard is recorded because removing it
re-opens the failure.

| What happened | Guard |
|---|---|
| **Sequential transcription overran the 300-minute job timeout.** State is only saved after a successful send, so a timeout banked *nothing* and the backlog compounded 7→13→16. Three days with no briefing (2026-09-11 to 09-13). | `run.py --max-minutes` (default 210): stop starting new episodes, send what is done, defer the rest and name them in the footer. |
| **The model's free tier is 20 requests per day PER MODEL**, not a high ceiling. A 16-episode morning needs ~20 on its own. Both ladder rungs ran dry. | `model_ladder()`, now five rungs (~100 calls a day). Each rung is another 20 calls, ordered by capability so quality degrades as late as possible. If this bites again the answer is a paid tier, not more juggling. |
| **Archive push rejected** when the backfill collector pushed concurrently; state was lost, so the next run re-processed and sent a **second** briefing. | Every archive push retries with `pull --rebase`. Backfill is manual-only — no recurring second writer. |
| **An unparseable model response escaped** past the fallback handler, killing a whole episode. | Parse errors now fall through to the next model in the ladder. |
| **Mis-pointed quotes** (~13%): a note about party purges attached to a quote about farming. | Each item carries an `anchor`; `repair_anchors()` re-points the segment IDs. It **never drops an item** — an explicit call by the reader: a slightly mismatched item beats a missing one. |
| **Whisper mis-hears names**, corrupting quotes and the archive alike. | Domain glossary in `config.toml`. Refresh after a reshuffle, alongside `baseline.md`. |
| **An unpinned transitive dependency broke everything, silently.** PyAV 19 landed 2026-09-30; faster-whisper 1.2.1 asks only for `av>=11`, so CI installed it and every episode failed with `TypeError` for three days. The job reported **success** throughout: per-episode error handling meant a 100% failure rate still produced an email, because the news and in-print layers were unaffected. Monitoring received success pings. 24 episodes undelivered, 11 written off at the retry cap. | `requirements.txt` bounds every direct dependency and hard-caps `av<19`. `run.py:is_total_failure()` writes a status file, and `briefing.yml` has a **tripwire step after the archive push** that fails the job on a total wipeout so the `/fail` ping fires. Cause-agnostic, so it catches the next one too. |
| **A silent outage needs a recovery path that does not duplicate the daily product.** Recovered summaries must reach the reader, but not under the daily subject line — recipients may have mail rules keyed to it. | `src/catchup.py`: summarises recovered transcripts and sends **one** email under a different brand, never touching `last_email_at`. See §6. |
| **The recovery itself silently delivered nothing** (2026-10-03). `catchup.py` treated a missing `index.md` line as "never emailed", but `backfill_collect.py` writes index lines for *every transcript it collects* — so recovering the transcripts made all 24 episodes look delivered. The scheduled pass exited with "nothing to recover" and reported success. Two days of believed-fixed, actually-nothing. | Selection now keys off **`items.json` absence**, plus a failure record, plus `--since` (§6). `--dry-run` stops before summarising, so the selection can always be checked for free. |

---

## 6. Operating notes

**Run locally** (never commit `.env`):

```bash
ARCHIVE_DIR=/path/to/scratch python src/run.py --whisper-model small
```

Always point `ARCHIVE_DIR` at a **scratch** copy when testing. `--whisper-model
small` keeps local runs fast.

**Tests**: `python tests/test_briefing.py` — 27 of them, fully offline.

**Model quota is 20 requests per day per model.** Prefer offline verification
(cached `items.json` plus a render) over re-running the model; a testing spree
exhausts the day's budget and blocks the real briefing.

**Both repositories push to `main`.** CI heartbeat commits mean `git pull
--rebase` before pushing is routine.

### Recovering a backlog after an outage

1. Fix the cause and push it. The backfill installs the same
   `requirements.txt`, so it fails the same way until you do.
2. `gh workflow run backfill.yml -f days=7 -f chunks=12` — transcribes in a
   parallel matrix (~1 hour for 24 episodes; serially it would exceed the job
   timeout). Whisper only: no model calls, no email.
3. Pull the archive.
4. **Claim the backlog before the next 03:47 run**: `src/catchup.py --claim`,
   then commit and push the archive. Without this the daily briefing finds the
   episodes unprocessed with transcripts sitting ready, summarises the lot, and
   sends the whole backlog under the daily subject line. Claiming marks them
   processed but keeps the failure records, so the catch-up can still find them.
5. Deliver with `catchup.yml`, or `src/catchup.py` locally. Use
   `--max-episodes` to split a large backlog across days: 24 summarise calls
   plus clustering will not fit the free tier alongside a normal briefing. Each
   pass sends **one** email, indexes what it sent, and clears those failure
   records so the next pass picks up cleanly. Run `--dry-run` first, always.

**`catchup.py` selects on three conditions, all required**: a recorded failure,
published on or after `--since`, and **no `items.json` beside the transcript**.
Each is load-bearing, and getting this wrong has already cost one failed
recovery:

- **Failure records alone are not a delivery ledger.** `episode_failures` was
  append-only until 2026-10-02, so it still holds counters for episodes that
  failed once, succeeded, and were delivered months ago.
- **`index.md` is not a delivery ledger either**, though it looks like one.
  `run.py` appends a line only after a successful send — but
  `backfill_collect.py` appends one for *every transcript it collects*.
  `index.md` records what is *archived*, not what was *read*.
- **`items.json` absence is the honest test** — nothing writes it without
  summarising — but alone it would sweep in the ~1,000 historical backfill
  transcripts, which have never been summarised and never should be. Hence the
  other two bounds.

`--ignore-items` covers the one case the `items.json` test gets wrong: a pass
that summarised successfully and then failed to *send* leaves `items.json`
behind without delivery. `--show NAME` covers a different case — episodes
archived but never summarised, typically a newly added feed whose back
catalogue was marked processed on first sight.

---

## 7. Known limits and open items

**Watch, do not pre-empt**
- Whether the time budget and the five-rung ladder hold on a heavy morning.
- Whether the longer `baseline.md` over-suppresses live items.

**Known open, low priority**
- `index.md`: ~283 backfill-era lines lack guests and topics. Cosmetic.
- Sequential transcription makes heavy days slow. The real fix is a
  parallel-matrix daily run — the `backfill.yml` architecture applied to
  `briefing.yml`. Parked until it causes real pain.
- The search page is ~41 MB in one file. Workable; splitting by year is the fix
  if it becomes slow to open.

**Structural limits worth stating plainly**
- Transcripts are derived from copyrighted audio. Appropriate for one person's
  private reference; a different question entirely if shared or republished.
- Relevance is tuned to a single reader through `profile.md`. This is not a
  general-purpose product.
- The Gmail app password grants both read and send access to a mailbox, with no
  scoping and no expiry. It exists because the Politico layer reads an inbox.
  On a managed estate this is the first thing to replace.
- The whole system depends on five services having usable free tiers.
