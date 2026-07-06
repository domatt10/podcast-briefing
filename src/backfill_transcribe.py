"""Transcribe one chunk of the backfill plan (agent brief C).

Whisper only — no Gemini, no emails, no state changes. Output goes to a local
out/ directory that the workflow uploads as an artifact; the collector job
merges all artifacts into the archive in a single commit. One broken episode
never sinks the chunk.
"""

import argparse
import json
from pathlib import Path

from config import data_dir, load_config
from download import download_audio, slug
from feeds import Episode
from transcribe import ensure_readable, transcribe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--chunk-id", type=int, required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--whisper-model", help="override config model (local tests)")
    args = ap.parse_args()

    cfg = load_config()
    chunk = json.loads(Path(args.plan).read_text(encoding="utf-8"))["chunks"][args.chunk_id]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    scratch = data_dir(cfg)

    index_lines = []
    done = failed = 0
    for spec in chunk:
        ep = Episode(**spec)
        try:
            audio = download_audio(ep, scratch)
            tpath = out / "transcripts" / slug(ep.show) / f"{ep.published}_{ep.stamp}.transcript.json"
            transcribe(audio, ep, cfg["whisper"], tpath, model_name=args.whisper_model)
            ensure_readable(tpath)
            audio.unlink()  # keep runner disk in check across many episodes
            # Plain index line: backfilled episodes have no Gemini pass, so no
            # guests/topics — "-" placeholders keep the column count uniform.
            index_lines.append(f"- {ep.published} · {ep.show} · “{ep.title}” · - · - · `{ep.stamp}`")
            done += 1
        except Exception as e:
            print(f"[chunk {args.chunk_id}] FAILED '{spec['title']}' ({type(e).__name__}) - continuing")
            failed += 1

    (out / f"index-lines-{args.chunk_id}.txt").write_text(
        "\n".join(index_lines) + ("\n" if index_lines else ""), encoding="utf-8"
    )
    print(f"[chunk {args.chunk_id}] done={done} failed={failed}")


if __name__ == "__main__":
    main()
