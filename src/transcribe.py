"""Transcribe episode audio with faster-whisper (self-hosted Whisper models).

Segment-level timestamps are the backbone of the verbatim-quote mechanism
(spec §5): segments are numbered HERE, Gemini later refers to passages by
segment ID only, and the code reconstitutes exact quote text + timestamp from
those IDs. The transcript JSON is therefore the ground truth for everything
downstream, and its accuracy is why the domain glossary is seeded into
Whisper's initial_prompt (spec §9).
"""

import json
import time
from pathlib import Path


def _fmt_clock(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def ensure_readable(transcript_path: Path) -> Path:
    """Write a human/agent-friendly .md rendering beside the JSON transcript.

    The JSON stays canonical (the verbatim mechanism reads segment IDs from
    it); the markdown exists so the archive is browsable by people and by
    future transcript-querying agents (spec §10). Idempotent: skips if present.
    """
    out = transcript_path.with_suffix("").with_suffix(".md")
    if out.exists():
        return out
    doc = json.loads(transcript_path.read_text(encoding="utf-8"))
    m = doc["metadata"]
    lines = [
        f"# {m['title']}",
        "",
        f"- **Show:** {m['show']}",
        f"- **Published:** {m['published']}",
        f"- **Host/author (from feed):** {m['author'] or 'unknown'}",
        f"- **Transcription:** Whisper {m['whisper_model']} "
        f"(the .transcript.json beside this file is the verbatim ground truth)",
        "",
        "## Transcript",
        "",
    ]
    para: list[str] = []
    para_start = 0.0
    for seg in doc["segments"]:
        if not para:
            para_start = seg["start"]
        para.append(seg["text"])
        if seg["end"] - para_start >= 60:  # new paragraph roughly every minute
            lines += [f"**[{_fmt_clock(para_start)}]** " + " ".join(para), ""]
            para = []
    if para:
        lines.append(f"**[{_fmt_clock(para_start)}]** " + " ".join(para))
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


GLOSSARY_TOKEN_BUDGET = 448 // 2 - 1  # faster-whisper's own prompt cap: 223

# Offline proxy for the token budget, so a test can catch an over-long glossary
# without loading Whisper's tokenizer. Acronym-and-proper-noun text tokenizes
# badly: the current list measures 2.36 chars/token, so 2.1 is a pessimistic
# floor. The AUTHORITATIVE check is the "[transcribe] glossary N/223 tokens"
# line in the run log - this constant only stops the obvious mistake.
GLOSSARY_CHAR_BUDGET = int(GLOSSARY_TOKEN_BUDGET * 2.1)  # 468


def check_glossary_budget(glossary: str, model) -> int:
    """Warn loudly if the glossary will not fit Whisper's prompt.

    faster-whisper keeps only the LAST 223 tokens of the prompt and discards
    the front without a word (see tokenizer.get_prompt). An over-long glossary
    therefore does not degrade gracefully - it throws away whatever is listed
    first, which is where the core vocabulary lives. This happened on
    2026-11-21: the glossary reached 360 tokens and DESNZ, NESO, SSEP, Ofgem
    and the ministers' names were being dropped on every episode.

    Returns the token count, or 0 if the tokenizer could not be reached. Never
    raises: a glossary problem must not stop a transcription.
    """
    try:
        n = len(model.hf_tokenizer.encode(" " + glossary.strip(), add_special_tokens=False).ids)
    except Exception as e:
        print(f"[transcribe] could not measure the glossary ({type(e).__name__}) - continuing")
        return 0
    if n > GLOSSARY_TOKEN_BUDGET:
        over = n - GLOSSARY_TOKEN_BUDGET
        print(
            f"[transcribe] *** GLOSSARY TOO LONG: {n} tokens, budget "
            f"{GLOSSARY_TOKEN_BUDGET}. Whisper is SILENTLY DISCARDING the first "
            f"{over} tokens of it - the terms listed first get no help at all. "
            f"Trim config.toml [whisper].glossary. ***"
        )
    else:
        print(f"[transcribe] glossary {n}/{GLOSSARY_TOKEN_BUDGET} tokens")
    return n



def transcribe(audio_path: Path, episode, whisper_cfg: dict, out: Path, model_name: str | None = None) -> Path:
    """Transcribe one episode to `out` (a path inside the archive).

    Skips work if the transcript already exists (idempotence).
    LOG DISCIPLINE: never print segment text — counts and timings only.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        print(f"[transcribe] already done: {out.name}")
        return out

    from faster_whisper import WhisperModel  # deferred import — slow to load

    name = model_name or whisper_cfg["model"]
    print(f"[transcribe] loading Whisper model '{name}' (first use downloads it)...")
    model = WhisperModel(name, device="cpu", compute_type="int8")
    check_glossary_budget(whisper_cfg["glossary"], model)

    print("[transcribe] transcribing...")
    t0 = time.time()
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="en",
        initial_prompt=whisper_cfg["glossary"],
        vad_filter=True,  # skip silence/music beds
    )

    segments = []
    for i, seg in enumerate(segments_iter):
        segments.append(
            {"id": i, "start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()}
        )
        if (i + 1) % 100 == 0:
            print(f"[transcribe] {i + 1} segments, at {seg.end / 60:.1f} min of audio...")

    elapsed = time.time() - t0
    doc = {
        "metadata": {
            "show": episode.show,
            "title": episode.title,
            "published": episode.published,
            "author": episode.author,
            "guid": episode.guid,
            "duration_secs": episode.duration_secs,
            "whisper_model": name,
        },
        "segments": segments,
    }
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    speed = (info.duration / elapsed) if elapsed else 0
    print(
        f"[transcribe] done: {len(segments)} segments, {info.duration / 60:.1f} min audio "
        f"in {elapsed / 60:.1f} min ({speed:.1f}x realtime)"
    )
    return out
