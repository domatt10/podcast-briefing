# Podcast signals briefing

Transcribes 20 UK politics and energy podcasts overnight, selects the passages
that matter against a stated relevance test, and emails a briefing of verbatim
quotes before the working day starts.

Built for one reader: an external affairs and policy role in offshore wind.
Running daily since July 2026, on free tiers, at no cost.

**The central design rule:** the language model never writes a quote. It is
given a transcript split into numbered segments and returns *segment numbers*;
code then reconstitutes the exact words from the transcript. The model cannot
paraphrase or invent a quote, because it never produces quote text at all.

---

## What it produces

| Output | Cadence | Contents |
|---|---|---|
| Daily briefing | Weekday mornings, by 07:30 UK | Verbatim podcast quotes grouped by theme, each with a one-line note on why it matters, plus an "In print" section drawn from commentary and research feeds |
| Constituency Watch | Weekly | Local offshore wind and tidal news across six coastal geographies |
| Archive and search | Continuous | 1,387 transcripts (~9.8M words) and 1,763 archived news items, with an offline search page built over them |

### Scope, if you are evaluating this for a rebuild

The three products are not of equal value, and the whole repository is here as
a reference implementation rather than as a specification of what to build.

**The daily briefing is the product.** The archive is its by-product — the
transcripts have to be kept anyway, so the search layer is close to free. Those
two together are the core.

**Everything else is optional, and two parts carry questions worth settling
early:**

- **The Politico layer** (`politico.py`) reads a mailbox over IMAP. It is the
  sole reason the system needs a Gmail app password with read access, which is
  its weakest credential by some distance. Dropping this layer removes that
  credential entirely.
- **The "In print" layer** (`in_print.py`) fetches third-party articles and
  reproduces paragraphs from them. Fine for one person's private reading;
  a licensing question at any wider distribution.
- **Constituency Watch** (`constituency.py`, `constituency.yml`) is live and
  left in deliberately, because its relevance logic is the most interesting in
  the repository — its prompt **inverts** the daily briefing's altitude test,
  since low altitude is the whole point of a local digest. It is **not** part
  of the intended first scope.

---

## How a run works

```
cron-job.org (03:47 UTC) ──▶ GitHub Actions ──▶ temporary runner
                                                      │
   20 RSS feeds ──▶ download audio ──▶ faster-whisper transcription
                                                      │
                    numbered, timestamped segments (ground truth)
                                                      │
          model selects passages BY SEGMENT NUMBER ──▶ items.json
                                                      │
          code reconstitutes exact text ──▶ cluster ──▶ render ──▶ email
                                                      │
                              transcripts + state ──▶ private archive repo
```

Audio is downloaded to the runner, transcribed, and destroyed with the runner.
Only text is kept.

---

## Repository layout

```
src/                 20 Python modules; run.py is the orchestrator
tests/               27 offline tests, no API access needed
.github/workflows/   briefing (daily), constituency (weekly),
                     catchup (recovery), backfill (manual)
config.toml          every tunable: feeds, models, thresholds, glossary
profile.md           who the reader is and what clears the bar
baseline.md          what is already established, so recaps aren't reported
docs/                original specification and an example of the output
HANDOVER.md          design decisions and the production failures behind them
```

**Tuning the briefing usually means editing `profile.md`, `baseline.md` or
`config.toml` — not the code.** The relevance logic lives in prose, on purpose,
so that it can be changed by the person who knows what "relevant" means.

---

## Running it

Requires Python 3.12.

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in the values
ARCHIVE_DIR=/path/to/scratch python src/run.py --whisper-model small
```

Point `ARCHIVE_DIR` at a **scratch** directory when testing, never at the real
archive. `--whisper-model small` keeps local runs fast; production uses
`medium`.

```bash
python tests/test_briefing.py     # 27 tests, fully offline
```

### Configuration

Secrets come from the environment — a local `.env` (gitignored) or GitHub
Actions secrets in CI. Nothing is hardcoded.

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Passage selection |
| `GMAIL_APP_PASSWORD` | Sending mail, and reading the Politico layer's inbox |
| `BRIEFING_FROM` / `BRIEFING_TO` | Sender and recipient |
| `ARCHIVE_DIR` | Path to the archive working copy |
| `HEALTHCHECK_URL` / `HEALTHCHECK_URL_WEEKLY` | Dead-man's-switch monitoring |

---

## Why it is shaped the way it is

Short version; the reasoning is in [HANDOVER.md](HANDOVER.md).

- **The code repository is public** because GitHub Actions minutes are
  unlimited on public repositories, and transcription is hours of CPU every
  night. That is what makes the project free — and why the copyrighted
  transcripts live in a separate private repository, and why nothing sensitive
  is ever printed to a log.
- **The schedule is triggered externally** because GitHub's own scheduler ran
  6–11 hours late every day.
- **Five models are configured**, not for redundancy but as a quota pool: the
  free tier allows 20 requests per day *per model*.
- **Failures are loud.** One broken feed never sinks a run, but a run where
  *every* episode failed deliberately fails the job, so monitoring fires. Added
  after a three-day outage in which the job reported success each morning while
  processing nothing.
- **Dependencies are pinned**, including transitive ones, after a library two
  levels down shipped a breaking major version overnight.

---

## Limits

- Transcripts are derived from copyrighted audio. Appropriate for one person's
  private reference; a separate question if shared or republished.
- Relevance is tuned to a single reader. This is not a general-purpose product.
- The Gmail app password grants read *and* send access to a mailbox, unscoped
  and without expiry. It exists only because the Politico layer reads an inbox;
  dropping that layer removes the credential.
- Transcript text is sent to a third-party model API for passage selection.
  Transcription itself is local to the runner.
- The whole system depends on five services continuing to offer usable free
  tiers.
