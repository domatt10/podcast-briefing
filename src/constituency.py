"""Constituency Watch — weekly local digest for offshore-wind/tidal geographies.

THE ALTITUDE INVERSION (brief §0): every other pipeline in this repo filters UP
to ministerial altitude via profile.md. This one filters DOWN — the local
minutiae are the product. This module must never import or quote profile.md.

Flow: Google News query feeds per geography → cross-feed dedup → one Gemini
call per geography (with previously-reported context so items read as
developments) → sparse-aware digest email → selected articles saved to the
archive's news tree → state updated. Weekly, standalone, reuses the existing
credentials and archive plumbing.
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from html import escape

import feedparser
from bs4 import BeautifulSoup

from config import archive_dir, load_config
from emailer import send_email
from news import _article_text
from summarise import _call_with_backoff, genai

CATEGORIES = ("planning", "mp_politics", "community", "ports_supply", "grid")

PROMPT = """You select items for "Constituency Watch": a weekly digest of LOCAL, on-the-ground news about OFFSHORE WIND and TIDAL energy in one UK geography. The reader works on offshore wind at The Crown Estate. His other tools already cover national politics, ministerial news and formal parliamentary monitoring — this product exists for the local layer those tools miss.

# THE ALTITUDE RULE — deliberately inverted; read carefully
LOW ALTITUDE IS THE POINT. Keep the local and granular: a parish-council objection, a cable-landfall row, a port sub-contract, one MP's local campaigning, a petition, planning/examination steps, a jobs announcement at a fabrication yard. NEVER reject an item for being minor, local, or "below ministerial level" — that is precisely the signal wanted here.

# This geography
{bounds}

# Three hard scope rules
1. TOPIC: offshore wind and tidal only. Other energy or infrastructure (onshore-only wind, solar, data centres, roads) is OUT unless directly tied to an offshore-wind/tidal project, port or grid connection.
2. DON'T ASSUME OFFSHORE: if the headline/snippet does not establish that a project is offshore wind or tidal (e.g. an unnamed "wind farm" or "energy project"), treat it as out of scope rather than guessing.
3. LOCAL ONLY: national or sector-wide commentary and UK-government policy news are OUT — the reader's daily briefing covers them. Devolved government (Welsh Government / Senedd) IS in scope: it is part of the local layer here. Trade press covering a specific project milestone in this geography IS in scope.

# Signal vs noise (brief §3)
Prioritise CHANGE, CONFLICT and DECISION: objections, delays, stage changes, political interventions, new or scrapped developments, escalating opposition. Plain announcements rank below shifts. Reject PR puff, recruitment ads, sponsorships, "developer donates to school".

# Previously reported (for continuity — items below may be DEVELOPMENTS of these)
{previous}

# Your task
The numbered items below are headlines/snippets from this geography's feeds over the last fortnight. Group duplicates (the same story echoes across outlets), select what clears the bar, and return JSON only:

{{
  "items": [
    {{
      "ids": [3, 7],                 // this story's item numbers, best-sourced FIRST; duplicates grouped here, never listed twice
      "tier": "lead",                // "lead" = worth a paragraph; "brief" = one-line mention
      "category": "planning",        // one of: planning | mp_politics | community | ports_supply | grid
      "note": "one plain-English line on what happened and why it matters locally — spoken register, no jargon",
      "development_of": "short quote of the previous item this continues, or null if new"
    }}
  ]
}}

Selecting nothing is a valid answer for a quiet fortnight. Never invent facts not in the headlines/snippets.

# Items
{items}
"""


# ---------------------------------------------------------------- fetching --


def _clean_title(raw: str) -> str:
    """Strip Google News's ' - Outlet' suffix."""
    return re.sub(r"\s+-\s+[^-]+$", "", raw).strip()


def _title_key(title: str) -> str:
    """Loose dedup key: lowercase word set, order-insensitive."""
    words = sorted(set(re.findall(r"[a-z0-9']+", title.lower())))
    return hashlib.sha256(" ".join(words).encode()).hexdigest()[:12]


def fetch_geography(geo: dict, recency: str) -> list[dict]:
    """All queries for one geography → deduped item list (exact dupes only;
    fuzzy same-story grouping is Gemini's job)."""
    items, seen_urls, seen_titles = [], set(), set()
    for query in geo["queries"]:
        url = (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(f"{query} {recency}")
            + "&hl=en-GB&gl=GB&ceid=GB:en"
        )
        try:
            parsed = feedparser.parse(url)
        except Exception as e:
            print(f"[cw] feed failed ({type(e).__name__}) for {geo['name']} - skipping query")
            continue
        for e in parsed.entries:
            link = e.get("link", "")
            title = _clean_title(e.get("title", ""))
            tkey = _title_key(title)
            if not link or link in seen_urls or tkey in seen_titles:
                continue
            seen_urls.add(link)
            seen_titles.add(tkey)
            snippet = BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ", strip=True)
            items.append(
                {
                    "title": title,
                    "source": e.get("source", {}).get("title", "unknown"),
                    "url": link,
                    "published": e.get("published", "")[:16],
                    "snippet": snippet[:300],
                    "url_hash": hashlib.sha256(link.encode()).hexdigest()[:12],
                    "title_key": tkey,
                }
            )
    return items


# ------------------------------------------------------------------- state --


def load_cw_state(path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"seen": {}, "reported": []}


def previous_context(state: dict, weeks: int) -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(weeks=weeks)).isoformat()
    lines = [
        f"- {r['note']} ({r['when'][:10]})"
        for r in state["reported"]
        if r["when"] >= cutoff
    ]
    return "\n".join(lines) if lines else "(nothing reported yet — this is a new watch)"


# ------------------------------------------------------------------ gemini --


def select_items(geo: dict, items: list[dict], previous: str, gemini_cfg: dict) -> list[dict]:
    listing = "\n".join(
        f"[{i}] {it['title']} | {it['source']} | {it['published']} | {it['snippet']}"
        for i, it in enumerate(items)
    )
    prompt = PROMPT.format(bounds=geo["bounds"], previous=previous, items=listing)
    client = genai.Client()
    # Same model-fallback ladder as the daily briefing: Google's free tier
    # throws transient 503s and occasionally reshuffles which models it includes.
    models = [gemini_cfg["model"]]
    if gemini_cfg.get("fallback_model") and gemini_cfg["fallback_model"] not in models:
        models.append(gemini_cfg["fallback_model"])
    raw, last_err = None, None
    for model in models:
        try:
            raw = _call_with_backoff(client, model, prompt)
            break
        except Exception as e:
            print(f"[cw] {model} failed ({type(e).__name__})" + (" - trying fallback" if model != models[-1] else ""))
            last_err = e
    if raw is None:
        raise last_err
    data = json.loads(raw)
    selected = []
    for entry in data.get("items", []):
        ids = entry.get("ids")
        ok = (
            isinstance(ids, list)
            and ids
            and all(isinstance(i, int) and 0 <= i < len(items) for i in ids)
            and entry.get("tier") in ("lead", "brief")
            and entry.get("category") in CATEGORIES
            and isinstance(entry.get("note"), str)
        )
        if ok:
            selected.append(entry)
    return selected


# ------------------------------------------------------------------ render --


def render_digest(date_label: str, sections: list[dict]) -> tuple[str, str, str]:
    """sections: [{geo, leads: [(entry, items)], briefs: [...], raw_count}].
    Sparse-aware (brief §4): lead with what exists, quiet geographies in one line."""
    subject = f"Constituency Watch — w/c {date_label}"
    text, html = [], ["<div style='font-family:Georgia,serif;max-width:640px;margin:auto;font-size:16px;line-height:1.5;color:#222'>"]
    html.append(f"<h1 style='font-size:21px'>Constituency Watch — w/c {escape(date_label)}</h1>")

    quiet = [s["geo"] for s in sections if not s["leads"] and not s["briefs"]]
    for s in sections:
        if not s["leads"] and not s["briefs"]:
            continue
        text += [f"=== {s['geo'].upper()} ===", ""]
        html.append(f"<h2 style='font-size:17px;border-bottom:1px solid #ddd;padding-bottom:3px'>{escape(s['geo'])}</h2>")
        for entry, its in s["leads"]:
            first = its[0]
            dev = f" (develops: {entry['development_of']})" if entry.get("development_of") else ""
            srcs = " · ".join(f"{i['source']}" for i in its[:3])
            text += [f"• {entry['note']}{dev}", f"  [{entry['category']}] {first['title']} — {srcs}", f"  {first['url']}", ""]
            html.append(
                f"<p><b>{escape(entry['note'])}</b>{escape(dev)}<br>"
                f"<span style='font-size:13px;color:#666'>[{entry['category']}] "
                f"<a href='{escape(first['url'])}'>{escape(first['title'])}</a> — {escape(srcs)}</span></p>"
            )
        if s["briefs"]:
            text.append("In brief:")
            html.append("<p style='margin-bottom:2px'><i>In brief:</i></p><ul style='margin-top:2px'>")
            for entry, its in s["briefs"]:
                first = its[0]
                text.append(f"  - {entry['note']} ({first['source']}) {first['url']}")
                html.append(
                    f"<li style='font-size:14px;margin-bottom:5px'>{escape(entry['note'])} "
                    f"<a style='font-size:12px' href='{escape(first['url'])}'>{escape(first['source'])}</a></li>"
                )
            html.append("</ul>")
        text.append(f"({s['raw_count']} raw items scanned)")
        text.append("")

    if quiet:
        line = "Quiet this week: " + ", ".join(quiet) + "."
        text += [line]
        html.append(f"<p style='color:#888'><i>{escape(line)}</i></p>")
    html.append("</div>")
    return subject, "\n".join(text), "".join(html)


# -------------------------------------------------------------------- main --


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-email", action="store_true", help="print digest text instead of sending")
    args = ap.parse_args()

    cfg = load_config()
    cw = cfg["constituency"]
    archive = archive_dir(cfg)
    state_path = archive / "constituency" / "state.json"
    state = load_cw_state(state_path)

    today = date.today()
    date_label = f"{today:%A} {today.day} {today:%B %Y}"

    sections = []
    for geo in cfg["constituency_geographies"]:
        items = fetch_geography(geo, cw["recency"])
        fresh = [i for i in items if i["url_hash"] not in state["seen"] and i["title_key"] not in state["seen"]]
        print(f"[cw] {geo['name']}: {len(items)} fetched, {len(fresh)} new")

        leads, briefs = [], []
        if fresh:
            selected = select_items(geo, fresh, previous_context(state, cw["state_memory_weeks"]), cfg["gemini"])
            for entry in selected:
                grouped = [fresh[i] for i in entry["ids"]]
                (leads if entry["tier"] == "lead" else briefs).append((entry, grouped))
            leads = leads[: cw["max_leads_per_geography"]]
            print(f"[cw] {geo['name']}: {len(leads)} lead(s), {len(briefs)} brief(s)")
        sections.append({"geo": geo["name"], "leads": leads, "briefs": briefs, "raw_count": len(fresh)})

        # Everything fetched is now seen — never re-surfaced, selected or not.
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for i in fresh:
            state["seen"][i["url_hash"]] = now
            state["seen"][i["title_key"]] = now
        for entry in leads + briefs:
            state["reported"].append({"note": entry[0]["note"], "when": now, "geo": geo["name"]})

        # Save selected stories' article text for the archive agent (news tree).
        for entry, grouped in leads + briefs:
            first = grouped[0]
            dest = archive / "news" / "constituency-watch" / geo["slug"] / f"{today.isoformat()}_{first['url_hash']}.md"
            if dest.exists():
                continue
            try:
                body = _article_text(first["url"])
            except Exception:
                body = first["snippet"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(
                f"# {first['title']}\n\n- **Source:** {first['source']} (local/trade press — reported)\n"
                f"- **Date:** {first['published']}\n- **URL:** {first['url']}\n"
                f"- **Watch note:** {entry['note']}\n\n{body or first['snippet']}\n",
                encoding="utf-8",
            )

    subject, text, html = render_digest(date_label, sections)
    if args.no_email:
        print("\n" + text)
    else:
        send_email(subject, text, html, cfg["email"])

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[cw] state saved ({len(state['seen'])} seen keys)")


if __name__ == "__main__":
    main()
