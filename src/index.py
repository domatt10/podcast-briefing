"""index.md — one line per archived episode; the agent's fast map (brief A.2).

Format: date · show · episode title · guests · topics · stamp
The stamp ties the line to the episode's files and doubles as the dedupe key,
so appending is idempotent.
"""

from pathlib import Path

HEADER = "# Episode index\n\ndate · show · episode title · guests · topics\n\n"


def append_index_line(archive: Path, episode, guests: list[str], topics: list[str]) -> None:
    path = archive / "index.md"
    if not path.exists():
        path.write_text(HEADER, encoding="utf-8")
    if episode.stamp in path.read_text(encoding="utf-8"):
        return  # already indexed
    guests_txt = ", ".join(guests) if guests else "hosts only"
    topics_txt = ", ".join(topics) if topics else "-"
    line = f"- {episode.published} · {episode.show} · “{episode.title}” · {guests_txt} · {topics_txt} · `{episode.stamp}`\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
