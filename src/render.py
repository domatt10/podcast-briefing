"""Assemble the briefing from validated items + transcripts.

ATTRIBUTION IS STAMPED BY CODE (spec §7): every rendered item carries the
show / episode title / date / author from feed metadata, and its quote text +
timestamp come from the transcript segments referenced by ID. The only model
prose on display is the one-line relevance note ("why").

Layout: top line, then five fixed sections in fixed order (so quiet days stay
legible), tiered items, a badge for institutional-memory material. The spec's
two "band" headings were dropped in favour of the lane colours. Three email shapes: the briefing, the fallback
(raw episode list when synthesis failed — something always arrives, spec §9),
and the quiet-day one-liner.

STYLING NOTE: email clients are not browsers. Everything here is inline styles
on simple block elements — no <style> blocks, no flexbox, no external assets —
because that is what survives Gmail, Outlook and Apple Mail alike.
"""

from html import escape

BRAND = "Daily podcast summary"

# (stream key, display heading) in the fixed §5 order. The spec grouped these
# under two bands ("On your patch" / "The wider weather"); dropped at Dom's
# request 2026-07-29 — the lane colours and fixed order already do that work.
SECTIONS = [
    ("energy_desnz", "Energy / DESNZ"),
    ("crown_estate", "Crown Estate lane"),
    ("treasury_fiscal", "Treasury / fiscal"),
    ("top_of_government", "Top of government"),
    ("parliamentary_colour", "Parliamentary colour"),
]

ENERGY_STREAMS = {"energy_desnz", "crown_estate"}

# Per-lane colour coding (Dom's request). Deliberately desaturated, print-like
# tones: dark enough to read as body text on white, distinct at a glance on a
# phone, and they never carry meaning alone — every section is also labelled.
STREAM_COLOURS = {
    "energy_desnz": "#2f6b4f",        # green
    "crown_estate": "#1f3a5f",        # navy
    "treasury_fiscal": "#9b2c2c",     # red
    "top_of_government": "#b1621a",   # orange
    "parliamentary_colour": "#6b3f6e",  # plum
}
INPRINT_COLOUR = "#4a5763"  # slate — reported fact, deliberately cooler

# --- design tokens ----------------------------------------------------------
INK = "#1d2a35"
BODY = "#2f3a44"
MUTED = "#6b7783"
FAINT = "#98a2ad"
RULE = "#e3e7ea"
ACCENT = "#24425c"
BADGE_BG = "#fdf3e3"
BADGE_INK = "#8a5a1b"
QUOTE_BG = "#f7f9fa"

SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
SERIF = "Georgia,'Times New Roman',serif"

S_LABEL = f"font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase"
S_SOURCE = f"font-family:{SANS};font-size:12.5px;color:{MUTED};line-height:1.5"
S_WHY = f"font-family:{SERIF};font-size:16.5px;font-weight:700;color:{INK};line-height:1.5;margin:0 0 10px"
S_QUOTE = f"font-family:{SERIF};font-size:16px;color:{BODY};line-height:1.62;margin:0 0 12px"

PARA_GAP_SECS = 45  # break a long quote at roughly this cadence


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"~{h}:{m:02d}:{s:02d}" if h else f"~{m:02d}:{s:02d}"


def reconstitute(item: dict, transcript: dict) -> tuple[str, str]:
    """Exact quote text + timestamp from the item's segment IDs — the verbatim
    mechanism's final step. No model output involved.

    Long passages are broken into paragraphs (~every PARA_GAP_SECS of speech)
    so they don't arrive as a wall of text on a phone. Paragraphing is
    whitespace only: not a word of the transcript is changed.
    """
    segs = [transcript["segments"][i] for i in item["segment_ids"]]
    paras, current, start = [], [], segs[0]["start"]
    for s in segs:
        current.append(s["text"])
        if s["end"] - start >= PARA_GAP_SECS:
            paras.append(" ".join(current))
            current, start = [], s["end"]
    if current:
        paras.append(" ".join(current))
    return "\n\n".join(paras), _fmt_ts(segs[0]["start"])


def quote_words(item: dict, transcript: dict) -> int:
    return sum(
        len(transcript["segments"][i]["text"].split())
        for i in item["segment_ids"]
        if i < len(transcript["segments"])
    )


def build_stories(episodes: list[dict], groups: list[list[int]]) -> list[dict]:
    """Turn per-episode items + cluster groups into deduped stories.

    Each story: {"primary": (item, transcript), "others": [(item, transcript)]}.
    The primary is the fullest treatment (significant beats fragment, then
    longest quote) — the others become the corroboration line, which is also
    the spec's attribution-density signal: one source or many.
    """
    flat = [(item, ep["transcript"]) for ep in episodes for item in ep["items"]]
    stories = []
    for group in groups:
        members = [flat[i] for i in group if i < len(flat)]
        if not members:
            continue
        members.sort(
            key=lambda m: (m[0]["tier"] == "significant", quote_words(*m)), reverse=True
        )
        stories.append({"primary": members[0], "others": members[1:]})
    return stories


def _source_line(transcript: dict, ts: str) -> str:
    m = transcript["metadata"]
    who = m["author"] or "hosts"
    return f"{m['show']} · ep. “{m['title']}” · {who} · {m['published']} · {ts}"


def _source_html(transcript: dict, ts: str) -> str:
    """Same facts as _source_line, with the show emphasised for scanning."""
    m = transcript["metadata"]
    who = m["author"] or "hosts"
    return (
        f"<strong style='color:{BODY};font-weight:600'>{escape(m['show'])}</strong> · "
        f"“{escape(m['title'])}” · {escape(who)} · {escape(m['published'])} · {escape(ts)}"
    )


def _corroboration(others: list[tuple[dict, dict]]) -> str:
    """The attribution-density line (spec §3): who else carried this story.
    Empty for single-source items — so a bare item visibly means one source."""
    if not others:
        return ""
    bits = []
    for item, transcript in others:
        _, ts = reconstitute(item, transcript)
        bits.append(f"{transcript['metadata']['show']} ({ts})")
    return "Also on: " + " · ".join(bits)


def _quote_html(quote: str, colour: str = ACCENT) -> str:
    paras = "".join(
        f"<p style='{S_QUOTE}'>{escape(p)}</p>" for p in quote.split("\n\n") if p.strip()
    )
    return (
        f"<div style='background:{QUOTE_BG};border-left:3px solid {colour};"
        f"padding:14px 16px 4px;margin:0 0 10px;border-radius:0 3px 3px 0'>{paras}</div>"
    )


def _footer(footer_notes, text_parts: list, html_parts: list) -> None:
    if not footer_notes:
        return
    text_parts += ["", "— Pipeline notes —"]
    html_parts.append(
        f"<div style='border-top:1px solid {RULE};margin:28px 0 0;padding-top:12px'>"
        f"<div style='{S_LABEL};color:{FAINT};margin-bottom:6px'>Pipeline notes</div><ul style='margin:0;padding-left:18px'>"
    )
    for note in footer_notes:
        text_parts.append(f"  ! {note}")
        html_parts.append(f"<li style='{S_SOURCE};margin-bottom:3px'>{escape(note)}</li>")
    html_parts.append("</ul></div>")


def _wrap_html(date_label: str, body: str, preheader: str = "") -> str:
    hidden = (
        f"<div style='display:none;max-height:0;overflow:hidden;opacity:0'>{escape(preheader)}</div>"
        if preheader
        else ""
    )
    return (
        f"<div style='background:#ffffff;padding:24px 18px'>{hidden}"
        f"<div style='max-width:640px;margin:0 auto;font-family:{SERIF};color:{BODY}'>"
        f"<div style='{S_LABEL};color:{ACCENT};margin-bottom:4px'>{BRAND}</div>"
        f"<h1 style='font-family:{SERIF};font-size:23px;font-weight:700;color:{INK};"
        f"margin:0 0 4px;line-height:1.25'>{escape(date_label)}</h1>"
        f"{body}</div></div>"
    )


def _divider_html(label: str, colour: str = INK) -> str:
    """A labelled rule marking a change of material — now only used to separate
    the reported-news block from the podcast sections above it."""
    return (
        f"<div style='margin:30px 0 14px'>"
        f"<div style='{S_LABEL};color:{colour};border-bottom:1px solid {RULE};"
        f"padding-bottom:5px'>{escape(label)}</div></div>"
    )


def _section_html(heading: str, count: int, colour: str) -> str:
    """Lane heading and its count together in the lane colour — 'Crown Estate
    lane (2)' — so a phone skim finds the lane and its weight at a glance."""
    return (
        f"<h2 style='font-family:{SANS};font-size:15px;font-weight:700;color:{colour};"
        f"margin:22px 0 8px;letter-spacing:0.2px'>{escape(heading)} ({count})</h2>"
    )


def render_briefing(
    date_label: str,
    stories: list[dict],
    top: list[tuple[dict, dict]] = (),
    footer_notes: list[str] = (),
    in_print: list[dict] = (),
) -> tuple[str, str, str]:
    """stories: [{"primary": (item, transcript), "others": [...]}] from
    build_stories — one entry per story, deduped across episodes.
    top: (item, transcript) pairs chosen by select_top_line.

    Returns (subject, plain_text, html).
    """
    by_stream: dict[str, list[dict]] = {}
    for story in stories:
        by_stream.setdefault(story["primary"][0]["stream"], []).append(story)

    subject = f"{BRAND} — {date_label}"
    text_parts: list[str] = []
    html_parts: list[str] = []

    # Orientation: what you're about to read, before you commit to it.
    shows = {s["primary"][1]["metadata"]["show"] for s in stories}
    for s in stories:
        shows.update(t["metadata"]["show"] for _, t in s["others"])
    words = sum(quote_words(*s["primary"]) for s in stories)
    n_sig = sum(1 for s in stories if s["primary"][0]["tier"] == "significant")
    orientation = ""
    if stories:
        orientation = (
            f"{len(stories)} stories ({n_sig} in full) from {len(shows)} shows"
            f"{f' · {len(in_print)} in print' if in_print else ''} · ~{max(1, round(words / 200))} min"
        )
        text_parts += [orientation, ""]
        html_parts.append(
            f"<div style='font-family:{SANS};font-size:12.5px;color:{FAINT};"
            f"padding-bottom:14px;border-bottom:1px solid {RULE}'>{escape(orientation)}</div>"
        )

    if top:
        text_parts += ["TOP LINE", ""]
        html_parts.append(
            f"<div style='margin:18px 0 4px'><div style='{S_LABEL};color:{MUTED};"
            f"margin-bottom:8px'>Top line</div>"
        )
        for item, transcript in top:
            show = transcript["metadata"]["show"]
            tag = "energy" if item["stream"] in ENERGY_STREAMS else "politics"
            colour = STREAM_COLOURS.get(item["stream"], ACCENT)
            text_parts.append(f"- {item['why']} — {show} · ({tag})")
            html_parts.append(
                f"<div style='margin:0 0 9px;padding-left:12px;border-left:3px solid {colour}'>"
                f"<span style='font-family:{SERIF};font-size:15.5px;color:{INK};"
                f"line-height:1.45'>{escape(item['why'])}</span><br>"
                f"<span style='{S_SOURCE}'>{escape(show)} · "
                f"<span style='color:{colour};font-weight:600'>{tag}</span></span></div>"
            )
        text_parts.append("")
        html_parts.append("</div>")

    for stream, heading in SECTIONS:
        entries = by_stream.get(stream, [])
        colour = STREAM_COLOURS.get(stream, ACCENT)
        text_parts.append(f"{heading} ({len(entries)})")
        html_parts.append(_section_html(heading, len(entries), colour))
        if not entries:
            text_parts += ["  Nothing notable today.", ""]
            html_parts.append(
                f"<p style='font-family:{SANS};font-size:13px;color:{FAINT};margin:0 0 4px'>"
                f"Nothing notable today.</p>"
            )
            continue

        significant = [s for s in entries if s["primary"][0]["tier"] == "significant"]
        fragments = [s for s in entries if s["primary"][0]["tier"] != "significant"]

        for story in significant:
            item, transcript = story["primary"]
            quote, ts = reconstitute(item, transcript)
            badge = "★ Worth remembering — institutional memory. " if item["institutional_memory"] else ""
            src = _source_line(transcript, ts)
            also = _corroboration(story["others"])
            text_parts += [f"  {badge}{item['why']}", f"    “{quote}”", f"    — {src}"]
            if also:
                text_parts.append(f"    {also}")
            text_parts.append("")

            badge_html = (
                f"<div style='display:inline-block;background:{BADGE_BG};color:{BADGE_INK};"
                f"{S_LABEL};padding:3px 7px;border-radius:3px;margin-bottom:8px'>"
                f"★ Worth remembering</div><br>"
                if item["institutional_memory"]
                else ""
            )
            html_parts.append(
                f"<div style='margin:0 0 22px'>{badge_html}"
                f"<p style='{S_WHY}'>{escape(item['why'])}</p>"
                f"{_quote_html(quote, colour)}"
                f"<div style='{S_SOURCE}'>{_source_html(transcript, ts)}</div>"
                + (
                    f"<div style='{S_SOURCE};color:{FAINT};margin-top:2px'>{escape(also)}</div>"
                    if also
                    else ""
                )
                + "</div>"
            )

        if fragments:
            text_parts.append("  In brief:")
            html_parts.append(
                f"<div style='{S_LABEL};color:{FAINT};margin:14px 0 8px'>In brief</div>"
            )
            for story in fragments:
                item, transcript = story["primary"]
                quote, ts = reconstitute(item, transcript)
                src = _source_line(transcript, ts)
                also = _corroboration(story["others"])
                text_parts.append(f"  - {item['why']} “{quote}” — {src} {also}".rstrip())
                html_parts.append(
                    f"<div style='margin:0 0 12px;padding-left:12px;border-left:2px solid {colour}'>"
                    f"<span style='font-family:{SERIF};font-size:15px;color:{INK};"
                    f"line-height:1.5'>{escape(item['why'])}</span> "
                    f"<span style='font-family:{SERIF};font-size:15px;color:{MUTED}'>"
                    f"“{escape(quote.replace(chr(10) * 2, ' '))}”</span><br>"
                    f"<span style='{S_SOURCE}'>{_source_html(transcript, ts)}"
                    + (f"<br><span style='color:{FAINT}'>{escape(also)}</span>" if also else "")
                    + "</span></div>"
                )
            text_parts.append("")

    if in_print:
        # Reported news/analysis, visually separate from podcast speculation.
        # Quotes are exact paragraphs reconstituted by code (in_print.py).
        text_parts += ["——— IN PRINT ———", ""]
        html_parts.append(_divider_html("In print", INPRINT_COLOUR))
        for item in in_print:
            src = f"{item['source']} · “{item['title']}” · {item['published']}"
            text_parts.append(f"• {item['why']}")
            if item.get("quote"):
                text_parts.append(f'  “{item["quote"]}”')
            text_parts += [f"  — {src}", f"  {item['url']}", ""]
            html_parts.append(
                f"<div style='margin:0 0 22px'><p style='{S_WHY}'>{escape(item['why'])}</p>"
                + (_quote_html(item["quote"], INPRINT_COLOUR) if item.get("quote") else "")
                + f"<div style='{S_SOURCE}'>"
                f"<strong style='color:{BODY};font-weight:600'>{escape(item['source'])}</strong> · "
                f"<a href='{escape(item['url'])}' style='color:{INPRINT_COLOUR};text-decoration:none'>"
                f"{escape(item['title'])}</a> · {escape(item['published'])}</div></div>"
            )

    _footer(footer_notes, text_parts, html_parts)
    text = f"{BRAND.upper()} — {date_label}\n\n" + "\n".join(text_parts)
    preheader = orientation or "Nothing new since the last run."
    return subject, text, _wrap_html(date_label, "".join(html_parts), preheader)


def render_fallback(
    date_label: str,
    failures: list[tuple],
    footer_notes: list[str] = (),
) -> tuple[str, str, str]:
    """Everything-failed email: the raw new-episode list + transcript links
    (spec §9) so something useful always arrives.

    failures: (episode, transcript_url_or_None) pairs.
    """
    subject = f"{BRAND} — {date_label} (fallback: processing failed)"
    text_parts = [
        "Summarisation failed today, so here is the raw list of new episodes.",
        "They will be retried tomorrow.",
        "",
    ]
    html_parts = [
        f"<p style='font-family:{SANS};font-size:14px;color:{MUTED};margin:16px 0'>"
        "Summarisation failed today, so here is the raw list of new episodes. "
        "They will be retried tomorrow.</p><ul style='padding-left:18px'>"
    ]
    for ep, url in failures:
        line = f"{ep.show} — “{ep.title}” ({ep.published})"
        text_parts.append(f"- {line}" + (f"\n  transcript: {url}" if url else ""))
        html_parts.append(
            f"<li style='font-family:{SERIF};font-size:15px;color:{BODY};margin-bottom:7px'>{escape(line)}"
            + (
                f" — <a href='{escape(url)}' style='color:{ACCENT};text-decoration:none'>transcript</a>"
                if url
                else ""
            )
            + "</li>"
        )
    html_parts.append("</ul>")
    _footer(footer_notes, text_parts, html_parts)
    text = f"{BRAND.upper()} — {date_label} (FALLBACK)\n\n" + "\n".join(text_parts)
    return subject, text, _wrap_html(date_label, "".join(html_parts), "Processing failed — raw episode list")


def render_quiet(date_label: str, footer_notes: list[str] = ()) -> tuple[str, str, str]:
    """Nothing-new day: a one-liner, as spec §9 allows."""
    subject = f"{BRAND} — {date_label} (quiet)"
    text_parts = ["Nothing new since the last run. All feeds checked."]
    html_parts = [
        f"<p style='font-family:{SANS};font-size:14px;color:{MUTED};margin:16px 0'>"
        "Nothing new since the last run. All feeds checked.</p>"
    ]
    _footer(footer_notes, text_parts, html_parts)
    text = f"{BRAND.upper()} — {date_label}\n\n" + "\n".join(text_parts)
    return subject, text, _wrap_html(date_label, "".join(html_parts), "Quiet morning — nothing new")
