# Daily Political & Energy Signals Briefing — Build Spec

**What this is.** A complete specification for an automated daily briefing: it ingests a fixed set of UK politics and energy podcasts, transcribes them, and emails a signals-and-speculation digest each morning. Built collaboratively and pressure-tested — ready to hand to Claude Code as the build brief.

**How to use it.** Give this file to Claude Code alongside `example-briefing.md` (the worked example of the target output, which also serves as the few-shot example inside the summarisation prompt). Sections 1–5 define *what* the briefing is and looks like; 6–9 define *how* it's sourced, built and kept alive. Section 8 (the briefer profile) is the artefact the system reads every morning to judge relevance — it deserves the most care. Appendix A is the pre-build to-do list; Appendix B is the critical-review watch-outs.

**Map:** 1 Purpose · 2 Streams · 3 Standing rules · 4 Attribution · 5 Output shape · 6 Sources · 7 Stack & architecture · 8 Briefer profile · 9 Failure & reliability · 10 Future · A Pre-build setup · B Watch-outs.

---

## 1. The job it does

A personal early-warning system for one question: **is the political and fiscal environment for offshore wind shifting — how, and who needs convincing?**

A **signals-and-speculation briefing, not a news briefing.** The value is the rumour/prediction layer, *with attribution*, so the reader can form their own view and pick up signals early enough to flag to seniors and policy colleagues. "Point me toward where to look" is enough — a good tip-off with its source is the unit of value.

**Read context:** mobile, ~8am, 10–15 minutes. ~1/4 to 1/3 reported fact as grounding, from the podcasters' own recaps.

**Cadence:** runs every morning, covering episodes new since the last run. Quiet mornings are expected, not a fault.

---

## 2. The five streams (lenses applied to the transcripts)

1. **Top of government** — PM attitude/positioning with energy implications; machinery/"wiring" of government (lower bar — fluency is part of the reader's credibility).
2. **Energy / DESNZ** — core; highest resolution. Fed by the energy specialists (§6).
3. **Treasury / fiscal** — deliberately a **low bar**; general HMT mood music, not only when energy-linked.
4. **Parliamentary colour & speculation** — MP/opposition interviews, rebellion speculation, PMB chatter. Soft layer only — formal monitoring is PolicyMogul's job (§6).
5. **Crown Estate lane** — Crown Estate, seabed leasing, NESO, SSEP → **covered in detail**.

---

## 3. Standing rules

- **Always include** any current or former **energy or Treasury minister or SpAd** — by role, not name.
- **Crown Estate lane → detail.**
- **Institutional-memory / explanatory material → include, even if only a line.** Prompt for it deliberately; full richness lives in the archive (§7).
- **Predictions must carry their reasoning/basis** where given.
- **Surface disagreement** between sources.
- **Attribution density** — flag one-source vs many.

---

## 4. Attribution philosophy

- **Episode-level** attribution (podcast, hosts, guests); not speaker-level.
- Preserve who said it, where, how confidently.
- **Faithfulness to source is paramount.** See §5.

---

## 5. Output shape

Email, mobile-first, ~8am.

- **Top line** — 2–4 most significant signals, one line each + source.
- **Five fixed sections, fixed order**, grouped under two bands — **"On your patch"** (Energy/DESNZ, Crown Estate lane) and **"The wider weather"** (Treasury, Top of government, Parliamentary colour). Fixed, not ranked, so the reader can jump to a stream and quiet days stay legible; the two-band split also stops a light-energy day reading as failure.
- Within sections, items **listed cleanly, not ranked**.

**Item format — tiered. No hard length ceiling — reader is a fast reader who prefers richness; a busy day may run 2–3× longer, and longer quotes/context are welcome where the material warrants.**
- *Significant items:* signpost of why it matters + **verbatim passage (1–3+ paragraphs)** + source + **timestamp**.
- *Everything else:* one-line flag + **several-word verbatim fragment** + source + timestamp.
- **Every item, including fragments, carries feed-metadata context:** show, **episode title**, and **guest name(s)** — even where the specific speaker isn't attributed, this frames what the discussion was worth.
- **Crown Estate lane:** fuller treatment. **Institutional-memory items:** marked.

**Cross-cutting items:** single most relevant section; if important, also in the top line. No duplication.

**Verbatim integrity (the mechanism matters):** number the transcript segments; Gemini returns the **segment IDs** for a relevant passage plus its relevance note, and the **code reconstitutes the exact text + timestamp from those IDs**. Gemini must *not* hand back the quote as prose — if it does, you get its tidied paraphrase, silently defeating the whole feature. Same rule for the low-tier fragments.

---

## 6. Sources — podcasts only

**Not duplicated:** formal parliamentary monitoring (Hansard, committees, EDMs) via **PolicyMogul**.

### Westminster / general politics
Politics At Sam and Anne's · The Rest Is Politics · The Rest Is Politics: Leading · Westminster Insider (Politico) · Political Currency · Oh God, What Now? · The Rundown (PoliticsHome) · Chopper's Political Podcast (**GB News / Acast feed**, weekly Fri — not the defunct Telegraph one) · The Politics Show (**New Statesman** flagship; Anoosh Chakelian + team; Acast; twice weekly).

### Energy / infrastructure / industry
Aurora "Energy Unplugged" · The Offshore Wind Podcast (GWEC) · reNEWS · How We Build Britain (Rob Gilbert; Buzzsprout — energy/infrastructure/industry; short, essayistic).
*Optional later: Watt Matters, ORE Catapult.*

**Removed:** Matt Forde's Political Party. **Balance:** 9 Westminster + 4 energy/infra.

---

## 7. Technical stack & architecture (locked)

- **Compute home:** a **public GitHub repo** runs the scheduled workflow — unlimited free Actions minutes; removes the cost ceiling and allows an accurate model.
- **Privacy split:** code, profile and prompts in the public repo. **Transcripts written to a separate private repo** via a token — keeps copyrighted transcripts off the open web; preserves the private archive (§10). Transcripts are tiny; the private repo runs no compute → still free.
- **Transcription:** OpenAI **Whisper**, self-hosted, **episode-by-episode** (each job under the 6h cap), **segment-level timestamps** on. Medium-grade (accurate) model.
- **Synthesis:** **Gemini API**, free tier (Flash). Caveat: free-tier inputs may be used for training; UK commercial-use a grey area — fine for personal use.
- **Secrets:** Gemini key + cross-repo token in encrypted GitHub Secrets. Job **scheduled-only, not exposed to fork PRs**.
- **Archive:** transcripts to `/transcripts` (private repo), by podcast/date, each with a metadata header (podcast, title, date, hosts, guests).
- **Public logs are public:** a public repo's Actions logs are world-readable — the pipeline must **never print transcript text, quotes or the briefing to stdout**, and the heartbeat commit must carry only innocuous metadata (timestamp, episode count), never content.
- **Per-episode + code-stamped attribution:** Gemini processes one episode's transcript at a time; the **code stamps the source metadata** (podcast, date, hosts, guest) onto each item, so Gemini can't misattribute across episodes. Feeding it the known host/guest names also lets it distinguish "the guest said" from "a host said" without full diarization.
- **Model as config; use the strongest free model:** call volume is a few calls/day, so favour the most capable model the free tier allows over defaulting to Flash — the oblique-relevance judgement (§8) is exactly what weak models miss. Keep the model name a config value (Google rotates/retires free models).
- **Official transcript first:** where a show publishes its own transcript, use it (faster, more accurate, no compute); fall back to Whisper otherwise.
- **Delivery:** email, ~8am. **Cost:** zero.

---

## 8. Profile of the briefer (the load-bearing artefact)

The system reads this every morning to decide what clears the bar. Getting it right matters more than the pipeline.

**Who:**
- **Role:** External Affairs & Policy Manager, offshore/marine; primary focus **offshore wind** (secondary: tidal, nature, interconnectors).
- **Organisation:** **The Crown Estate**, marine team.
- **Lens — landowner/enabler, not developer or thinktank.** Seabed leasing; the commercial framework under developers; the interface between government ambition and deployment. Weights: allocation-round economics, route-to-market, grid/transmission, the investment climate for big capital projects, government appetite to de-risk vs leave it to the market.

**What he's doing with it:**
- **Core motivation:** align the organisation's work with government priorities; find the best "way in" for engagement; anticipate ministerial moves and changes of direction; prepare for scenarios.
- **Payoff:** catches a soft signal early (e.g. HMT cooling on big energy projects), articulates it upward/across, never out of the loop going into conversations.
- **Existing diet (supplement, don't duplicate):** reads/rates Politico; gets day-to-day sector + industry news, and formal parliamentary monitoring (PolicyMogul), elsewhere.

**Two audiences (what makes him look on the ball):**
- *Specialist marine policymakers* — he advises them on the wider political environment. Wants **granular political signals**: funding shifts ("Reeves might cut CCS funding"), personnel ("the energy minister looks like he'll be moved"), prioritisation direction ("government favouring projects that do X over Y").
- *Seniors & external-affairs colleagues* — wants the **big-picture political weather**: where the winds are blowing, where government is feeling pressure. Plus a career/credibility interest in being seen as across the political vibe (hence the wider-politics streams).

**The relevance test — two axes, applied together:**
- **Altitude:** does it cross a minister's desk or change a decision-maker's mind? Moves, reshuffles, shifts in priority, money switched on/off → **in**. Delivery of already-announced policy, or detail below the ministerial radar → **out, even within the offshore core.**
- **Proximity rings:**
  - *Core, deepest detail:* offshore/marine energy (CCS, offshore wind, tidal, oil & gas) + grid/system (NESO's SSEP, connections reform, zonal-vs-national / REMA pricing debates).
  - *Outer ring, informed-level only:* hydrogen, onshore wind, etc. — in only when landscape-shaping or high-altitude.
  - *Geographic:* England/Wales/NI seabed incl. the Celtic Sea = core; **Scotland at lower resolution** (its offshore wind and oil & gas debates yes; ScotWind leasing minutiae and Scottish domestic politics no).

**"Pressure on government" = internal signals** — comments/rumours from *within* government that it's feeling pressure — not external lobbying noise (tracked elsewhere).

**Negative space (out):** anything that is *both* irrelevant to the energy sector / the running of government *and* unlikely to be a talking point among general public-affairs people. (So horse-race polling detail, foreign politics, culture-war rows, party-management trivia → out — unless genuinely landscape-shaping or a live public-affairs conversation.)

---

## 9. Failure behaviour & reliability

**Three principles:** (1) *Degrade gracefully* — one broken source/episode never sinks the run; always send something. (2) *Be idempotent* — track processed episodes; never re-transcribe or double-send. (3) *Make failure loud, not silent* — the failure that bites is the job quietly stopping, since GitHub gives no alert on scheduled-job failure.

**Monitoring (highest priority):**
- A free dead-man's-switch (e.g. Healthchecks.io): workflow pings **on full success only**; a missing ping triggers an email/push. Catches "didn't run / disabled / skipped."
- Plus a **failure alert** (email step / ping-on-fail) to distinguish "ran but broke" from "didn't run."

**Scheduling:**
- Run **~05:30 UTC at an odd minute**, away from midnight/high-load — cron is routinely 10–30 min late (sometimes >1h) with no timing guarantee; the buffer ensures it's ready before the 8am read. UTC only (mind BST).
- Add `workflow_dispatch` for manual runs/testing.
- Keep the public repo active (workflow commits a tiny run-log each run) — **60 days of inactivity silently disables scheduled workflows**.

**No new episodes (normal):** maintain a processed-episode **state file (GUIDs)** in the private repo; diff feeds each run. Nothing new → skip, or send a one-line "nothing today." Same state prevents re-processing/double-emailing.

**Feed breakage:** wrap each feed **independently** — log & skip a bad one, continue with the rest. If a feed fails N runs running, flag it in the briefing footer so a genuinely dead feed gets noticed.

**Transcription:**
- Per-episode jobs + per-job `timeout-minutes` so a stuck job is killed, not left burning.
- **Cache the Whisper model** in the workflow — runtime download is slow and can fail outright.
- Medium model = accuracy/speed sweet spot (large rarely worth it).
- Seed Whisper's `initial_prompt` with a **domain glossary** (DESNZ, NESO, SSEP, Ofgem, CfD, Crown Estate, key surnames) to cut mis-hearing — improves the *raw* transcript, so verbatim quotes stay faithful (no LLM rewriting of quotes).
- Very long episodes: optional silence-aware ~10-min chunking + stitch (likely unnecessary with per-episode medium jobs).

**Gemini:**
- Free Flash (~15 RPM, ~1,500 req/day, 1M TPM) far exceeds our handful of daily calls — quota isn't the issue; but the shared free tier throws transient 429/503 at peak.
- **Exponential backoff with jitter**; retry only 429/500/503/504, never 400-class (that's a prompt bug to fix).
- If synthesis still fails after retries: **fall back** to emailing the raw new-episode list + transcript links, plus a failure alert — so something always arrives.
- Validate the structured output before sending; if it won't parse, retry once then fall back.
- Hallucination: verbatim-by-code already removes the worst risk; instruct Gemini to **omit anything it can't ground in the transcript** rather than guess.

---

## 10. Future (out of scope)

- A transcript-querying agent over the archive — the private archive (§7) is designed to enable it.

---

## Appendix A — Pre-build setup (do outside Claude Code)

**Accounts / credentials to have ready** (store them securely — e.g. a password manager; they go into GitHub Secrets later, never into the public repo):
- **GitHub account** — the public + private repos themselves get created during the build.
- **Gemini API key** — from Google AI Studio; free, no card required. Generate and save it.
- **Email-sending method** — simplest is a Gmail account with an *app password* for SMTP (needs 2FA on); or a free tier of a service like Resend. Pick one; keep the credential.
- **Healthchecks.io account** (or similar) — create one check, copy its ping URL (the dead-man's-switch from §9).

**No account needed:** Whisper is open-source — the script installs it. There is no "Whisper account" to create.

**High-leverage thinking to prepare** (only you can do these well, and they matter more than the plumbing):
- **Flesh out the briefer profile (§8)** — the artefact the system reads every morning to decide what clears the bar. The richer and more specific, the better the briefing.
- **Draft the domain glossary** for Whisper's prompt — acronyms, bodies, programmes and names (DESNZ, NESO, SSEP, Ofgem, CfD, allocation rounds, GB Energy, Crown Estate; current DESNZ + Treasury ministers/SpAds and the commentators you most want caught).
- **Write a one-page mock-up of your ideal briefing** — a worked example anchors the prompt far better than any description.
- *(Optional)* collect the podcast feed URLs.

**Leave for Claude Code:** the repo structure, all code and workflow files, GitHub Secrets wiring, the cross-repo token. Don't pre-write these — let them match what your course teaches and what Claude Code generates.

---

## Appendix B — Critical-review refinements & watch-outs

*Output of an adversarial pass over the spec. The Tier-1 fixes are folded into §5 and §7 above; the rest are build-time watch-outs and open decisions.*

**Conceptual — the biggest one (an expectations point, not a bug):** the highest-value target — *insider political signal specifically about the offshore/energy patch, at ministerial altitude* — is likely **sparse** in the source material. Westminster shows give politics with little energy; energy shows give energy with little gossip; the fusion the reader wants is genuinely rarer than the vision implies. Expect the briefing to skew to general political weather, with energy-specific gold intermittent. Mitigation: the worked example (`example-briefing.md`) sets a realistic bar, and having the output **visibly separate "energy signal" from "political weather"** stops sparse-energy days reading as failures.

**Will bite at build / in use:**
- **Volume vs the read.** The reader is fast and *prefers* richness, so lean generous — but a genuinely huge day could still overwhelm. If a control is ever needed, prefer a gentle relevance threshold on the low tier over hard caps, and keep the longer quotes where they're warranted.
- **Institutional-memory catch is the likeliest feature to underperform.** It isn't keyword-flagged and competes for prompt attention with signal-hunting; one prompt may squeeze it out. Give it an explicit instruction + example, and expect iteration.
- **Feed dedupe + junk filtering.** GUIDs can rotate or be unreliable — fall back to title+date for the processed-episode key. Feeds also carry trailers/bonus/members clips; filter them (e.g. skip very short items) or you'll transcribe and summarise noise.
- **Launch backfill — a decision to make.** Start empty, or seed the archive by transcribing the last ~month of each show? Backfill gives a richer first briefing and archive, but is a heavy one-off transcription burst (potentially 40–60 episodes).

**Minor / good to know:**
- **Timestamps vs ad insertion.** Dynamic ad insertion means your podcast app's timings may not match the downloaded file's, so "jump to 34:12" can drift. The transcript archive stays the ground truth.
- **Attribution ceiling & upgrade path.** Episode-level attribution is what you asked for; if speaker-level turns out to matter once you see real output, speaker diarization (whisperX / pyannote) is the upgrade, at a complexity cost.
- **Public-runner fair use.** Sustained heavy transcription on free public runners is legitimate (it's the repo's own project), but it's the one place the "zero cost" model is exposed if GitHub's terms ever change.
