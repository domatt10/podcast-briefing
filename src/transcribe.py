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
