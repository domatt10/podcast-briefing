# Archive Agent — Build Brief

**What this is.** A conversational agent over the growing transcript archive from the daily briefing system — for asking things like *"trace how the reshuffle chatter evolved over June,"* *"what's been said about the SSEP since launch,"* *"prep me for a Celtic Sea floating-wind meeting."* It is **not a new app**: it's Claude Code pointed at a local clone of the private transcript repo, guided by a standing `CLAUDE.md`. This brief also adds a few small things to the existing daily pipeline so the archive is richer.

**Assumes** the briefing system (`briefing-spec.md`) is already built, and **reuses its parts**: the public repo (pipeline + free unlimited Actions minutes), the private repo (`/transcripts` archive), the Gmail app password, and the cross-repo token. The only new external step is pointing Politico at the existing Gmail.

**Three parts:** (A) small additions to the existing daily pipeline; (B) the agent itself; (C) a one-off 3-month backfill.

---

## A. Additions to the existing daily pipeline (public repo)

**1. A news layer — a factual spine alongside the podcast speculation.** This is the real upgrade: it lets the agent calibrate rumour against outcome (*"the podcasts predicted a June reshuffle — here's what actually happened — whose read was right?"*).
- **BBC + a couple of RSS feeds (easy):** pull a **curated** selection each run — UK politics plus relevant energy stories, not the whole firehose — and save each as text to `/news/` in the **private** repo, with a small header (source, title, date, URL). No transcription, no LLM — just fetch and save.
- **Politico via IMAP (small extra step):** connect to the existing Gmail over **IMAP with the app password** (no Gmail API / OAuth — that's the fiddly thing we deliberately avoided), fetch new Politico-labelled emails since the last run, strip HTML → text, save to `/news/politico/` with a header, then mark them read so they're never re-grabbed. One credential covers both *sending* the briefing and *reading* Politico.
- Keep news in the **private** repo (subscriber content — off the open web), in a `/news` tree kept separate from `/transcripts`.

**2. An index line.** At the end of each run, append one line per new episode to `index.md` in the private repo: `date · show · episode title · guests · topics`. Gives the agent a fast map instead of grepping blind.

---

## B. The agent (a local clone of the private repo)

- **Local clone** of the private transcripts repo on the personal machine. The `CLAUDE.md` instructs a `git pull` at the start of each session, so the agent is always on the latest archive.
- **`CLAUDE.md`** (the standing brief Claude Code reads on startup) should contain:
  - **The briefer profile** — reuse §8 of `briefing-spec.md` so the agent already knows the lens (role, Crown Estate landowner/enabler angle, the altitude + proximity relevance test).
  - **Citation discipline:** quote **verbatim** from the transcript files, always with `show · episode · guests · timestamp`; never paraphrase a quote from memory. Treat `/transcripts` as **attributed speculation** and `/news` as **reported fact**, and cite each distinctly — keep the rumour-vs-reality line clean.
  - **Search guidance:** check `index.md` and the per-file metadata headers first; search **synonyms** (zonal = locational = REMA; SSEP; connections reform; etc.); cover both `/transcripts` and `/news`.
  - **Calibration use:** where podcasts made predictions, cross-check `/news` for what actually happened and note which sources were right.
- **Usage:** open Claude Code in that folder and ask. Works in the terminal at home, or remotely via the Claude mobile app.

---

## C. One-off backfill — 3 months

- **Transcription only — no Gemini.** The agent reads raw transcripts, so history needs Whisper and nothing else. Whisper runs on the **public** repo where minutes are unlimited and free, so this costs **nothing** in plan terms. (A paid Claude plan is irrelevant here — Claude doesn't transcribe audio.)
- Fetch each feed's last ~3 months, transcribe (same medium model + metadata headers as the daily job), save to `/transcripts`, and populate `index.md`.
- **Parallelise** (~20 concurrent jobs on public repos) — a few nights of batch running, not weeks.
- **Bounded one-off**, not a permanent grind — a defined seeding burst stays within GitHub's fair-use.
- **Depth varies by show** — some feeds only expose recent episodes, so 3 months is a target, not a guarantee.

---

## What needs you (Claude Code should walk you through each, step by step)

- Get **Politico landing in the personal Gmail** — subscribe it there, or auto-forward from wherever it currently arrives (never the work inbox) — and add a Gmail **filter/label** so the pipeline can find it.
- Confirm **IMAP is enabled** in that Gmail's settings (the app password already exists from the briefing build).
- **Trigger and monitor the backfill** run.
- Everything else reuses the briefing build (both repos, Gmail app password, cross-repo token, local git auth).

---

## Build order (thin slice first)

1. **Stand up the agent over the *current* archive first** — local clone + `CLAUDE.md` — and confirm it searches and cites well, before anything else.
2. Add the **news layer** (BBC/RSS first; Politico IMAP second) to the daily pipeline.
3. Add the **`index.md`** line.
4. Run the **3-month backfill** last, once the format and index are settled.

---

## Watch-outs

- **Newsletter HTML is messy** — ads/tracking/sponsor blocks; accept some boilerplate after HTML → text. Fine as reference material.
- **Gmail IMAP / app passwords** can be tightened by Google — confirm they're on at setup; if ever disabled, no-code fallbacks (Zapier, Google Apps Script) don't depend on IMAP.
- **News must not drown the podcast signal** — keep it curated, in its own `/news` tree, with the reported-fact-vs-speculation distinction spelled out in `CLAUDE.md`.
- **No RAG / GitHub connector** — grep-style agentic search over the files is simpler and more robust for a fast-growing archive than Projects' auto-RAG or the GitHub connector (which needs re-syncing and has been flaky).
- **Private repo** holds transcripts *and* news — both stay off the public side.
