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
from summarise import _call_with_backoff, genai

MIN_BODY_CHARS = 400  # below this we can't honestly offer an "extended quote"

SELECT_PROMPT = """You pick items for the "In print" section of a private daily political briefing. The reader:

{profile}

# The mission of this section
Catch what would OTHERWISE SLIP UNDER HIS RADAR. He already reads Politico Playbook and the mainstream front pages, and gets formal parliamentary monitoring elsewhere — never pick a story those would carry prominently. Prioritise: energy/DESNZ and Treasury signal, machinery-of-government insight, party-internal mood (ConservativeHome and LabourList show what each party is telling itself), and institutional-memory explainers. Comment pieces are fine when they reveal positioning or explain how something actually works — the note should say what the piece SIGNALS, not just what it says.

# Rules
- Group duplicate coverage of one story into a single pick (all its ids, best-sourced first).
- Up to {max_items} picks, ranked most significant first. Fewer is fine. Zero is a normal answer.
- Never invent facts not present in the headline/standfirst.

Return JSON only:
{{"picks": [{{"ids": [3], "why": "one plain-English line, spoken register — what it says and why he should care"}}]}}

# Candidates
{listing}
"""

QUOTE_PROMPT = """From the numbered paragraphs below, choose the passage — 1 to 4 CONSECUTIVE paragraphs — that best delivers this signal to the reader: {why}

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


def fetch_candidates(cfg: dict, state: dict) -> list[dict]:
    """Fresh, unseen items across all print feeds."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=cfg["in_print"]["lookback_hours"])
    seen = state.setdefault("print_seen", {})
    items = []
    for feed_cfg in cfg.get("print_feeds", []):
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
                        "title": e.get("title", "(untitled)").strip(),
                        "url": link,
                        "published": when.date().isoformat(),
                        "summary": summary[:280],
                        "body": _feed_body(e),
                        "url_hash": h,
                    }
                )
                fresh += 1
            print(f"[in-print] {feed_cfg['name']}: {fresh} fresh")
        except Exception as e:
            print(f"[in-print] {feed_cfg['name']} FAILED ({type(e).__name__}) - skipping")
    return items


def _ensure_body(item: dict) -> str:
    if len(item.get("body", "")) >= MIN_BODY_CHARS:
        return item["body"]
    try:
        item["body"] = _article_text(item["url"])
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
    hashes = [c["url_hash"] for c in candidates]

    models = [cfg["gemini"]["model"]]
    if cfg["gemini"].get("fallback_model") and cfg["gemini"]["fallback_model"] not in models:
        models.append(cfg["gemini"]["fallback_model"])

    profile = (ROOT / "profile.md").read_text(encoding="utf-8")
    listing = "\n".join(
        f"[{i}] {c['title']} | {c['source']} | {c['summary']}" for i, c in enumerate(candidates)
    )
    data = _ask(
        models,
        SELECT_PROMPT.format(profile=profile, max_items=cfg["in_print"]["max_items"], listing=listing),
    )

    results = []
    for pick in data.get("picks", [])[: cfg["in_print"]["max_items"]]:
        ids = pick.get("ids")
        if not (isinstance(ids, list) and ids and all(isinstance(i, int) and 0 <= i < len(candidates) for i in ids)):
            continue
        item = candidates[ids[0]]
        why = pick.get("why", "").strip() or item["title"]
        body = _ensure_body(item)
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
            dest.write_text(
                f"# {item['title']}\n\n- **Source:** {item['source']} (reported news / analysis)\n"
                f"- **Date:** {item['published']}\n- **URL:** {item['url']}\n"
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
            }
        )
    print(f"[in-print] {len(results)} item(s) selected from {len(candidates)} candidates")
    return results, hashes
