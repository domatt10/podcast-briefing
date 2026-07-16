"""Assemble the briefing from validated items + transcripts.

ATTRIBUTION IS STAMPED BY CODE (spec §7): every rendered item carries the
show / episode title / date / author from feed metadata, and its quote text +
timestamp come from the transcript segments referenced by ID. The only model
prose on display is the one-line relevance note ("why").

Layout follows docs/example-briefing.md: top line, two bands, five fixed
sections in fixed order (so quiet days stay legible), tiered items, ★ for
institutional-memory material. Three email shapes: the briefing, the fallback
(raw episode list when synthesis failed — something always arrives, spec §9),
and the quiet-day one-liner.
"""

from html import escape

# (stream key, display heading) in the fixed §5 order, grouped into bands.
BANDS = [
    (
        "ON YOUR PATCH",
        [
            ("energy_desnz", "Energy / DESNZ"),
            ("crown_estate", "Crown Estate lane"),
        ],
    ),
    (
        "THE WIDER WEATHER",
        [
            ("treasury_fiscal", "Treasury / fiscal"),
            ("top_of_government", "Top of government"),
            ("parliamentary_colour", "Parliamentary colour"),
        ],
    ),
]

ENERGY_STREAMS = {"energy_desnz", "crown_estate"}


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"~{h}:{m:02d}:{s:02d}" if h else f"~{m:02d}:{s:02d}"


def reconstitute(item: dict, transcript: dict) -> tuple[str, str]:
    """Exact quote text + timestamp from the item's segment IDs — the verbatim
    mechanism's final step. No model output involved."""
    segs = [transcript["segments"][i] for i in item["segment_ids"]]
    quote = " ".join(s["text"] for s in segs)
    return quote, _fmt_ts(segs[0]["start"])


def _source_line(transcript: dict, ts: str) -> str:
    m = transcript["metadata"]
    who = m["author"] or "hosts"
    return f"{m['show']} · ep. “{m['title']}” · {who} · {m['published']} · {ts}"


def _footer(footer_notes, text_parts: list, html_parts: list) -> None:
    if not footer_notes:
        return
    text_parts += ["", "— Pipeline notes —"]
    html_parts.append(
        "<h3 style='font-size:13px;color:#a66;border-top:1px solid #ddd;"
        "padding-top:8px;margin-top:20px'>Pipeline notes</h3><ul>"
    )
    for note in footer_notes:
        text_parts.append(f"  ! {note}")
        html_parts.append(f"<li style='font-size:13px;color:#a66'>{escape(note)}</li>")
    html_parts.append("</ul>")


def _wrap_html(date_label: str, body: str) -> str:
    return (
        "<div style='font-family:Georgia,serif;max-width:640px;margin:auto;"
        "font-size:16px;line-height:1.5;color:#222'>"
        f"<h1 style='font-size:22px'>Morning Signals — {escape(date_label)}</h1>"
        f"{body}</div>"
    )


def render_briefing(
    date_label: str,
    episodes: list[dict],
    top: list[tuple[dict, dict]] = (),
    footer_notes: list[str] = (),
    in_print: list[dict] = (),
) -> tuple[str, str, str]:
    """episodes: [{"transcript": ..., "items": [...]}, ...] (one per episode).
    top: (item, transcript) pairs chosen by select_top_line.

    Returns (subject, plain_text, html).
    """
    by_stream: dict[str, list[tuple[dict, dict]]] = {}
    for ep in episodes:
        for item in ep["items"]:
            by_stream.setdefault(item["stream"], []).append((item, ep["transcript"]))

    subject = f"Morning Signals — {date_label}"
    text_parts: list[str] = []
    html_parts: list[str] = []

    if top:
        text_parts += ["▶ TOP LINE", ""]
        html_parts.append("<h2 style='font-size:16px'>▶ Top line</h2><ul>")
        for item, transcript in top:
            show = transcript["metadata"]["show"]
            tag = "energy" if item["stream"] in ENERGY_STREAMS else "politics"
            text_parts.append(f"- {item['why']} — {show} · ({tag})")
            html_parts.append(
                f"<li style='margin-bottom:6px'><b>{escape(item['why'])}</b> "
                f"<span style='font-size:13px;color:#666'>— {escape(show)} · ({tag})</span></li>"
            )
        text_parts.append("")
        html_parts.append("</ul>")

    n = 0
    for band, sections in BANDS:
        text_parts += [f"——— {band} ———", ""]
        html_parts.append(
            f"<h2 style='font-size:13px;letter-spacing:2px;color:#888;"
            f"border-bottom:1px solid #ddd;padding-bottom:4px'>——— {band} ———</h2>"
        )
        for stream, heading in sections:
            n += 1
            entries = by_stream.get(stream, [])
            text_parts.append(f"{n} · {heading}")
            html_parts.append(f"<h3 style='font-size:18px;margin-bottom:4px'>{n} · {escape(heading)}</h3>")
            if not entries:
                text_parts += ["  Nothing notable today.", ""]
                html_parts.append("<p style='color:#888'><i>Nothing notable today.</i></p>")
                continue

            significant = [(i, t) for i, t in entries if i["tier"] == "significant"]
            fragments = [(i, t) for i, t in entries if i["tier"] == "fragment"]

            for item, transcript in significant:
                quote, ts = reconstitute(item, transcript)
                star = "★ Worth remembering — institutional memory. " if item["institutional_memory"] else ""
                src = _source_line(transcript, ts)
                text_parts += [f"  {star}{item['why']}", f"    “{quote}”", f"    — {src}", ""]
                html_parts.append(
                    f"<p><b>{escape(star)}{escape(item['why'])}</b></p>"
                    f"<blockquote style='border-left:3px solid #ccc;margin:8px 0 8px 8px;"
                    f"padding-left:12px;color:#333'><i>“{escape(quote)}”</i></blockquote>"
                    f"<p style='font-size:13px;color:#666'>— {escape(src)}</p>"
                )

            if fragments:
                text_parts.append("  Fragments:")
                html_parts.append("<p style='margin-bottom:2px'><i>Fragments:</i></p><ul style='margin-top:2px'>")
                for item, transcript in fragments:
                    quote, ts = reconstitute(item, transcript)
                    src = _source_line(transcript, ts)
                    text_parts.append(f"  - {item['why']} “{quote}” — {src}")
                    html_parts.append(
                        f"<li style='font-size:14px;margin-bottom:6px'>{escape(item['why'])} "
                        f"<i>“{escape(quote)}”</i> "
                        f"<span style='font-size:12px;color:#666'>— {escape(src)}</span></li>"
                    )
                text_parts.append("")
                html_parts.append("</ul>")

    if in_print:
        # Reported news/analysis, visually separate from podcast speculation.
        # Quotes are exact paragraphs reconstituted by code (in_print.py).
        text_parts += ["——— IN PRINT ———", ""]
        html_parts.append(
            "<h2 style='font-size:13px;letter-spacing:2px;color:#888;"
            "border-bottom:1px solid #ddd;padding-bottom:4px'>——— IN PRINT ———</h2>"
        )
        for item in in_print:
            src = f"{item['source']} · “{item['title']}” · {item['published']}"
            text_parts.append(f"• {item['why']}")
            if item.get("quote"):
                text_parts += [f'  “{item["quote"]}”']
            text_parts += [f"  — {src}", f"  {item['url']}", ""]
            html_parts.append(f"<p><b>{escape(item['why'])}</b></p>")
            if item.get("quote"):
                quote_html = escape(item["quote"]).replace("\n\n", "<br><br>")
                html_parts.append(
                    f"<blockquote style='border-left:3px solid #ccc;margin:8px 0 8px 8px;"
                    f"padding-left:12px;color:#333'><i>“{quote_html}”</i></blockquote>"
                )
            html_parts.append(
                f"<p style='font-size:13px;color:#666'>— {escape(item['source'])} · "
                f"<a href='{escape(item['url'])}'>{escape(item['title'])}</a> · {escape(item['published'])}</p>"
            )

    _footer(footer_notes, text_parts, html_parts)
    text = f"MORNING SIGNALS — {date_label}\n\n" + "\n".join(text_parts)
    return subject, text, _wrap_html(date_label, "".join(html_parts))


def render_fallback(
    date_label: str,
    failures: list[tuple],
    footer_notes: list[str] = (),
) -> tuple[str, str, str]:
    """Everything-failed email: the raw new-episode list + transcript links
    (spec §9) so something useful always arrives.

    failures: (episode, transcript_url_or_None) pairs.
    """
    subject = f"Morning Signals — {date_label} (fallback: processing failed)"
    text_parts = [
        "Summarisation failed today, so here is the raw list of new episodes.",
        "They will be retried tomorrow.",
        "",
    ]
    html_parts = [
        "<p>Summarisation failed today, so here is the raw list of new episodes. "
        "They will be retried tomorrow.</p><ul>"
    ]
    for ep, url in failures:
        line = f"{ep.show} — “{ep.title}” ({ep.published})"
        text_parts.append(f"- {line}" + (f"\n  transcript: {url}" if url else ""))
        html_parts.append(
            f"<li style='margin-bottom:6px'>{escape(line)}"
            + (f" — <a href='{escape(url)}'>transcript</a>" if url else "")
            + "</li>"
        )
    html_parts.append("</ul>")
    _footer(footer_notes, text_parts, html_parts)
    text = f"MORNING SIGNALS — {date_label} (FALLBACK)\n\n" + "\n".join(text_parts)
    return subject, text, _wrap_html(date_label, "".join(html_parts))


def render_quiet(date_label: str, footer_notes: list[str] = ()) -> tuple[str, str, str]:
    """Nothing-new day: a one-liner, as spec §9 allows."""
    subject = f"Morning Signals — {date_label} (quiet)"
    text_parts = ["Nothing new since the last run. All feeds checked."]
    html_parts = ["<p>Nothing new since the last run. All feeds checked.</p>"]
    _footer(footer_notes, text_parts, html_parts)
    text = f"MORNING SIGNALS — {date_label}\n\n" + "\n".join(text_parts)
    return subject, text, _wrap_html(date_label, "".join(html_parts))
