"""Daily news layer: curated RSS → text files in the private archive.

This is the factual spine beside the podcasts' attributed speculation (agent
brief A.1): it lets the archive agent calibrate rumour against outcome. No
LLM involved — fetch, extract the article text, save with a small header.

Failure posture: nothing here may ever sink the briefing run. Every feed and
every article is individually wrapped; the worst outcome is a footer note.

Dedupe is by file existence (hash of the article URL in the filename) — same
idempotence pattern as episodes.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

REQUEST_HEADERS = {"User-Agent": "podcast-briefing/0.1 (personal, single-user)"}


def _matches_keywords(entry, keywords: list[str]) -> bool:
    text = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(k.lower() in text for k in keywords)


def _article_text(url: str) -> str:
    """Best-effort body extraction. Some boilerplate is acceptable (brief's
    watch-outs) — this is reference material, not display copy."""
    resp = requests.get(url, timeout=30, headers=REQUEST_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    root = soup.find("article") or soup.body
    if root is None:
        return ""
    paras = [p.get_text(" ", strip=True) for p in root.find_all("p")]
    return "\n\n".join(p for p in paras if len(p) > 40)  # drop nav/crumb lines


def _save_story(entry, feed_cfg: dict, news_dir: Path) -> bool:
    """Save one story; returns True if a new file was written."""
    link = entry.get("link")
    if not link:
        return False
    date = ""
    if entry.get("published_parsed"):
        date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).date().isoformat()
    stamp = hashlib.sha256(link.encode()).hexdigest()[:8]
    dest = news_dir / feed_cfg["slug"] / f"{date}_{stamp}.md"
    if dest.exists():
        return False

    title = entry.get("title", "(untitled)").strip()
    try:
        body = _article_text(link)
    except Exception:
        body = ""
    if not body:  # fall back to the RSS summary, stripped of any HTML
        body = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        f"# {title}\n\n"
        f"- **Source:** {feed_cfg['name']} (reported news)\n"
        f"- **Date:** {date}\n"
        f"- **URL:** {link}\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return True


def fetch_news(cfg: dict, archive: Path) -> int:
    """Pull all configured news feeds; returns count of new stories saved."""
    news_dir = archive / "news"
    keywords = cfg["news"]["energy_keywords"]
    cap = cfg["news"]["max_per_feed"]
    total = 0
    for feed_cfg in cfg.get("news_feeds", []):
        try:
            parsed = feedparser.parse(feed_cfg["url"])
            if not parsed.entries:
                print(f"[news] {feed_cfg['name']}: no entries - skipping")
                continue
            saved = 0
            for entry in parsed.entries:
                if saved >= cap:
                    break
                if feed_cfg.get("filter") == "energy" and not _matches_keywords(entry, keywords):
                    continue
                try:
                    if _save_story(entry, feed_cfg, news_dir):
                        saved += 1
                except Exception as e:
                    print(f"[news] story failed ({type(e).__name__}) - skipping")
            print(f"[news] {feed_cfg['name']}: {saved} new")
            total += saved
        except Exception as e:
            print(f"[news] {feed_cfg['name']} FAILED ({type(e).__name__}) - skipping feed")
    return total
