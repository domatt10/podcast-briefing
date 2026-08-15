"""Per-episode summarisation via Gemini.

THE VERBATIM CONTRACT (spec §5): Gemini receives numbered transcript segments
and must reference passages by SEGMENT ID only. It never returns quote text —
code reconstitutes the exact words + timestamp from the IDs (render.py). If
the model handed back quotes as prose we'd get its tidied paraphrase, silently
defeating verbatim integrity. The validator below enforces the contract.

PER-EPISODE PROCESSING (spec §7): one episode per call. Attribution is stamped
by code from feed metadata, so the model cannot misattribute across episodes.

RETRY POLICY (spec §9): exponential backoff + jitter on 429/500/503/504 only.
A 400-class error is a prompt bug — fail fast so it gets fixed, never retried.
"""

import json
import random
import re
import time
from bisect import bisect_right
from datetime import date

from google import genai
from google.genai import errors

from config import ROOT

BASELINE_STALE_DAYS = 45  # nudge to re-verify baseline.md after a reshuffle etc.

STREAMS = (
    "energy_desnz",
    "crown_estate",
    "treasury_fiscal",
    "top_of_government",
    "parliamentary_colour",
)

RETRYABLE_CODES = {429, 500, 503, 504}
MAX_ATTEMPTS = 4

PROMPT = """You are the researcher for a private daily signals-and-speculation briefing on UK politics and energy. You are processing ONE podcast episode transcript, split into numbered segments. Your job is to select which segments matter to the reader described below — not to summarise the episode.

# The reader (this decides what clears the bar)

{profile}

# What the reader ALREADY KNOWS — do not report these back to him

{baseline}

This baseline is established fact. Podcasts lag events by days and love a recap,
so you will hear these facts discussed constantly. Discussion of something in the
"Settled" list is NOT a signal, however confidently or recently it is said:
someone explaining that there has been a change of Chancellor, or reacting to the
reshuffle, is telling this reader something he has known for weeks.

Include such material ONLY when it carries something genuinely additional:
- new information that CHANGES or contradicts the baseline (a further move, a
  reversal, a resignation),
- a consequence or intention not yet settled — what the new post-holder will
  actually DO, priorities shifting, money moving,
- an insider account of how or why it happened that is not already public.

If you strip the recap away and nothing is left, there is no item. Beware of
"why" lines that merely restate the baseline in different words.

# This episode (metadata from the podcast feed — trust it, don't infer)

Show: {show}
Episode: {title}
Published: {published}
Host/author per feed: {author}

# What to look for

Signals and speculation, with the reasoning given for any prediction: rumours, mood shifts, personnel chatter, money being switched on or off, machinery-of-government wiring. Reported fact is welcome as grounding. Also capture institutional-memory material: an insider explaining how government/industry actually works behind the scenes — include it even if only worth a line, flagged with "institutional_memory": true.

# Streams (assign each item to exactly one)

- energy_desnz — energy policy, DESNZ, ministers, clean power
- crown_estate — Crown Estate, seabed leasing, NESO, SSEP, grid/connections, Celtic Sea
- treasury_fiscal — Treasury/HMT mood music; deliberately a LOW bar, need not be energy-linked
- top_of_government — PM positioning, No 10, reshuffles, machinery of government
- parliamentary_colour — MPs, rebellions, opposition chatter; soft layer only

Standing rules: anything from a current or former energy/Treasury minister or SpAd is always in (identify by role, not name). Crown Estate lane items deserve detail. Predictions must carry their stated basis — put it in "why".

# THE CORE-PATCH EXEMPTION — read this before applying the altitude test

The reader's relevance test has two axes, altitude and proximity; apply them TOGETHER rather than as two separate hurdles. In his CORE ring — offshore/marine energy (offshore wind, floating wind, tidal, CCS, oil & gas transition) and the grid/system layer (NESO, SSEP, connections reform, zonal/REMA pricing, transmission charging, allocation rounds/CfD, seabed leasing, ports and supply chain) — the altitude bar is LOWER: he does not need it to have crossed a minister's desk, and specialist detail is welcome where general political shows can't give it to him.

But lower is not zero. The test that replaces altitude here is: **does it bear on whether and how projects actually get built, or on the commercial and political framework around them?** So IN: leasing and route-to-market, grid access and queues, the investment climate, government or regulator decisions and appetite, supply-chain capacity as a constraint on deployment, project timelines slipping or accelerating, who is lobbying whom.

OUT, even on his core topics: industry operational practice (training standards, HSE, crew transfer, vessel logistics), technical methodology, corporate and product announcements, conference throat-clearing, and general "the transition is important" commentary. An energy-industry podcast will be full of this — it is the industry talking shop, not signal. A specialist episode with no policy or commercial bearing is a legitimately EMPTY episode; say so by returning no items.

The altitude test bites hardest OUTSIDE the core ring: for Westminster process, party management and non-energy policy, keep requiring that it crosses a minister's desk or changes a decision-maker's mind.

# Tiering — a hierarchy, not a rating. Default to FRAGMENT.

Start every item as a fragment and promote it only if it clears a high bar. Roughly TWO THIRDS of your items should be fragments; a typical episode yields AT MOST 1-3 significant items, often zero.

Promote to "significant" only for: a genuinely new signal or shift, a prediction with its reasoning spelled out, an explicit disagreement between sources, substantive core-patch (offshore/grid) discussion, or an insider explaining how something really works.

Keep as "fragment": passing mentions, restatements of known news, routine reported fact, single-line colour, general commentary and opinion — however interesting. If you find yourself making a third or fourth item significant in one episode, it almost certainly belongs in the fragment tier.

# Volume ceiling

Return AT MOST 6 items from any one episode, and usually far fewer. You are selecting the signals a busy reader must not miss, not summarising the episode. If you have more than 6 candidates, keep only the strongest — and if an episode genuinely contains nothing that clears the bar, return no items at all. Zero is a common and correct answer, especially for specialist industry episodes.

# Style for "why" — plain English, spoken register

NEVER begin a "why" with "This ..." — no "This explains", "This provides", "This shows", "This highlights", "This indicates". Those describe the item instead of telling the reader the thing. Begin with the ACTOR and what they did or said: "The former chief whip explains how No 10 tracks wavering MPs", not "This provides institutional memory about whipping operations". Same for "The discussion covers ..." and "The government's approach involves ..." — say what actually happened.

# NAMING THE SPEAKER — the transcripts do not record who is talking

These transcripts have NO speaker labels. You are reading one undifferentiated stream of speech and often cannot tell which participant is talking. Guessing wrong puts words in a real person's mouth, and the reader may repeat it in a meeting.

**Attribute to the SHOW, not to a person.** "{show} expects the energy secretary to be moved", "{show} reports that the Treasury is blocking reforms", "{show} is told that ...". That is always accurate, because the show did carry it. A role also works where it reads better — "a host", "the guest", "a former Treasury official".

Use a person's NAME as the speaker ONLY when the text removes all doubt: the words identify them ("when I was chancellor I ..."), or someone addresses them by name and they answer, or the episode is plainly an interview with one named guest and the passage is clearly that guest answering.

NEVER pick between co-hosts. Shows like The Rest Is Politics, Political Currency, Politics At Sam and Anne's and The Rest Is Money have two or more regulars who cannot be told apart from the text — attribute to the show.

Naming people who are being DISCUSSED is always fine and encouraged ("{show} expects Burnham to move the energy secretary"). This rule is only about who is doing the speaking.

Write each "why" the way you'd flag it to a colleague out loud: short sentences, plain words, active voice. Unpack dense ideas rather than compressing them. No corporate or policy-memo language — never "provides insider context", "signals a shift", "landscape", "stakeholders", "prioritisation direction". Say who did what and why the reader should care. ("The host is inside government right now, running GB Energy's £1bn supply-chain fund" beats "Reveals he is currently seconded into government to lead the design and delivery of...").

# THE CARDINAL RULE — segment IDs only

Point to passages by their segment ID numbers. NEVER copy, quote, or rewrite transcript text in your response — the exact wording is reconstituted from your IDs by the pipeline. "segment_ids" must be a consecutive run covering the passage.

"segment_ids" MUST be an unbroken consecutive run — [41, 42, 43], never [41, 43, 45]. A quote is continuous speech; skipping segments would splice together things that were never said together. If the passage you want has irrelevant chat in the middle, either pick the tighter consecutive run that carries the point, or return two separate items.

"anchor" is the ONE exception to the no-copying rule, and it is not a quote: copy the first six to ten words of your FIRST segment exactly as they appear. It is a locator, never shown to the reader — the pipeline uses it to check your segment IDs really point at the passage you are describing, and to correct them if they don't. Getting it exactly right matters more than getting it short.

Prefer a passage that BEGINS AT THE START OF A SENTENCE. These transcripts are chopped into segments mid-flow, so check whether your first segment starts mid-sentence; if it does and the point survives, start one segment later or earlier so the quote opens cleanly.

Length: the reader is a fast reader who prefers richness, so there is no hard ceiling — give a significant passage the room it genuinely needs (commonly 3-12 segments, more when the material really warrants it). Start where the point starts and end where it lands.

Choose the passage where the point is made most CLEANLY. These are unscripted conversations: much of the talk is circling, filler and thinking aloud. Where a speaker makes the same point twice, take the tighter telling; prefer the run where they say the thing to the run where they are working up to it. A short, sharp passage beats a long, meandering one carrying the same content. Fragments should be SHORT — 1-3 segments, just enough to carry the line.

# Output — JSON only, exactly this shape

{{
  "guests": ["Jane Doe"],               // guests actually on THIS episode, from the metadata/description/discussion; [] if hosts only; never guess
  "topics": ["reshuffle", "Treasury restructure", "CfD budget"],   // 3-6 short tags for an episode index
  "items": [
    {{
      "tier": "significant",            // see tiering rule above: "significant" = the few items deserving a full verbatim passage; "fragment" = everything else (a flag plus a short verbatim snippet)
      "stream": "energy_desnz",         // one of the five streams above
      "why": "one plain-English line (see style rule): why this matters to this reader; include the stated basis of any prediction",
      "segment_ids": [41, 42, 43],
      "anchor": "the first six to ten words of segment 41, copied exactly",
      "institutional_memory": false
    }}
  ]
}}

Only include what you can ground in the segments below — omit anything you are unsure of rather than guessing. If nothing clears the bar, return "items": [] — a quiet episode is a normal, correct answer (still fill guests and topics).

# Transcript segments

{segments}
"""


def _format_segments(segments: list[dict]) -> str:
    return "\n".join(f"[{s['id']}] {s['text']}" for s in segments)


def _baseline() -> str:
    """Current-landscape file: what is already established, so recaps of it
    don't get reported back as news. Optional — absence must not break a run."""
    path = ROOT / "baseline.md"
    if not path.exists():
        return "(No baseline file — treat nothing as pre-established.)"
    text = path.read_text(encoding="utf-8")
    m = re.search(r"\*\*Last verified:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        age = (date.today() - date.fromisoformat(m.group(1))).days
        if age > BASELINE_STALE_DAYS:
            print(f"[summarise] WARNING: baseline.md last verified {age} days ago")
    return text


def build_prompt(transcript: dict) -> str:
    profile = (ROOT / "profile.md").read_text(encoding="utf-8")
    meta = transcript["metadata"]
    return PROMPT.format(
        profile=profile,
        baseline=_baseline(),
        show=meta["show"],
        title=meta["title"],
        published=meta["published"],
        author=meta["author"] or "(not given)",
        segments=_format_segments(transcript["segments"]),
    )


def _call_with_backoff(client, model: str, prompt: str) -> str:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"response_mime_type": "application/json", "temperature": 0.2},
            )
            return resp.text
        except errors.APIError as e:
            # A 429 carrying "limit: 0" means the model has NO free-tier quota
            # (Google reshuffled the tiers) — that's permanent, not transient:
            # stop immediately so the caller can try the fallback model.
            if "limit: 0" in str(e):
                raise
            if e.code not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS:
                raise
            wait = (2**attempt) + random.uniform(0, 2)
            print(f"[summarise] transient {e.code}, retry {attempt}/{MAX_ATTEMPTS - 1} in {wait:.0f}s")
            time.sleep(wait)


MIN_ANCHOR_CHARS = 18  # shorter locators match by accident


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def repair_anchors(items: list[dict], segments: list[dict]) -> dict:
    """Use each item's anchor to check — and if necessary CORRECT — its segment
    IDs, so a quote always contains the passage the note describes.

    The model gives us two independent things: what it means (the note plus a
    short locator) and where it thinks that is (segment IDs). When they disagree
    it is nearly always an indexing slip, so we trust the locator and re-point
    the quote. Nothing is ever dropped: an anchor we cannot find leaves the item
    exactly as it came, because a slightly mismatched item beats a missing one
    (Dom's call, 2026-08-15). The anchor is never shown to the reader — the quote
    is still reconstituted from real transcript segments either way.
    """
    seg_norm = [_norm(s["text"]) for s in segments]
    full, offsets, pos = [], [], 0
    for t in seg_norm:
        full.append(t)
        offsets.append(pos)
        pos += len(t) + 1
    haystack = " ".join(full)

    stats = {"ok": 0, "repaired": 0, "unlocatable": 0, "no_anchor": 0}
    for item in items:
        anchor = _norm(item.get("anchor") or "")
        if len(anchor) < MIN_ANCHOR_CHARS:
            stats["no_anchor"] += 1
            continue
        ids = item["segment_ids"]
        if anchor in " ".join(seg_norm[i] for i in ids if i < len(seg_norm)):
            stats["ok"] += 1
            continue
        at = haystack.find(anchor)
        if at < 0:
            stats["unlocatable"] += 1  # keep the item unchanged
            continue
        start = bisect_right(offsets, at) - 1
        item["segment_ids"] = list(range(start, min(start + len(ids), len(segments))))
        stats["repaired"] += 1
    return stats


MAX_SIGNIFICANT_PER_EPISODE = 3
FRAGMENT_SEGMENTS = 3
CORE_STREAMS = ("crown_estate", "energy_desnz")


def _enforce_tier_budget(items: list[dict]) -> list[dict]:
    """Cap full-quote items per episode, in code.

    The prompt asks for restraint and mostly gets it, but it drifts badly on
    some days (33 of 36 items came back "significant" on 2026-07-24), which
    flattens the hierarchy the reader skims by. Priority when choosing which
    keep the full treatment: his core patch first, then institutional memory,
    then the longest passages. Demoted items stay verbatim — their segment run
    is simply trimmed to a fragment-sized opening.
    """
    sig = [i for i in items if i["tier"] == "significant"]
    if len(sig) <= MAX_SIGNIFICANT_PER_EPISODE:
        return items
    ranked = sorted(
        sig,
        key=lambda i: (
            i["stream"] in CORE_STREAMS,
            i.get("institutional_memory", False),
            len(i["segment_ids"]),
        ),
        reverse=True,
    )
    for item in ranked[MAX_SIGNIFICANT_PER_EPISODE:]:
        item["tier"] = "fragment"
        item["segment_ids"] = item["segment_ids"][:FRAGMENT_SEGMENTS]
    print(f"[summarise] tier budget: {len(sig)} significant -> {MAX_SIGNIFICANT_PER_EPISODE}")
    return items


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


def _validate(raw: str, n_segments: int) -> dict:
    """Enforce the output contract; drop (and count) malformed items.
    Returns {"items": [...], "guests": [...], "topics": [...]}."""
    data = json.loads(raw)
    items, reasons = [], []
    for item in data.get("items", []):
        ids = item.get("segment_ids")
        why = None
        if item.get("tier") not in ("significant", "fragment"):
            why = "bad tier"
        elif item.get("stream") not in STREAMS:
            why = "bad stream"
        elif not isinstance(item.get("why"), str):
            why = "no why"
        elif not (isinstance(ids, list) and ids and all(isinstance(i, int) and 0 <= i < n_segments for i in ids)):
            why = "bad ids"
        elif ids != list(range(ids[0], ids[-1] + 1)):
            # Gaps break verbatim integrity — splicing non-adjacent speech would
            # misrepresent it. Salvage the longest consecutive run instead of
            # binning the item (a whole episode was lost to this, 2026-07-25).
            best = cur = [ids[0]]
            for prev, nxt in zip(ids, ids[1:]):
                cur = cur + [nxt] if nxt == prev + 1 else [nxt]
                if len(cur) > len(best):
                    best = cur
            item["segment_ids"] = best
            reasons.append(f"gapped ids -> salvaged {len(best)}/{len(ids)}")
        if why:
            reasons.append(why)
            continue
        item["institutional_memory"] = bool(item.get("institutional_memory", False))
        item["anchor"] = item.get("anchor") if isinstance(item.get("anchor"), str) else ""
        items.append(item)
    if reasons:
        print(f"[summarise] item issues: {', '.join(reasons)}")
    items = _enforce_tier_budget(items)
    return {
        "items": items,
        "guests": _str_list(data.get("guests")),
        "topics": _str_list(data.get("topics")),
    }


CLUSTER_PROMPT = """Below are items selected from several podcast episodes recorded around the same time, for one reader's daily briefing. Different shows often cover the SAME story — your job is to group those together so the reader sees each story once, with all its sources.

Group two items only if they are about the SAME underlying story or claim (e.g. both about who will be Chancellor, both about the same funding decision). Do NOT group items that merely share a topic area (two unrelated Treasury items stay separate).

Return JSON only. List only genuine groups of 2 or more; ungrouped items are assumed singletons:
{{"groups": [[3, 7, 11], [2, 5]]}}

# Items
{listing}
"""


def cluster_items(flat: list[tuple[dict, dict]], gemini_cfg: dict) -> list[list[int]]:
    """Group indices of items that cover the same story across episodes.

    Returns a list of groups covering every index exactly once (singletons
    included), in the original order. Any failure degrades to all-singletons,
    i.e. today's behaviour.
    """
    singletons = [[i] for i in range(len(flat))]
    if len(flat) < 2:
        return singletons

    listing = "\n".join(
        f"[{i}] ({t['metadata']['show']}) {item['why']}" for i, (item, t) in enumerate(flat)
    )
    models = [gemini_cfg["model"]]
    if gemini_cfg.get("fallback_model") and gemini_cfg["fallback_model"] not in models:
        models.append(gemini_cfg["fallback_model"])

    client = genai.Client()
    raw = None
    for model in models:
        try:
            raw = _call_with_backoff(client, model, CLUSTER_PROMPT.format(listing=listing))
            break
        except errors.APIError as e:
            print(f"[cluster] {model} failed ({e.code})")
    if raw is None:
        print("[cluster] unavailable - treating all items as separate")
        return singletons

    try:
        groups = json.loads(raw).get("groups", [])
    except json.JSONDecodeError:
        print("[cluster] unparseable response - treating all items as separate")
        return singletons

    used, out = set(), []
    for g in groups:
        if not isinstance(g, list):
            continue
        members = [i for i in g if isinstance(i, int) and 0 <= i < len(flat) and i not in used]
        if len(members) < 2:
            continue  # a "group" of one adds nothing
        used.update(members)
        out.append(sorted(members))
    # Everything the model didn't group stays a singleton, original order kept.
    result = []
    for i in range(len(flat)):
        if i in used:
            grp = next((g for g in out if g[0] == i), None)
            if grp:
                result.append(grp)
        else:
            result.append([i])
    merged = sum(len(g) - 1 for g in result)
    print(f"[cluster] {len(flat)} item(s) -> {len(result)} story/stories ({merged} duplicate(s) merged)")
    return result


TOP_LINE_PROMPT = """You pick the top line of a daily signals briefing for this reader: an External Affairs & Policy Manager at The Crown Estate focused on offshore wind — he cares most about ministerial-altitude signals touching energy, the Treasury's mood on big capital projects, and the machinery of government.

Below are today's significant items (one line each, with the show they came from). Choose the 2-4 MOST significant for this reader. Return JSON only: {{"top": [list of item numbers, most significant first]}}

{candidates}
"""


def select_top_line(stories: list[dict], gemini_cfg: dict) -> list[tuple[dict, dict]]:
    """Pick the briefing's top line from the deduped stories' primaries.

    Selection only — items are referenced by index, never rewritten. With four
    or fewer candidates code picks them all and no model call happens; any
    model failure falls back to the first four.
    """
    candidates = [s["primary"] for s in stories if s["primary"][0]["tier"] == "significant"]
    if len(candidates) <= 4:
        return candidates

    listing = "\n".join(
        f"{i}. {item['why']} ({t['metadata']['show']})" for i, (item, t) in enumerate(candidates)
    )
    try:
        client = genai.Client()
        raw = _call_with_backoff(
            client, gemini_cfg["model"], TOP_LINE_PROMPT.format(candidates=listing)
        )
        picks = json.loads(raw)["top"]
        picks = [i for i in picks if isinstance(i, int) and 0 <= i < len(candidates)]
        seen: list[int] = []
        for i in picks:
            if i not in seen:
                seen.append(i)
        if 2 <= len(seen) <= 4:
            return [candidates[i] for i in seen]
    except (errors.APIError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[top-line] selection failed ({type(e).__name__}) - using first four")
    return candidates[:4]


def summarise(transcript: dict, gemini_cfg: dict) -> dict:
    """One episode in → {"items": [...], "guests": [...], "topics": [...]}.
    Items carry segment IDs, never quote text.

    Tries the configured model, then the fallback model — Google reshuffles
    which models the free tier includes, and the briefing must survive that.
    """
    client = genai.Client()  # reads GEMINI_API_KEY from the environment
    prompt = build_prompt(transcript)
    n = len(transcript["segments"])

    models = [gemini_cfg["model"]]
    fallback = gemini_cfg.get("fallback_model")
    if fallback and fallback not in models:
        models.append(fallback)

    # Each model gets two attempts; a bad-JSON retry must fall through to the
    # fallback model, not escape (it used to, costing the whole episode).
    last_error: Exception | None = None
    for model in models:
        for attempt in (1, 2):
            try:
                print(f"[summarise] calling {model} ({n} segments)")
                result = _validate(_call_with_backoff(client, model, prompt), n)
                stats = repair_anchors(result["items"], transcript["segments"])
                if stats["repaired"] or stats["unlocatable"]:
                    print(
                        f"[summarise] anchors: {stats['ok']} ok, {stats['repaired']} re-pointed, "
                        f"{stats['unlocatable']} unlocatable (kept as-is), {stats['no_anchor']} missing"
                    )
                return result
            except (json.JSONDecodeError, AttributeError, TypeError) as e:
                print(f"[summarise] {model}: unparseable response (attempt {attempt})")  # spec §9
                last_error = e
            except errors.APIError as e:
                print(f"[summarise] {model} failed ({e.code})")
                last_error = e
                break  # API-level failure: go straight to the next model
    raise last_error
