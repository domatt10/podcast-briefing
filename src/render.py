"""Assemble the briefing from validated items + transcripts.

ATTRIBUTION IS STAMPED BY CODE (spec §7): every rendered item carries the
show / episode title / date / author from feed metadata, and its quote text +
timestamp come from the transcript segments referenced by ID. The only model
prose on display is the one-line relevance note ("why").

Layout follows docs/example-briefing.md: two bands, five fixed sections in
fixed order (so quiet days stay legible), tiered items, ★ for
institutional-memory material.
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


def render_briefing(date_label: str, episodes: list[dict]) -> tuple[str, str, str]:
    """episodes: [{"transcript": ..., "items": [...]}, ...] (one per episode).

    Returns (subject, plain_text, html).
    """
    by_stream: dict[str, list[tuple[dict, dict]]] = {}
    for ep in episodes:
        for item in ep["items"]:
            by_stream.setdefault(item["stream"], []).append((item, ep["transcript"]))

    subject = f"Morning Signals — {date_label}"
    text_parts = [f"MORNING SIGNALS — {date_label}", ""]
    html_parts = [
        "<div style='font-family:Georgia,serif;max-width:640px;margin:auto;"
        "font-size:16px;line-height:1.5;color:#222'>",
        f"<h1 style='font-size:22px'>Morning Signals — {escape(date_label)}</h1>",
    ]

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

    html_parts.append("</div>")
    return subject, "\n".join(text_parts), "".join(html_parts)
