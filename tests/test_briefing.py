"""Offline tests for the highest-risk pure logic: tier budget, clustering
assembly, quote reconstitution and rendering. No API calls, no network.

Run: .venv\\Scripts\\python -m pytest tests -q     (or: python tests/test_briefing.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from render import build_stories, reconstitute, render_briefing
from summarise import MAX_SIGNIFICANT_PER_EPISODE, _enforce_tier_budget, repair_anchors


def _item(stream="top_of_government", tier="significant", ids=None, inst=False, why="why"):
    return {
        "tier": tier,
        "stream": stream,
        "why": why,
        "segment_ids": ids if ids is not None else [0, 1, 2, 3, 4],
        "institutional_memory": inst,
    }


def _transcript(show="Test Show", n=40):
    return {
        "metadata": {
            "show": show,
            "title": "An Episode",
            "published": "2026-07-24",
            "author": "Someone",
            "whisper_model": "medium",
        },
        # 20s segments, each a complete sentence (long runs cross the paragraph
        # threshold). Real Whisper segments often are NOT complete sentences —
        # see the ellipsis tests below for that case.
        "segments": [
            {"id": i, "start": i * 20, "end": (i + 1) * 20, "text": f"Sentence{i}."} for i in range(n)
        ],
    }


def test_tier_budget_caps_and_prioritises_core_patch():
    items = [
        _item(stream="top_of_government", why="westminster"),
        _item(stream="treasury_fiscal", why="treasury"),
        _item(stream="parliamentary_colour", why="colour"),
        _item(stream="crown_estate", why="core patch"),
        _item(stream="energy_desnz", why="energy"),
        _item(stream="top_of_government", inst=True, why="institutional memory"),
    ]
    kept = [i for i in _enforce_tier_budget(items) if i["tier"] == "significant"]
    assert len(kept) == MAX_SIGNIFICANT_PER_EPISODE
    whys = {i["why"] for i in kept}
    # Core patch beats Westminster; institutional memory beats plain items.
    assert {"core patch", "energy"} <= whys, whys
    assert "institutional memory" in whys, whys


def test_tier_budget_demotes_verbatim_not_paraphrase():
    items = [_item(ids=list(range(10)), why=f"item{n}") for n in range(5)]
    out = _enforce_tier_budget(items)
    demoted = [i for i in out if i["tier"] == "fragment"]
    assert demoted, "expected demotions"
    for d in demoted:
        # Still a consecutive run starting at the original opening: verbatim,
        # just shorter. Never rewritten.
        assert d["segment_ids"] == list(range(d["segment_ids"][0], d["segment_ids"][0] + len(d["segment_ids"])))
        assert len(d["segment_ids"]) <= 3


def test_tier_budget_leaves_small_episodes_alone():
    items = [_item(why="a"), _item(tier="fragment", why="b")]
    assert [i["tier"] for i in _enforce_tier_budget(items)] == ["significant", "fragment"]


def test_reconstitute_is_verbatim_and_paragraphed():
    t = _transcript()
    quote, ts = reconstitute(_item(ids=list(range(9))), t)
    assert ts == "~00:00"
    # Every word survives, in order — paragraphing adds whitespace only.
    assert quote.split() == [f"Sentence{i}." for i in range(9)]
    assert "\n\n" in quote, "long passage should be broken into paragraphs"
    short, _ = reconstitute(_item(ids=[0, 1]), t)
    assert "\n\n" not in short, "short passage should stay in one paragraph"


def test_midsentence_quote_is_marked_with_an_ellipsis():
    """39% of real quotes opened mid-clause. Mark the clip honestly rather than
    pretending the speaker started there — and never drop words to tidy it."""
    t = _transcript()
    t["segments"][4]["text"] = "and helping ferment the revolt that took place"
    t["segments"][5]["text"] = "which nobody expected"
    quote, _ = reconstitute(_item(ids=[4, 5]), t)
    assert quote.startswith("… and helping ferment"), quote
    assert quote.rstrip().endswith("…"), quote
    # Lossless: every original word is still present.
    for word in ("ferment", "revolt", "nobody", "expected"):
        assert word in quote


def test_clean_sentence_quote_gets_no_ellipsis():
    t = _transcript()
    quote, _ = reconstitute(_item(ids=[2, 3]), t)
    assert not quote.startswith("…") and not quote.rstrip().endswith("…"), quote


def test_build_stories_picks_fullest_treatment_as_primary():
    t1, t2 = _transcript("Show A"), _transcript("Show B")
    episodes = [
        {"transcript": t1, "items": [_item(tier="fragment", ids=[0, 1], why="brief mention")]},
        {"transcript": t2, "items": [_item(ids=list(range(8)), why="full treatment")]},
    ]
    stories = build_stories(episodes, [[0, 1]])
    assert len(stories) == 1
    assert stories[0]["primary"][0]["why"] == "full treatment"
    assert stories[0]["primary"][1]["metadata"]["show"] == "Show B"
    assert len(stories[0]["others"]) == 1


def test_render_shows_corroboration_only_for_multi_source():
    t1, t2 = _transcript("Show A"), _transcript("Show B")
    episodes = [
        {"transcript": t1, "items": [_item(why="shared story")]},
        {"transcript": t2, "items": [_item(why="shared story too")]},
        {"transcript": t1, "items": [_item(stream="treasury_fiscal", why="solo story")]},
    ]
    stories = build_stories(episodes, [[0, 1], [2]])
    _, text, html = render_briefing("Friday 24 July 2026", stories)
    assert "Also on: Show" in text
    assert text.count("Also on:") == 1, "solo story must not claim corroboration"
    assert "2 stories" in text, "orientation line missing"
    for body in (text, html):
        assert "shared story" in body and "solo story" in body


def test_multiple_passages_from_one_episode_are_grouped():
    """Several quotes from one episode should read as one source with several
    extracts — cited once, not three times over."""
    t = _transcript("Political Currency")
    episodes = [{"transcript": t, "items": [
        _item(ids=[0, 1, 2], why="first point"),
        _item(ids=[10, 11, 12], why="second point"),
        _item(ids=[20, 21, 22], why="third point"),
    ]}]
    stories = build_stories(episodes, [[0], [1], [2]])
    _, text, html = render_briefing("Friday 24 July 2026", stories)

    # The episode title is stated once, not once per passage.
    assert text.count("An Episode") == 1, text
    assert "3 passages" in text and "3 passages" in html
    assert text.count("same episode") == 3, "each passage should cite its timestamp only"
    assert "dotted" in html, "passages should be separated by a dotted rule"
    for why in ("first point", "second point", "third point"):
        assert why in text and why in html


def test_single_passage_keeps_its_full_citation():
    t1, t2 = _transcript("Show A"), _transcript("Show B")
    episodes = [
        {"transcript": t1, "items": [_item(why="only item here")]},
        {"transcript": t2, "items": [_item(why="other show item")]},
    ]
    stories = build_stories(episodes, [[0], [1]])
    _, text, _ = render_briefing("Friday 24 July 2026", stories)
    assert "same episode" not in text, "lone passages must keep the full source line"
    assert "passages" not in text
    assert "Show A" in text and "Show B" in text


def test_anchor_repairs_a_mispointed_quote():
    """The model's note and its segment IDs sometimes disagree; trust the note's
    locator and re-point the quote rather than shipping a mismatch."""
    segs = _transcript(n=60)["segments"]
    segs[40]["text"] = "The Treasury is quietly cooling on carbon capture."
    item = _item(ids=[10, 11, 12], why="Treasury cooling on CCS")
    item["anchor"] = "The Treasury is quietly cooling"
    stats = repair_anchors([item], segs)
    assert stats["repaired"] == 1, stats
    assert item["segment_ids"][0] == 40, item["segment_ids"]
    assert len(item["segment_ids"]) == 3, "keeps the original passage length"


def test_anchor_leaves_correct_items_alone():
    segs = _transcript(n=60)["segments"]
    segs[10]["text"] = "The Treasury is quietly cooling on carbon capture."
    item = _item(ids=[10, 11], why="Treasury cooling")
    item["anchor"] = "The Treasury is quietly cooling"
    stats = repair_anchors([item], segs)
    assert stats["ok"] == 1 and stats["repaired"] == 0
    assert item["segment_ids"] == [10, 11]


def test_unlocatable_anchor_never_drops_the_item():
    """Dom's call: a slightly mismatched item beats a missing one."""
    segs = _transcript(n=30)["segments"]
    item = _item(ids=[5, 6], why="something")
    item["anchor"] = "words that appear nowhere in this transcript at all"
    stats = repair_anchors([item], segs)
    assert stats["unlocatable"] == 1
    assert item["segment_ids"] == [5, 6], "item must survive unchanged"


def test_render_survives_empty_day():
    _, text, _ = render_briefing("Friday 24 July 2026", [])
    assert "Nothing notable today" in text


if __name__ == "__main__":
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
            passed += 1
    print(f"\n{passed} tests passed")
