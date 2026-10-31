# docs/

What is in here, and how current each file is. For what the system does today,
start with the repository root: `README.md`, then `HANDOVER.md`.

| File | Status | Worth reading for |
|---|---|---|
| `example-briefing.md` | **Current and load-bearing** | The target output format. It is also pasted into the summarisation prompt as a worked example, so changing it changes the product. Every quote in it is invented and clearly labelled as such |
| `briefing-spec.md` | Original specification, July 2026 | The reasoning behind the design. Stale on specifics — feed count, schedule, model names — but sections 3 (standing rules), 4 (attribution) and 8 (the relevance test) have held up and are the parts worth reusing |
| `archive-agent-brief.md` | Original build brief | Why the archive exists and what it is for. The implementation described (a local clone queried conversationally) is one option among several |
| `constituency-watch-brief.md` | Original build brief | The weekly local digest. Note its relevance test deliberately **inverts** the daily briefing's: low altitude is the product there |

## A note on the two build briefs

`archive-agent-brief.md` and `constituency-watch-brief.md` were written as
briefs for building those features, not as documentation of them. They describe
intent accurately and implementation only approximately. Both features are
live; neither brief has been updated since it was written.
