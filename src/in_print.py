"""'In print' — under-the-radar online news for the daily briefing.

Same integrity contract as the podcasts, transposed: articles are split into
NUMBERED PARAGRAPHS; Gemini selects by paragraph ID and never returns quote
text; the code reconstitutes the exact paragraphs as the extended quote.

Two-stage selection keeps calls and context small:
  1. one call over all fresh headlines/standfirsts -> up to N ranked picks
  2. one call per pick over that article's numbered paragraphs -> quote IDs

Paywall posture: sources here are open-text; if a body still can't be
extracted, the item degrades to a headline flag + link. BBC and Politico are
deliberately absent — the reader already sees those directly, so they stay
archive-only. Failure posture: the caller treats this stage as
non-fatal; nothing here may sink the briefing.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup

from config import ROOT
from news import _article_text
from summarise import _baseline, _call_with_backoff, genai, model_ladder

MIN_BODY_CHARS = 400  # below this we can't honestly offer an "extended quote"

SELECT_PROMPT = """You pick items for the "In print" section of a private daily political briefing. The reader:

{profile}

# What he already knows — do not pick pieces that just report these

{baseline}

Commentary reacting to the settled facts above is not news to him. Pick such a
piece only if it adds something the baseline doesn't already give him: what a new
post-holder will actually do, a consequence still unsettled, or insider detail.

# The mission of this section
Catch what would OTHERWISE SLIP UNDER HIS RADAR. He already reads Politico Playbook and the mainstream front pages, and gets formal parliamentary monitoring elsewhere.

THE TEST IS WHAT A PIECE ADDS, NOT HOW BIG THE STORY IS. Don't pick a piece that just retells what Politico and the front pages have already given him. But prominence alone never disqualifies a piece: if it adds something beyond the news account, it is in, however saturated the coverage. Adding something means a number, a mechanism, a consequence still unsettled, insider detail, what a post-holder will actually do, or an explanation of how something really works. Research on the week's biggest story is usually MORE use to him than research on a quiet one. If you strip out what he already knows and nothing is left, there is no pick.

Prioritise: energy/DESNZ and Treasury signal, machinery-of-government insight, party-internal mood (ConservativeHome and LabourList show what each party is telling itself), and institutional-memory explainers. Comment pieces are fine when they reveal positioning or explain how something actually works — the note should say what the piece SIGNALS, not just what it says.

# Research and reports
Candidates tagged RESEARCH are think tank and institute output, not journalism. Judge them differently:
- The value is the FINDING, not the positioning. Your note should say what the work actually concludes — the number, the mechanism, the consequence for his patch — never what publishing it signals politically. "The IFS finds the saving is real but can't fund social care" is useful; "the IFS is positioning itself against the plan" is not.
- Prefer research that settles a contested number or changes a decision over research that restates a known position.
- Every candidate shows its publication date. Research is listed for longer than news because a report keeps its value: an older report is still worth picking if it is genuinely significant and he is unlikely to have seen it, but where two items are of equal value take the newer one.
- These feeds also carry recruitment notices, event listings, annual reviews, press-clipping pages and staff profiles. Those are never signal. Skip them.

# Rules
- Group duplicate coverage of one story into a single pick (all its ids, best-sourced first).
- Up to {max_items} picks, ranked most significant first. Fewer is fine. Zero is a normal answer.
- Never invent facts not present in the headline/standfirst.
- SPREAD YOUR PICKS. Party-political commentary is plentiful and tends to crowd out everything else; energy, industry and machinery-of-government pieces are rarer and worth more to this reader. Where an energy or infrastructure item is close in value to a party-political one, take the energy item. Avoid taking more than two picks from any single outlet.

Return JSON only:
{{"picks": [{{"ids": [3], "why": "one plain-English line, spoken register — what it says and why he should care"}}]}}

# Candidates
{listing}
"""

NATURE_SELECT_PROMPT = """You pick items for the MARINE NATURE part of a private daily briefing. The reader:

{profile}

# What he already knows — do not pick pieces that just report these

{baseline}

# The bar for this section

He works on offshore wind at The Crown Estate and now advises colleagues on marine nature. He is a GENERALIST ADVISING SPECIALISTS: he needs enough to follow the debate and notice when something has changed, never enough to replicate an expert's work.

For every candidate ask: **would a specialist colleague expect him to already know this?** If only a specialist would track it, it is OUT. Zero picks is a normal and common answer.

Pick an item if it passes ANY ONE of these:

1. POLITICAL SIGNALLING ON NATURE — Defra's direction of travel, the nature-versus-growth tension, how government weighs nature against energy, housing and infrastructure, shifts in ministerial language or priority, money switched on or off.

2. MARINE NATURE POLICY AND REGULATION — wide on topic: Marine Protected Areas, Habitats Regulations and environmental compensation, the Marine Recovery Fund, Marine Net Gain, bottom trawling, 30x30, Good Environmental Status, and the statutory nature conservation bodies (Natural England, Natural Resources Wales, JNCC) including their capacity, reform or abolition. NARROW on what counts: a decision, a reversal, a direction of travel, a fight.

3. NATURE CAPITAL MARKETS — judged on whether it MOVES THE MARKET, not on altitude. A standard or code landing at all and what it unlocks; a first-of-kind transaction; a new fund or vehicle; a serious buyer arriving or leaving; a credible failure.

# Out, specifically

- THE CROWN ESTATE'S OWN ANNOUNCEMENTS. He sees those internally first. But a third party REACTING TO or DISCUSSING Crown Estate nature work IS in — what others say about his organisation is a signal, what it says about itself is not.
- Individual restoration projects (an oyster reef, a seagrass trial) unless they set a precedent, carry a genuine first, or are being used to make a wider argument.
- Terrestrial nature policy, UNLESS there is a marine read-across (Biodiversity Net Gain and Local Nature Recovery Strategies are the precedents marine mechanisms get built from) or it signals government's general posture toward nature.
- Species and conservation interest with no policy, market or commercial bearing. State-of-nature reporting and wildlife features are not this section.
- The mechanics of things: how a methodology works, consultation procedure, practitioner debate about measurement, incremental code revisions. THAT a code exists is news; its version history is not.
- Press-release throat-clearing, appointments, events, award announcements.

# Rules
- Group duplicate coverage of one story into a single pick (all its ids, best-sourced first).
- Up to {max_items} picks, ranked most significant first. Fewer is better than padding. Zero is normal.
- Never invent facts not present in the headline or standfirst.

Return JSON only:
{{"picks": [{{"ids": [3], "why": "one plain-English line, spoken register — what it says and why he should care"}}]}}

# Candidates
{listing}
"""

QUOTE_PROMPT = """From the numbered paragraphs below, choose the passage — 1 to 4 CONSECUTIVE paragraphs — that best delivers this signal to the reader: {why}

If this is research output, take the passage that states the finding most precisely — the number, the conclusion, the mechanism — not the framing or the call to action around it.

THE CARDINAL RULE: never copy, rewrite or quote the text back. Return paragraph numbers only; the exact wording is reconstituted from your IDs by the pipeline.

Return JSON only: {{"paragraph_ids": [2, 3], "why": "optionally sharpened one-line note — plain English, spoken register, about what the STORY signals for the reader; never describe the paragraphs or the quote itself"}}

# {title} — {source}
{paragraphs}
"""


def _ask(models: list[str], prompt: str) -> dict:
    """Model ladder + parse-retry, same posture as the other pipelines."""
    client = genai.Client()
    last_err = None
    for model in models:
        try:
            raw = _call_with_backoff(client, model, prompt)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                print(f"[in-print] unparseable JSON from {model} - retrying once")
                return json.loads(_call_with_backoff(client, model, prompt))
        except Exception as e:
            print(f"[in-print] {model} failed ({type(e).__name__})")
            last_err = e
    raise last_err


def _feed_body(entry) -> str:
    """Full text from the feed itself (content:encoded / atom content), if any."""
    for c in entry.get("content", []):
        html = c.get("value", "")
        if html:
            soup = BeautifulSoup(html, "html.parser")
            paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
            text = "\n\n".join(p for p in paras if len(p) > 40)
            if not text:  # content without <p> structure
                text = soup.get_text("\n", strip=True)
            return text
    return ""


def _paragraphs(body: str) -> list[str]:
    return [p.strip() for p in body.split("\n\n") if len(p.strip()) > 40]


def clean_title(raw: str, source_title: str) -> str:
    """Strip the ' - <Publisher>' suffix Google News appends to every title.

    Pure padding in the candidate listing — the source is already shown in its
    own column — and it would otherwise eat into the model's view of 25-odd
    headlines at once.
    """
    suffix = f" - {source_title}"
    if source_title and raw.endswith(suffix):
        return raw[: -len(suffix)].strip() or raw
    return raw


def fetch_candidates(cfg: dict, state: dict) -> list[dict]:
    """Fresh, unseen items across all print feeds.

    Research feeds carry a longer lookback than daily commentary, because a
    report keeps its value for days and a comment piece does not.
    """
    now = datetime.now(timezone.utc)
    windows = {
        "commentary": timedelta(hours=cfg["in_print"]["lookback_hours"]),
        "research": timedelta(hours=cfg["in_print"].get("research_lookback_hours", 168)),
        "nature": timedelta(hours=cfg["in_print"].get("nature_lookback_hours", 168)),
    }
    seen = state.setdefault("print_seen", {})
    items = []
    for feed_cfg in cfg.get("print_feeds", []):
        kind = feed_cfg.get("kind", "commentary")
        cutoff = now - windows.get(kind, windows["commentary"])
        try:
            parsed = feedparser.parse(feed_cfg["url"])
            fresh = 0
            for e in parsed.entries:
                link = e.get("link", "")
                # gov.uk atom feeds carry <updated> and no <published>. Without
                # this fallback they parse perfectly and yield zero items every
                # time - a feed that looks healthy in the log and silently
                # delivers nothing. A re-issued page still surfaces only once,
                # because the dedupe hash below is on the URL.
                stamp = e.get("published_parsed") or e.get("updated_parsed")
                if not link or not stamp:
                    continue
                when = datetime(*stamp[:6], tzinfo=timezone.utc)
                if when < cutoff:
                    continue
                h = hashlib.sha256(link.encode()).hexdigest()[:12]
                if h in seen:
                    continue
                summary = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ", strip=True)
                items.append(
                    {
                        "source": feed_cfg["name"],
                        "kind": kind,
                        "headline_only": bool(feed_cfg.get("headline_only")),
                        "title": clean_title(
                            e.get("title", "(untitled)").strip(),
                            (e.get("source") or {}).get("title", ""),
                        ),
                        "url": link,
                        "published": when.date().isoformat(),
                        "summary": summary[:280],
                        "body": _feed_body(e),
                        "url_hash": h,
                    }
                )
                fresh += 1
            print(f"[in-print] {feed_cfg['name']} ({kind}): {fresh} fresh")
        except Exception as e:
            print(f"[in-print] {feed_cfg['name']} FAILED ({type(e).__name__}) - skipping")
    return items


CONSENT_MARKERS = (
    "we use cookies",
    "cookies and data",
    "accept all",
    "reject all",
    "manage your privacy",
    "privacy settings",
    "before you continue",
    "enable javascript",
    "please enable cookies",
)


def _looks_like_boilerplate(body: str) -> bool:
    """True when extraction returned a consent wall rather than an article.

    This guards the quote stage, so it guards the project's central promise.
    Found while testing Google News links: they redirect to consent.google.com
    and extraction returns ~900 characters of cookie policy — comfortably over
    MIN_BODY_CHARS, so the quote stage would have turned Google's cookie notice
    into an "extended quote" attributed to the Institute for Fiscal Studies.
    Any consent-walled publisher can do the same, which is why this applies to
    every feed rather than to one tier.

    Two markers required: a genuine article about cookie law could plausibly
    use one of these phrases, but not two in its opening few hundred words.
    """
    head = body[:600].lower()
    return sum(marker in head for marker in CONSENT_MARKERS) >= 2


def hashes_to_mark(candidates: list[dict], delivered: list[str]) -> list[str]:
    """Which candidates count as 'seen' once the briefing has gone out.

    Commentary is one-shot: it was considered, and tomorrow it is yesterday's
    news either way. Research is NOT. An unselected report keeps its place in
    the pool for its longer window, because a significant report that loses out
    to a busy news day deserves another look rather than being discarded for
    good — which is what used to happen to everything.

    Nature works the same way, for the same reason and one more: the lane has
    only three slots, so crowding out is the normal case rather than the
    exception.
    """
    marked = [c["url_hash"] for c in candidates if c.get("kind") not in ("research", "nature")]
    marked += [h for h in delivered if h not in marked]
    return marked


def _ensure_body(item: dict) -> str:
    if len(item.get("body", "")) >= MIN_BODY_CHARS:
        return item["body"]
    try:
        fetched = _article_text(item["url"])
        if _looks_like_boilerplate(fetched):
            print(f"[in-print] consent wall, not an article: {item['source']} - flagging only")
            fetched = ""
        item["body"] = fetched
    except Exception:
        pass
    return item.get("body", "")


def _listing(pool: list[dict]) -> str:
    return "\n".join(
        f"[{i}] {c['title']} | {c['source']} | {c['published']}"
        f"{' | RESEARCH' if c.get('kind') == 'research' else ''} | {c['summary']}"
        for i, c in enumerate(pool)
    )


def _realise(data, pool, cfg, archive, models, max_items, cap, lane):
    """Turn one selection call's picks into render-ready items.

    Shared by the general and nature passes so the two cannot drift apart in
    quote handling, source capping or archiving.
    """
    results, per_source = [], {}
    for pick in data.get("picks", []):
        if len(results) >= max_items:
            break
        ids = pick.get("ids")
        if not (isinstance(ids, list) and ids and all(isinstance(i, int) and 0 <= i < len(pool) for i in ids)):
            continue
        item = pool[ids[0]]
        # Hard backstop on the prompt's spread rule: no outlet takes over.
        if per_source.get(item["source"], 0) >= cap:
            print(f"[in-print] skipping extra item from {item['source']} (source cap {cap})")
            continue
        per_source[item["source"]] = per_source.get(item["source"], 0) + 1
        why = pick.get("why", "").strip() or item["title"]
        # headline_only sources are aggregator links: following them fetches a
        # consent page, not the piece. Skip extraction entirely rather than
        # relying on the boilerplate guard to catch it afterwards.
        body = "" if item["headline_only"] else _ensure_body(item)
        quote = None
        if len(body) >= MIN_BODY_CHARS:
            paras = _paragraphs(body)
            try:
                q = _ask(
                    models,
                    QUOTE_PROMPT.format(
                        why=why,
                        title=item["title"],
                        source=item["source"],
                        paragraphs="\n".join(f"[{i}] {p}" for i, p in enumerate(paras)),
                    ),
                )
                pids = q.get("paragraph_ids")
                if (
                    isinstance(pids, list)
                    and pids
                    and all(isinstance(i, int) and 0 <= i < len(paras) for i in pids)
                    and pids == list(range(pids[0], pids[-1] + 1))
                    and len(pids) <= 4
                ):
                    quote = "\n\n".join(paras[i] for i in pids)
                    if isinstance(q.get("why"), str) and q["why"].strip():
                        why = q["why"].strip()
            except Exception as e:
                print(f"[in-print] quote stage failed for one item ({type(e).__name__}) - flag only")

        # Archive the selected article for the agent (reported-fact tree).
        dest = archive / "news" / "in-print" / f"{item['published']}_{item['url_hash'][:8]}.md"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            note = (
                "- **Full text:** not captured — aggregator link, headline and "
                "snippet only\n"
                if item["headline_only"]
                else ""
            )
            dest.write_text(
                f"# {item['title']}\n\n- **Source:** {item['source']} (reported news / analysis)\n"
                f"- **Date:** {item['published']}\n- **URL:** {item['url']}\n{note}"
                f"- **Briefing note:** {why}\n\n{body or item['summary']}\n",
                encoding="utf-8",
            )

        results.append(
            {
                "why": why,
                "quote": quote,
                "source": item["source"],
                "title": item["title"],
                "url": item["url"],
                "published": item["published"],
                "url_hash": item["url_hash"],  # so a delivered research item is marked seen
                "lane": lane,                  # "nature" items render under their own label
            }
        )
    return results


def fetch_in_print(cfg: dict, archive: Path, state: dict) -> tuple[list[dict], list[str]]:
    """Returns (render-ready items, url_hashes of ALL candidates considered).
    The caller marks hashes seen only after a successful send, so held days
    re-consider the same stories tomorrow.

    TWO SELECTION PASSES, each with its own budget. Nature sources joined a
    section that already had six slots and fourteen feeds. A single pass would
    have made nature and politics compete for the same slots: on a busy
    political day nature would never place, and on a quiet one it would crowd
    out the politics. One extra model call a day is cheap against a ladder
    carrying ~100, and separate budgets mean a quiet nature week simply yields
    less rather than padding itself to fill slots.
    """
    candidates = fetch_candidates(cfg, state)
    if not candidates:
        return [], []

    models = model_ladder(cfg["gemini"])
    profile = (ROOT / "profile.md").read_text(encoding="utf-8")
    baseline = _baseline()
    c = cfg["in_print"]

    nature_pool = [x for x in candidates if x.get("kind") == "nature"]
    general_pool = [x for x in candidates if x.get("kind") != "nature"]

    results = []
    if general_pool:
        data = _ask(models, SELECT_PROMPT.format(
            profile=profile, baseline=baseline,
            max_items=c["max_items"], listing=_listing(general_pool)))
        results += _realise(data, general_pool, cfg, archive, models,
                            c["max_items"], c.get("max_per_source", 2), "general")
    if nature_pool:
        data = _ask(models, NATURE_SELECT_PROMPT.format(
            profile=profile, baseline=baseline,
            max_items=c.get("nature_max_items", 3), listing=_listing(nature_pool)))
        results += _realise(data, nature_pool, cfg, archive, models,
                            c.get("nature_max_items", 3),
                            c.get("nature_max_per_source", 2), "nature")

    print(f"[in-print] {len(results)} item(s) selected from "
          f"{len(general_pool)} general / {len(nature_pool)} nature candidates")
    return results, hashes_to_mark(candidates, [r["url_hash"] for r in results])
