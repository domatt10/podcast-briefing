"""Merge backfill artifacts into the archive clone (agent brief C).

Copies transcripts that don't already exist and appends stamp-deduped index
lines, date-sorted. The workflow then commits the archive once — twenty
runners pushing separately would trip over each other.
"""

import argparse
import shutil
from pathlib import Path

from index import HEADER


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifacts", required=True)
    ap.add_argument("--archive", required=True)
    args = ap.parse_args()
    artifacts = Path(args.artifacts)
    archive = Path(args.archive)

    copied = 0
    for src in sorted(artifacts.glob("*/transcripts/*/*")):
        dest = archive / "transcripts" / src.parent.name / src.name
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1

    index = archive / "index.md"
    existing = index.read_text(encoding="utf-8") if index.exists() else ""
    fresh = set()
    for f in artifacts.glob("*/index-lines-*.txt"):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            stamp = line.rsplit("`", 2)[-2] if line.count("`") >= 2 else ""
            if stamp and stamp not in existing:
                fresh.add(line)

    if not index.exists():
        index.write_text(HEADER, encoding="utf-8")
    if fresh:
        with index.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(sorted(fresh)) + "\n")  # lines start with the date → date-sorted

    print(f"[collect] copied {copied} file(s), appended {len(fresh)} index line(s)")


if __name__ == "__main__":
    main()
