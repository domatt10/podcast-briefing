# Constituency Watch — Build Brief

**What this is.** A weekly *on-the-ground* digest for the coastal geographies and onshore grid corridors that matter to **offshore wind and tidal** deployment — catching the local signal the national tools miss: planning progress and objections, local MP positioning, community sentiment, port/supply-chain moves, and grid/pylon rows. **Scope is offshore wind and tidal only**; other local infrastructure is out. It deliberately sits **below** ministerial altitude — the landowner/enabler's ground-level view of whether leases actually get built.

**Reuses** the existing infrastructure: the public repo pipeline + free Actions minutes, Gemini synthesis, the private repo for storage, email delivery, and the news-ingestion pattern from the archive agent.

**The hard part is sources and filtering, not code** — so this brief leads with those, and with one important inversion.

---

## 0. The altitude inversion — read this first

Everything else you've built filters *up*, to ministerial altitude. **This product filters the opposite way.** The whole point is the local, granular detail the main briefing deliberately bins — a parish-council objection, a cable-landfall row, a port sub-contract, one MP's local campaign. If the shared briefer profile's altitude test leaks into this pipeline, it will strip out exactly the signal this exists to catch. So the prompt for this product must state plainly: **low altitude is the point here; keep the local minutiae — provided it relates to offshore wind or tidal.**

---

## 1. Sourcing (layered — the crux)

1. **Backbone — Google News RSS query feeds** (confirmed working in 2026). One tuned feed per *geography × topic*, using exact phrases and exclusions, UK-scoped (`&hl=en-GB&gl=GB&ceid=GB:en`). Free. ~100-item cap per feed, so keep queries **narrow and specific**. *(Google's ToS restricts public redisplay; ingesting privately into your own tool is the same personal-use posture as the transcripts — keep it in the private repo.)*
2. **Project pipeline — the Planning Inspectorate consenting register** (`national-infrastructure-consenting.planninginspectorate.gov.uk`). Every offshore-wind (and associated grid) DCO has a live page tracking it through examination to decision, with document libraries and examining-authority findings — the highest-signal, most structured source, and where local objections land. Watch the relevant project pages for stage changes and timetables.
3. **Regional & local news** — BBC regional RSS and the Local Democracy Reporting Service, plus a key local title or two per region.
4. **Community & campaign** — a curated handful of campaign sites and petitions. **Skip Facebook** (ToS-fraught and brittle).

---

## 2. Geographies (confirmed) & projects

- **Celtic Sea (floating, Round 5):** ports — Port Talbot, Milford Haven / Pembroke, Bristol Channel; South Wales + North Devon / Cornwall.
- **East Anglia (Southern North Sea):** Norfolk / Suffolk coast; the onshore cable + substation + pylon rows (Norwich–Tilbury / "East Anglia GREEN", Sea Link); North Falls, the East Anglia array.
- **Humber / Lincolnshire / Yorkshire:** Dogger Bank (incl. Dogger Bank South), Outer Dowsing, Hornsea; Grimsby / Immingham ports; onshore substation corridors.
- **Teesside / North East:** Teesworks / Able, supply chain and port/manufacturing.
- **North West / North Wales:** Morgan / Morecambe, Gwynt y Môr.
- **Scotland (low resolution):** major offshore-wind and tidal debates only — skip local Scottish planning minutiae.

**Projects:** track only insofar as they relate to **offshore wind or tidal** — the DCOs, ports, cable corridors and campaigns tied to those, not general infrastructure.

---

## 3. Signals — and what counts as one

Catch (all filtered to offshore wind / tidal): planning progress/objections & examination milestones · local MP positioning (distinct from PolicyMogul's formal feed) · community sentiment / opposition activity · port readiness, manufacturing, jobs and supply-chain · grid corridor rows (pylons, substations, landfall).

**Signal vs noise.** The feeds surface a lot of *activity* that isn't *signal* — PR, recruitment ads, "developer donates to local school", routine puff. Prioritise **change, conflict and decision**: an objection, a delay, a stage change, a political intervention, a new or scrapped development. Announcements rank below shifts.

**Tag the source type** so reliability is visible: *planning register* = authoritative; *local press* = reported; *campaign group* = advocacy (inherently one-sided). Don't launder a PR line or a campaign claim as neutral fact — the same fact-vs-spin discipline as the main briefing.

---

## 4. Output, cadence & the "what changed" thread

Local, offshore-specific signal is **sparse** — most weeks several geographies will have nothing. Design for that so it never reads as broken:

- **Lead with whatever there is**, not fixed empty sections. **Roll up quiet geographies into one line** ("Quiet this week: Teesside, North Wales") — absence, stated affirmatively, is itself information.
- **Cap per geography** so a noisy one (East Anglia's pylon rows will dominate) doesn't swamp the rest.
- **Track what changed since last week.** Keep a small state store of what's already been reported, so items read as *developments* — "now at examination", "opposition hardened", "new this week" — not disconnected snippets. The value is in escalation and change, which needs memory.
- **Affirmative DCO status line** — "no stage changes on the tracked projects this week" is reassuring signal, not a gap.
- **Cadence:** weekly by default, but given the sparsity, **fortnightly** or **event-triggered** (email only when something crosses a threshold) may fit better — try weekly first and lengthen if it's mostly quiet. If event-triggered, keep the dead-man's-switch so silence never reads as "is it broken?".
- **Email**, reusing the existing sender, standalone and separate from the daily briefing. Optionally also save items to `/news` so the archive agent can use them.

---

## 5. Build order (thin slice first)

1. Pick **2–3 priority geographies**, stand up their Google News query feeds, and produce a basic weekly digest. Confirm the signal is worth having before expanding.
2. Add the **Planning Inspectorate project-watch** for those geographies' offshore-wind/tidal DCOs.
3. Add **regional BBC / LDRS** + a key local title or two.
4. Expand to the full geography set; add community/campaign sites.

---

## 6. What needs you (Claude Code should walk you through each)

- Help **tune the Google News search strings**, and point to any specific campaign sites/petitions you want watched.
- Everything else reuses the existing build (repos, Gemini, Actions, email, news-ingestion).

---

## 7. Watch-outs

- **Sparse by nature** — especially tidal, which will be near-silent most weeks (few projects). Not broken, just quiet.
- **Clippings-pile risk** — without a firm signal-vs-activity filter and hard dedup (the same story echoes across BBC, local press, Google News and campaign sites), it degrades into repetitive PR.
- **Place-name false positives** — "Boston", "Barrow", "Morgan", "Sea Link" etc. will pull the wrong place or topic; scope queries with UK + disambiguating terms and expect ongoing tuning.
- **Community sentiment will underdeliver** — the richest sources (Facebook, local forums) are off-limits, so grassroots feeling comes only indirectly (petition numbers, campaign sites, press vox pops). Expect it thin.
- **Redundancy** — don't repeat national DESNZ news the main briefing already carries, or MP items PolicyMogul catches; stick to the *local* layer they miss.
- **Google News** — ToS restricts redisplay, ~100 items/feed → private repo, narrow queries.
- **Council planning portals** vary wildly and many lack feeds → optional later add, not core.
