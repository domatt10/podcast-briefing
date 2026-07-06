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
import time

from google import genai
from google.genai import errors

from config import ROOT

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

# Style for "why" — plain English, spoken register

Write each "why" the way you'd flag it to a colleague out loud: short sentences, plain words, active voice. Unpack dense ideas rather than compressing them. No corporate or policy-memo language — never "provides insider context", "signals a shift", "landscape", "stakeholders", "prioritisation direction". Say who did what and why the reader should care. ("The host is inside government right now, running GB Energy's £1bn supply-chain fund" beats "Reveals he is currently seconded into government to lead the design and delivery of...").

# THE CARDINAL RULE — segment IDs only

Point to passages by their segment ID numbers. NEVER copy, quote, or rewrite transcript text in your response — the exact wording is reconstituted from your IDs by the pipeline. "segment_ids" must be a consecutive run covering the passage (significant items typically 2-10 segments; fragments 1-2).

# Output — JSON only, exactly this shape

{{
  "guests": ["Jane Doe"],               // guests actually on THIS episode, from the metadata/description/discussion; [] if hosts only; never guess
  "topics": ["reshuffle", "Treasury restructure", "CfD budget"],   // 3-6 short tags for an episode index
  "items": [
    {{
      "tier": "significant",            // "significant" = worth a verbatim passage; "fragment" = one-line flag
      "stream": "energy_desnz",         // one of the five streams above
      "why": "one plain-English line (see style rule): why this matters to this reader; include the stated basis of any prediction",
      "segment_ids": [41, 42, 43],
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


def build_prompt(transcript: dict) -> str:
    profile = (ROOT / "profile.md").read_text(encoding="utf-8")
    meta = transcript["metadata"]
    return PROMPT.format(
        profile=profile,
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


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]


def _validate(raw: str, n_segments: int) -> dict:
    """Enforce the output contract; drop (and count) malformed items.
    Returns {"items": [...], "guests": [...], "topics": [...]}."""
    data = json.loads(raw)
    items, dropped = [], 0
    for item in data.get("items", []):
        ids = item.get("segment_ids")
        ok = (
            item.get("tier") in ("significant", "fragment")
            and item.get("stream") in STREAMS
            and isinstance(item.get("why"), str)
            and isinstance(ids, list)
            and ids
            and all(isinstance(i, int) and 0 <= i < n_segments for i in ids)
            and ids == list(range(ids[0], ids[-1] + 1))  # consecutive run
        )
        if ok:
            item["institutional_memory"] = bool(item.get("institutional_memory", False))
            items.append(item)
        else:
            dropped += 1
    if dropped:
        print(f"[summarise] dropped {dropped} malformed item(s)")
    return {
        "items": items,
        "guests": _str_list(data.get("guests")),
        "topics": _str_list(data.get("topics")),
    }


TOP_LINE_PROMPT = """You pick the top line of a daily signals briefing for this reader: an External Affairs & Policy Manager at The Crown Estate focused on offshore wind — he cares most about ministerial-altitude signals touching energy, the Treasury's mood on big capital projects, and the machinery of government.

Below are today's significant items (one line each, with the show they came from). Choose the 2-4 MOST significant for this reader. Return JSON only: {{"top": [list of item numbers, most significant first]}}

{candidates}
"""


def select_top_line(episodes: list[dict], gemini_cfg: dict) -> list[tuple[dict, dict]]:
    """Pick the briefing's top line from all episodes' significant items.

    Selection only — items are referenced by index, never rewritten. With four
    or fewer candidates code picks them all and no model call happens; any
    model failure falls back to the first four.
    """
    candidates = [
        (item, ep["transcript"])
        for ep in episodes
        for item in ep["items"]
        if item["tier"] == "significant"
    ]
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

    last_error: Exception | None = None
    for model in models:
        try:
            print(f"[summarise] calling {model} ({n} segments)")
            raw = _call_with_backoff(client, model, prompt)
            try:
                return _validate(raw, n)
            except (json.JSONDecodeError, AttributeError, TypeError):
                print("[summarise] unparseable response, retrying once")  # spec §9
                raw = _call_with_backoff(client, model, prompt)
                return _validate(raw, n)
        except errors.APIError as e:
            print(f"[summarise] {model} failed ({e.code}); trying next model" if model != models[-1] else f"[summarise] {model} failed ({e.code})")
            last_error = e
    raise last_error
