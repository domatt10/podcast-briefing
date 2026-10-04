"""'In print' — under-the-radar online news for the daily briefing.

Same integrity contract as the podcasts, transposed: articles are split into
NUMBERED PARAGRAPHS; Gemini selects by paragraph ID and never returns quote
text; the code reconstitutes the exact paragraphs as the extended quote.

Two-stage selection keeps calls and context small:
  1. one call over all fresh headlines/standfirsts -> up to N ranked picks
  2. one call per pick over that article's numbered paragraphs -> quote IDs

Paywall posture (agreed with Dom): sources here are open-text; if a body
still can't be extracted, the item degrades to a headline flag + link.
BBC and Politico are deliberately absent — he reads those already; they
remain archive-only. Failure posture: the caller treats this stage as
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
                if not link or not e.get("published_parsed"):
                    continue
                when = datetime(*e.published_parsed[:6], tzinfo=timezone.utc)
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
    """
    marked = [c["url_hash"] for c in candidates if c.get("kind") != "research"]
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


def fetch_in_print(cfg: dict, archive: Path, state: dict) -> tuple[list[dict], list[str]]:
    """Returns (render-ready items, url_hashes of ALL candidates considered).
    The caller marks hashes seen only after a successful send, so held days
    re-consider the same stories tomorrow."""
    candidates = fetch_candidates(cfg, state)
    if not candidates:
        return [], []

    models = model_ladder(cfg["gemini"])

    profile = (ROOT / "profile.md").read_text(encoding="utf-8")
    listing = "\n".join(
        f"[{i}] {c['title']} | {c['source']} | {c['published']}"
        f"{' | RESEARCH' if c.get('kind') == 'research' else ''} | {c['summary']}"
        for i, c in enumerate(candidates)
    )
    data = _ask(
        models,
        SELECT_PROMPT.format(
            profile=profile,
            baseline=_baseline(),
            max_items=cfg["in_print"]["max_items"],
            listing=listing,
        ),
    )

    results, per_source = [], {}
    for pick in data.get("picks", []):
        if len(results) >= cfg["in_print"]["max_items"]:
            break
        ids = pick.get("ids")
        if not (isinstance(ids, list) and ids and all(isinstance(i, int) and 0 <= i < len(candidates) for i in ids)):
            continue
        item = candidates[ids[0]]
        # Hard backstop on the prompt's spread rule: no outlet takes over.
        cap = cfg["in_print"].get("max_per_source", 2)
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
            }
        )
    print(f"[in-print] {len(results)} item(s) selected from {len(candidates)} candidates")
    return results, hashes_to_mark(candidates, [r["url_hash"] for r in results])
