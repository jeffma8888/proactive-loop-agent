"""Black-box behavior tests for foundry iteration 318 -- six settled Done-ledger rows
(#273-#278) shrink to terse stubs in ``ROADMAP.md`` while their full text moves VERBATIM
into a block-quoted section of ``ROADMAP_ARCHIVE.md``, buying the index measured headroom
under the ledger char pin ``tests/test_iter241_behavior.py::test_b09c`` owns.

WHY THIS ITERATION EXISTS. Every ship appends one Done-ledger row, and at HEAD the index
sat one row under the pin, so the mandatory row was a guaranteed red that only a Markdown
reword could clear -- the failure class that reverted three earlier iterations. The fix is
not a wider pin (that would only move the tax) but less prose in the index: the record is
conserved by relocating it, never by deleting it.

WHAT THIS MODULE GRADES. One collected item, funded net-zero by retiring one byte-identical
duplicate elsewhere (the binding-headroom gauge sat exactly at ``MIN_BINDING_HEADROOM``, so
a second item would red ``test_iter263::test_b6`` and ``test_iter270::test_b7``). The item
pins the RELOCATION INVARIANT rather than today's char count: every block-quoted original
in the archive's "trimmed to stubs" section has exactly one live ``- #NNN `` stub in the
index, the stub carries the same ``(foundry iter N)`` tag and is strictly shorter, and the
ship that did the trimming has its own ledger record. The headroom number itself is a
commit-time measurement for the tester's report: a bound like ``< 34_428`` would both red
the roadmap-size census ``test_iter172`` owns and re-create the tax the iteration repays.

ISOLATION CONTRACT (honored). Written from the spec's Expected Behaviors and acceptance
criteria; nothing under ``src/`` was read and no ``git diff`` was consulted. The artifacts
under test are the two Markdown files, read as text.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_INDEX = _REPO / "ROADMAP.md"
_ARCHIVE = _REPO / "ROADMAP_ARCHIVE.md"

#: The archive section the relocation ships under; its heading names the foundry iteration.
_SECTION = re.compile(r"^## Ledger prose trimmed to stubs in ROADMAP\.md \(foundry iter (\d+)\)$")
#: A live Done-ledger row in the index (the shape ``tests/test_roadmap_ledger_conservation``
#: and ``tests/test_iter264_behavior.py`` parse); a block-quoted line never matches.
_LEDGER_ROW = re.compile(r"^- #(\d+) (.*)$")
#: A relocated original: the SAME row shape, block-quoted so no ledger parser counts it.
_QUOTED_ORIGINAL = re.compile(r"^> - #(\d+) (.*)$")
_SHIP_TAG = re.compile(r"\(foundry iter (\d+)\)")


def _section_body(archive: str) -> tuple[int, list[str]]:
    """``(foundry iteration named by the heading, lines up to the next ``## `` heading)``."""
    lines = archive.splitlines()
    starts = [i for i, line in enumerate(lines) if _SECTION.match(line)]
    assert len(starts) == 1, (
        f"the archive must hold exactly one 'trimmed to stubs' section; found {len(starts)}"
    )
    start = starts[0]
    match = _SECTION.match(lines[start])
    assert match is not None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines)
    )
    return int(match.group(1)), lines[start + 1 : end]


def test_b1_every_archived_original_has_one_shorter_same_tagged_stub_and_the_ship_is_recorded() -> None:
    """Behavior 1 (acceptance: stubs stay, originals archived verbatim, ship recorded).

    For every block-quoted ``> - #NNN`` original in the archive section: exactly one live
    ``- #NNN`` row survives in the index, that row still ends in the SAME
    ``(foundry iter N)`` tag as the original, and the index row is strictly shorter than
    the archived text (the prose was trimmed, not duplicated). The originals are not
    ledger rows themselves (the block-quote keeps them out of every ``^- #`` parser), and
    the iteration that did the trimming left its own Done-ledger record.
    """
    index = _INDEX.read_text(encoding="utf-8")
    archive = _ARCHIVE.read_text(encoding="utf-8")
    ship_iter, body = _section_body(archive)

    originals = {
        int(m.group(1)): m.group(2)
        for line in body
        if (m := _QUOTED_ORIGINAL.match(line)) is not None
    }
    assert len(originals) >= 6, (
        f"the section must archive at least the six rows the iteration trimmed; found "
        f"{sorted(originals)}"
    )
    stray = [line for line in body if _LEDGER_ROW.match(line)]
    assert stray == [], (
        f"an archived original that is NOT block-quoted would be read as a second ledger "
        f"row by every '- #NNN' parser: {stray[:2]}"
    )

    rows: dict[int, list[str]] = {}
    for line in index.splitlines():
        if (m := _LEDGER_ROW.match(line)) is not None:
            rows.setdefault(int(m.group(1)), []).append(m.group(2))

    for row_id, original in sorted(originals.items()):
        stubs = rows.get(row_id, [])
        assert len(stubs) == 1, (
            f"row #{row_id} must survive in ROADMAP.md as exactly one '- #{row_id} ' stub "
            f"(count and position of the ledger are conserved); found {len(stubs)}"
        )
        (stub,) = stubs
        assert len(stub) < len(original), (
            f"row #{row_id}: the index text ({len(stub)} chars) must be STRICTLY shorter "
            f"than the archived original ({len(original)} chars) -- a relocation that "
            "leaves the prose in both places buys no headroom"
        )
        stub_tag = _SHIP_TAG.search(stub)
        original_tag = _SHIP_TAG.search(original)
        assert stub_tag is not None and original_tag is not None, (
            f"row #{row_id}: both the stub and the original must end in a "
            f"'(foundry iter N)' tag; stub={stub!r}"
        )
        assert stub_tag.group(1) == original_tag.group(1), (
            f"row #{row_id}: the stub's ship tag {stub_tag.group(0)!r} must equal the "
            f"original's {original_tag.group(0)!r} -- the record's provenance is conserved"
        )

    recorded = [
        text
        for texts in rows.values()
        for text in texts
        if f"(foundry iter {ship_iter})" in text
    ]
    assert len(recorded) == 1, (
        f"the trimming ship (foundry iter {ship_iter}) must itself hold exactly one "
        f"Done-ledger row in ROADMAP.md; found {len(recorded)}: {recorded}"
    )
    assert "stub" in recorded[0].lower() and "archiv" in recorded[0].lower(), (
        f"the ship's own row must say what moved and where: {recorded[0]!r}"
    )
