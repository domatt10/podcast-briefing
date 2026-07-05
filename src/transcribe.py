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
