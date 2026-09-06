"""Black-box behavior tests for factory iteration 288 -- the first ``SPEC.md`` slice.

Feature under test (retired roadmap row #179): ``SPEC.md`` reached 99,791 bytes
against the ``< 100_000`` action point its own budget oracle asserts, so the
settled ``### 4.2 llm/providers.py`` contract body is relocated byte-for-byte
into a new tracked ``SPEC_ARCHIVE.md``, leaving the heading and a terse pointer
behind. Nothing is rewritten: this is a move, and the value is headroom under a
budget that governs every stage's largest required read.

WHY THESE ASSERTIONS ARE PROVENANCE-GATED RATHER THAN HEAD-EQUAL
Two cases here want to compare the worktree to ``HEAD`` -- "is the relocated
prose byte-identical to what the vision said?" and "did anything ELSE in the
vision move?". Both questions are only answerable while ``HEAD`` still holds the
pre-move document, i.e. before this iteration commits. An earlier iteration
shipped three such cases keyed to its own commit and they were red for every
successor, halting the loop; and here a successor MUST be able to edit ``SPEC.md``
(section 4.5 is where each new capability is documented) and MUST be able to
archive a second settled section. So each of those two cases reads its own
provenance first and asserts the pre-move fact only on the pre-move branch. The
post-move branch is not a skip: it asserts the durable half of the same claim --
that the archived prose is byte-identical to the blob ``HEAD`` now carries for
it, and that it has not crept back into ``SPEC.md``. Every other case here is an
invariant that stays true forever (a heading occurs once, a pointer is short and
names the archive, a companion is linked below the marker, an exemption entry is
gone, a ledger row exists with its tag), so none of them can rot.

NO AMBIENT LOCAL STATE. Every fact is read from tracked bytes or from ``git``,
never from an mtime, a gitignored path or a ``.venv`` artifact, so this module
measures the same tree in a throwaway fresh clone as it does here. Nothing is
written inside the product repo, no subprocess runs the product, and there is no
network use.

ISOLATION CONTRACT (honored): every assertion is written against this
iteration's spec ("Expected Behaviors" in the state dir's ``pm.md``) and the
repo's own conventions under ``tests/``. **No file under ``src/`` was read, no
engineer's, reviewer's or fix note was opened, and no ``git diff`` was
inspected** -- the byte-faithfulness question is answered by asking ``git`` for
whole blobs instead.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parent.parent

#: The section that moves, and the heading that terminates it. Split on these exact
#: heading lines -- never on offsets, which every edit invalidates.
MOVED_HEADING: Final[str] = "### 4.2 llm/providers.py"
NEXT_HEADING: Final[str] = "### 4.3 scout"

ARCHIVE_NAME: Final[str] = "SPEC_ARCHIVE.md"

#: Anti-vacuity floor for the relocation: a truncated or empty move must not pass.
MIN_ARCHIVED_BYTES: Final[int] = 5_000

#: Behavior 3. The action point the vision's budget oracle enforces, and the ceiling
#: this iteration must land under so the guard stays a guard instead of a wall.
SPEC_ACTION_POINT: Final[int] = 100_000
SPEC_CEILING_AFTER_SLICE: Final[int] = 95_500

#: Behavior 2. The pointer left in place of the body: a summary plus a link, not prose.
MAX_POINTER_BYTES: Final[int] = 500

#: Behavior 6. The human-owned block no automated contributor may restructure.
MARKER: Final[str] = "PORTFOLIO INTRO"

#: Behavior 6. The ONE claim above that marker an automated contributor is not merely
#: permitted but REQUIRED to correct: the rounded suite-size floor. This relocation
#: ships fused with a published-floor raise, so the intro legitimately differs from
#: ``HEAD`` in exactly these digits; matching the token instead of the number keeps this
#: module from becoming a floor carrier itself.
FLOOR_CLAIM: Final[re.Pattern[str]] = re.compile(r"\*\*\d,\d00\+( passing)? tests\*\*")

#: Behavior 8. This iteration's Done-ledger id and the tag its commit subject carries.
LEDGER_ROW_PREFIX: Final[str] = "- #270 "
ITERATION_TAG: Final[str] = "(foundry iter 288)"
MAX_LEDGER_ROW_CHARS: Final[int] = 200

#: Behavior 8. The index row this iteration retires.
#:
#: Behavior 8(d) -- ROADMAP.md keeping >= 4,000 chars of headroom under its 40,000-char
#: ceiling -- is deliberately NOT asserted here. ``tests/test_iter172_behavior.py``
#: censuses every module that bounds that document's size against an allowlist whose
#: sanctioned numbers are DERIVED from ``tests/test_roadmap_size_budget.py``, the
#: declared owner; a second bound in this module makes the real budget "whichever
#: assertion is tightest, documented nowhere". The owner and
#: ``tests/test_iter214_behavior.py`` both run in this same suite, so 8(d) is covered
#: without planting a rival bound.
RETIRED_ROW_ID: Final[str] = "#179"

#: Behavior 8(e). The retirement-bullet total the roadmap-history oracle declares. A
#: successor that retires another row raises it, so this is a floor, not a pin.
MIN_RETIREMENT_BULLET_TOTAL: Final[int] = 78

#: Behavior 7. The two self-cleaning exemption maps that named the archive while it was
#: absent, each with the module that owns it.
EXEMPTION_MAPS: Final[tuple[tuple[str, str], ...]] = (
    ("tests/test_iter223_behavior.py", "CITED_BUT_UNTRACKED"),
    ("tests/test_iter224_behavior.py", "DECLARED_ABSENT"),
)


def _git(*args: str) -> str:
    proc = subprocess.run(
        ("git", *args), cwd=str(REPO), capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr}"
    return proc.stdout


def _head_text(rel: str) -> str:
    """The whole ``HEAD`` blob for ``rel`` -- a blob read, never a diff read."""
    return _git("show", f"HEAD:{rel}")


def _head_has(rel: str) -> bool:
    proc = subprocess.run(
        ("git", "cat-file", "-e", f"HEAD:{rel}"),
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode == 0


def _tracked() -> list[str]:
    paths = [line for line in _git("ls-files").splitlines() if line]
    assert paths, "`git ls-files` reported no tracked path at all"
    return paths


def _live(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"^#{1,6} ", line)]


def _section_body(text: str, heading: str, next_heading: str) -> str:
    """The text strictly BETWEEN two heading lines, both located by content."""
    start = text.index(heading)
    after_heading = text.index("\n", start) + 1
    end = text.index(next_heading, after_heading)
    return text[after_heading:end]


def _archived_slice() -> str:
    """The relocated region of the archive: its ``4.2`` heading through the end."""
    archive = _live(ARCHIVE_NAME)
    assert MOVED_HEADING in archive, (
        f"{ARCHIVE_NAME} does not carry {MOVED_HEADING!r}; behavior 1 wants the "
        "relocated section, heading included, moved verbatim"
    )
    return archive[archive.index(MOVED_HEADING) :]


def _archived_body() -> str:
    """The relocated body alone -- what must have LEFT ``SPEC.md``."""
    slice_ = _archived_slice()
    return slice_[slice_.index("\n") + 1 :]


def _move_has_landed_in_head() -> bool:
    """Has the relocation been committed yet?

    Before this iteration's commit, ``HEAD:SPEC.md`` still carries the body and the
    byte-faithfulness of the move is checkable against it. Afterwards it does not,
    and the durable question becomes whether the ARCHIVE blob is unchanged.
    """
    return _archived_body().rstrip("\n") not in _head_text("SPEC.md")


def test_b1_the_archive_is_tracked_and_carries_the_prose_verbatim() -> None:
    """Behavior 1: a tracked ``SPEC_ARCHIVE.md`` whose relocated text is a
    byte-identical substring of the blob that owned it, and is not a stub."""
    assert ARCHIVE_NAME in _tracked(), (
        f"{ARCHIVE_NAME} is not tracked; behavior 1 wants a git-tracked root companion, "
        "and an untracked file is absent in the fresh clone every ship is verified from"
    )

    slice_ = _archived_slice()
    size = len(slice_.encode("utf-8"))
    assert size >= MIN_ARCHIVED_BYTES, (
        f"the relocated slice is {size} bytes, below the {MIN_ARCHIVED_BYTES}-byte "
        "anti-vacuity floor -- a truncated relocation must not pass as a move"
    )

    body = _archived_body().rstrip("\n")
    if _move_has_landed_in_head():
        owner = f"HEAD:{ARCHIVE_NAME}"
        assert _head_has(ARCHIVE_NAME), (
            f"the move is committed (HEAD:SPEC.md no longer carries the body) but "
            f"{owner} does not exist -- the prose has no owner in HEAD at all"
        )
        assert body in _head_text(ARCHIVE_NAME), (
            f"the archived prose is not byte-identical to {owner}: this file is a "
            "verbatim relocation, so editing it here is a vision change wearing a "
            "move's clothes. Move the text back into SPEC.md and edit it there"
        )
    else:
        assert body in _head_text("SPEC.md"), (
            "the archived prose is NOT a byte-identical substring of HEAD:SPEC.md, so "
            "this is a rewrite rather than the byte-preserving move behavior 1 asks "
            "for. Re-slice from `git show HEAD:SPEC.md` with no reflowing or "
            "copy-editing"
        )


def test_b2_spec_keeps_the_heading_and_loses_the_body() -> None:
    """Behavior 2: the heading stays exactly once, the body is gone, and a short
    pointer naming the archive stands in its place."""
    spec = _live("SPEC.md")

    assert spec.count(MOVED_HEADING) == 1, (
        f"SPEC.md spells {MOVED_HEADING!r} {spec.count(MOVED_HEADING)} times; behavior 2 "
        "wants the heading kept byte-identical and kept exactly once"
    )
    assert NEXT_HEADING in spec, (
        f"SPEC.md lost {NEXT_HEADING!r}; the slice is bounded by that heading, so "
        "losing it means the move took a neighbour with it"
    )

    pointer = _section_body(spec, MOVED_HEADING, NEXT_HEADING)
    pointer_bytes = len(pointer.encode("utf-8"))
    assert pointer_bytes <= MAX_POINTER_BYTES, (
        f"the text left under {MOVED_HEADING!r} is {pointer_bytes} bytes, over the "
        f"{MAX_POINTER_BYTES}-byte pointer budget -- behavior 2 wants a one-paragraph "
        "summary plus a link, not a second copy of the contract"
    )
    assert ARCHIVE_NAME in pointer, (
        f"the text left under {MOVED_HEADING!r} never names {ARCHIVE_NAME}, so a reader "
        f"of SPEC.md cannot find the contract: {pointer!r}"
    )

    body = _archived_body().rstrip("\n")
    assert body not in spec, (
        "the archived body still occurs in SPEC.md -- this is a duplication, not a "
        "relocation, and it buys no headroom at all"
    )


def test_b3_the_budget_is_bought_back_without_moving_the_action_point() -> None:
    """Behavior 3: ``SPEC.md`` lands under the post-slice ceiling and the budget
    oracle's own ``100_000`` literal is untouched."""
    size = (REPO / "SPEC.md").stat().st_size
    assert size <= SPEC_CEILING_AFTER_SLICE, (
        f"SPEC.md is {size} bytes; behavior 3 wants <= {SPEC_CEILING_AFTER_SLICE}, i.e. "
        f">= {SPEC_ACTION_POINT - SPEC_CEILING_AFTER_SLICE} bytes of headroom under the "
        f"{SPEC_ACTION_POINT}-byte action point. Relocate more settled prose; do not "
        "raise the budget"
    )
    assert size == len((REPO / "SPEC.md").read_bytes()), "SPEC.md size read disagreed with itself"

    budget_oracle = "tests/test_iter234_behavior.py"
    literal = f"{SPEC_ACTION_POINT:_}"
    text = _live(budget_oracle)
    assert text.count(literal) == 1, (
        f"{budget_oracle} spells {literal} {text.count(literal)} times (expected 1). The "
        "action point may not be raised or duplicated by the same commit that spends "
        "the headroom it grants"
    )


def test_b4_nothing_else_in_the_vision_moved() -> None:
    """Behavior 4: with the moved body and the one new layout-fence line accounted
    for, the rest of ``SPEC.md`` is byte-identical to the blob it came from.

    Asserted by RECONSTRUCTION rather than by ``live == head`` or
    ``live.startswith(head)``, both of which are false by construction here: the
    edit is an interior replacement plus one interior insertion.
    """
    spec = _live("SPEC.md")
    head_spec = _head_text("SPEC.md")

    if _move_has_landed_in_head():
        body = _archived_body().rstrip("\n")
        assert body not in head_spec and body not in spec, (
            "the relocated body is back inside SPEC.md; the slice must live in the "
            f"archive only, so {ARCHIVE_NAME} and SPEC.md never disagree about it"
        )
        assert _headings(spec).count(MOVED_HEADING) == 1, (
            "SPEC.md must keep the moved section's heading even after the body leaves"
        )
        return

    head_body = _section_body(head_spec, MOVED_HEADING, NEXT_HEADING)
    live_pointer = _section_body(spec, MOVED_HEADING, NEXT_HEADING)

    start = spec.index(MOVED_HEADING)
    after_heading = spec.index("\n", start) + 1
    end = spec.index(NEXT_HEADING, after_heading)
    restored = spec[:after_heading] + head_body + spec[end:]

    fence_lines = [
        line for line in restored.splitlines(keepends=True) if ARCHIVE_NAME in line
    ]
    assert fence_lines, (
        f"nothing in SPEC.md names {ARCHIVE_NAME} outside the moved body -- behavior 5 "
        "wants the layout fence to carry it"
    )
    rebuilt = "".join(
        line for line in restored.splitlines(keepends=True) if ARCHIVE_NAME not in line
    )

    assert rebuilt == head_spec, (
        "restoring the moved body and dropping the lines that name the archive does NOT "
        f"reproduce HEAD:SPEC.md byte-for-byte (rebuilt {len(rebuilt)} chars vs "
        f"{len(head_spec)}), so something ELSE in the fixed intent changed. This "
        "iteration is a byte-preserving move: no copy-editing, no reflowing, no "
        '"while we are here"'
    )

    delta = len(head_spec.encode("utf-8")) - len(spec.encode("utf-8"))
    accounted = (
        len(head_body.encode("utf-8"))
        - len(live_pointer.encode("utf-8"))
        - sum(len(line.encode("utf-8")) for line in fence_lines)
    )
    assert delta == accounted, (
        f"SPEC.md shrank by {delta} bytes but the moved body minus the pointer minus the "
        f"new fence line accounts for {accounted}"
    )


def test_b5_the_layout_fence_names_the_new_file() -> None:
    """Behavior 5: the vision's own layout tree lists the new companion, so the
    document that describes the repo does not omit a file the repo now ships."""
    spec = _live("SPEC.md")
    fences = re.findall(r"```[^\n]*\n(.*?)```", spec, flags=re.DOTALL)
    assert fences, "SPEC.md carries no fenced block at all"

    naming = [block for block in fences if ARCHIVE_NAME in block]
    assert naming, (
        f"no fenced layout block in SPEC.md names {ARCHIVE_NAME}; behavior 5 wants the "
        "repo-layout tree to carry an entry for the new companion"
    )
    entry = next(
        line for block in naming for line in block.splitlines() if ARCHIVE_NAME in line
    )
    assert entry.strip(), f"the {ARCHIVE_NAME} fence entry is blank"
    assert "SPEC.md" in " ".join(
        line for block in naming for line in block.splitlines()
    ), "the layout block naming the archive no longer names SPEC.md itself"


def _neutralize_floor(intro: str) -> str:
    """``intro`` with its rounded suite-size digits replaced by a fixed placeholder.

    WHY neutralize instead of comparing raw bytes: this relocation ships in the same
    commit as the published-floor raise that seats its oracle, and that raise edits one
    carve-out number ABOVE the human-owned marker -- the one edit the README carve-out
    both permits and requires. Dropping the comparison would surrender the guarantee
    that nothing ELSE up there moved, so both slices are normalized instead and every
    other character still has to match ``HEAD`` byte for byte.
    """
    return FLOOR_CLAIM.sub(lambda match: f"**<floor>+{match.group(1) or ''} tests**", intro)


def test_b6_readme_links_the_new_companion_below_the_marker_only() -> None:
    """Behavior 6: every tracked root companion, the new one included, is linked
    below the human-owned marker -- and nothing above it gained a link."""
    readme = _live("README.md")
    assert MARKER in readme, f"README.md lost the {MARKER!r} marker"
    split = readme.index(MARKER)
    above, below = readme[:split], readme[split:]

    companions = sorted(
        path
        for path in _tracked()
        if "/" not in path and path.endswith(".md") and path != "README.md"
    )
    assert ARCHIVE_NAME in companions, (
        f"{ARCHIVE_NAME} is not a tracked root companion, so behavior 6 has nothing to link"
    )
    assert len(companions) >= 5, (
        f"only {len(companions)} root companions derived ({companions}) -- behavior 6 "
        "expects the archive to raise the domain to at least five"
    )

    for name in companions:
        link = f"]({name})"
        assert link in below, (
            f"{name} is tracked at the repo root but never linked below the "
            f"{MARKER!r} marker; add one bullet to README's project-documents list"
        )
        assert link not in above, (
            f"{name} is linked ABOVE the {MARKER!r} marker. The portfolio intro is "
            "human-owned: companion links belong in the reference sections below it"
        )

    if not _move_has_landed_in_head():
        head_readme = _head_text("README.md")
        head_above = head_readme[: head_readme.index(MARKER)]
        assert FLOOR_CLAIM.search(above) and FLOOR_CLAIM.search(head_above), (
            "neither slice matches FLOOR_CLAIM any more, so neutralizing it is a silent "
            "no-op and this comparison would pass for the wrong reason -- re-anchor the "
            "pattern rather than trusting the compare"
        )
        assert _neutralize_floor(above) == _neutralize_floor(head_above), (
            "the text ABOVE the human-owned marker differs from HEAD:README.md in "
            "something other than the sanctioned suite-size floor digits. Only the "
            "three carve-out numbers may ever change up there"
        )


def test_b7_both_declared_absent_exemptions_retire() -> None:
    """Behavior 7: the archive was excused in two self-cleaning maps while it was
    untracked; now that it is tracked, both entries are gone."""
    for module, map_name in EXEMPTION_MAPS:
        text = _live(module)
        anchor = f"{map_name}: Final[dict[str, str]] = {{"
        assert anchor in text, (
            f"{module} no longer declares {map_name} in the shape this case anchors on "
            f"({anchor!r}); re-anchor rather than deleting the check"
        )
        start = text.index(anchor) + len(anchor)
        body = text[start : text.index("\n}", start)]
        assert body.strip(), f"{map_name} in {module} parsed as empty -- the anchor slipped"
        assert ARCHIVE_NAME not in body, (
            f"{ARCHIVE_NAME!r} is tracked now -- delete its {map_name} entry in {module}. "
            "Both maps are two-directional, so a stale exemption reds the build"
        )


def test_b8_the_roadmap_records_this_iteration_in_this_commit() -> None:
    """Behavior 8: the index row retires into the archive, the Done ledger gains
    exactly one row for this iteration, and the roadmap keeps its headroom."""
    roadmap = _live("ROADMAP.md")
    archive = _live("ROADMAP_ARCHIVE.md")

    index_rows = [
        line for line in roadmap.splitlines() if re.match(r"^\|\s*\d+\s*\|", line)
    ]
    assert index_rows, "ROADMAP.md carries no index table rows at all"
    stale = [line for line in index_rows if re.match(r"^\|\s*179\s*\|", line)]
    assert not stale, (
        f"index row 179 is still in ROADMAP.md: {stale[0][:80]!r}... -- behavior 8 "
        "retires it into ROADMAP_ARCHIVE.md"
    )

    bullets = [
        line
        for line in archive.splitlines()
        if line.startswith("- **") and RETIRED_ROW_ID in line.split("--")[0]
    ]
    assert len(bullets) == 1, (
        f"ROADMAP_ARCHIVE.md carries {len(bullets)} retirement bullets keyed "
        f"{RETIRED_ROW_ID} (expected exactly 1)"
    )
    assert "|" not in bullets[0], (
        "the retirement bullet still carries pipe characters, so it can be parsed as an "
        "index table row; replace the pipes with field labels as the prior retirement did"
    )
    assert len(bullets[0]) > 400, (
        f"the {RETIRED_ROW_ID} retirement bullet is only {len(bullets[0])} chars -- it "
        "must hold the row's verbatim pre-move index text, not a one-line stub"
    )

    ledger = [line for line in roadmap.splitlines() if line.startswith(LEDGER_ROW_PREFIX)]
    assert len(ledger) == 1, (
        f"ROADMAP.md holds {len(ledger)} Done-ledger rows starting {LEDGER_ROW_PREFIX!r} "
        "(expected exactly 1 -- fold this iteration's information into its own row, "
        "never a second row)"
    )
    row = ledger[0]
    assert len(row) <= MAX_LEDGER_ROW_CHARS, (
        f"the ledger row is {len(row)} chars, over the {MAX_LEDGER_ROW_CHARS}-char budget"
    )
    assert row.endswith(ITERATION_TAG), (
        f"the ledger row must end with the tag {ITERATION_TAG!r} that the shipping "
        f"commit subject carries: {row!r}"
    )
    assert ARCHIVE_NAME in row, (
        f"the ledger row never names {ARCHIVE_NAME}, so the Done ledger does not record "
        f"what shipped: {row!r}"
    )

    subject = _git("log", "-1", "--format=%s").strip()
    if ITERATION_TAG in subject:
        assert subject.endswith(ITERATION_TAG), (
            f"the committed subject {subject!r} must end with {ITERATION_TAG!r} so the "
            "ledger tag and the commit subject agree verbatim"
        )

    history_oracle = "tests/test_iter214_behavior.py"
    totals = [
        int(match)
        for match in re.findall(r"sum\(counts\.values\(\)\)\s*==\s*(\d+)", _live(history_oracle))
    ]
    assert totals, (
        f"{history_oracle} no longer declares a retirement-bullet total in the shape this "
        "case reads; re-anchor rather than deleting the check"
    )
    assert min(totals) >= MIN_RETIREMENT_BULLET_TOTAL, (
        f"{history_oracle} declares a retirement-bullet total of {min(totals)}, below the "
        f"{MIN_RETIREMENT_BULLET_TOTAL} this iteration's retirement produces -- that "
        "oracle's own message says to bump the total and name the row you retired"
    )
    assert RETIRED_ROW_ID in _live(history_oracle), (
        f"{history_oracle} does not name {RETIRED_ROW_ID}, so the bumped total records no "
        "reason for the row that caused it"
    )


# --- Extension (retry round): the parts of behaviors 1 and 2, and of the spec's
# --- acceptance criteria, that the first round's checkpoint left uncovered.

#: Behavior 2. The pointer must be a resolvable RELATIVE Markdown link, not a bare
#: filename: a reader of the rendered SPEC has to be able to click through.
ARCHIVE_LINK: Final[str] = f"]({ARCHIVE_NAME})"

#: Behavior 1. The archive has to say what it is. Any ONE of these words in its header
#: satisfies that, so a successor may reword the header without reding the build.
ARCHIVE_PURPOSE_WORDS: Final[tuple[str, ...]] = ("relocat", "archive", "moved")

#: Acceptance criteria. Paths this documentation relocation must leave alone: a `src/`
#: edit puts `make typecheck` at risk, and lockfile drift reds CI's `uv sync --locked`.
UNTOUCHED_PATHS: Final[tuple[str, ...]] = ("src", "uv.lock", "pyproject.toml")


def test_b1b_the_archive_explains_itself_and_points_back_to_the_spec() -> None:
    """Behavior 1: the relocated prose sits under a short header that says what the
    file is and that ``SPEC.md`` is still the entry point.

    Without this, the archive is an orphaned wall of contract text and a reader who
    lands in it cannot tell settled history from live intent.
    """
    archive = _live(ARCHIVE_NAME)
    header = archive[: archive.index(MOVED_HEADING)]

    assert header.strip(), (
        f"{ARCHIVE_NAME} opens straight into {MOVED_HEADING!r} with no header at all; "
        "behavior 1 wants a short preamble saying what the file is"
    )
    assert _headings(header), (
        f"{ARCHIVE_NAME}'s preamble carries no Markdown heading, so the file renders "
        "without a title"
    )
    assert "SPEC.md" in header, (
        f"{ARCHIVE_NAME}'s header never names SPEC.md, so nothing tells a reader that "
        f"SPEC.md remains the entry point and the fixed intent: {header!r}"
    )
    lowered = header.lower()
    assert any(word in lowered for word in ARCHIVE_PURPOSE_WORDS), (
        f"{ARCHIVE_NAME}'s header uses none of {ARCHIVE_PURPOSE_WORDS}, so it does not "
        f"say that this is relocated prose rather than a new promise: {header!r}"
    )


def test_b2b_every_heading_survives_in_order_and_the_pointer_is_a_real_link() -> None:
    """Behavior 2, the half the pointer-size check does not reach: every heading the
    vision had is still there in the same relative order, and what replaced the body
    is a link rather than a mention.

    A relocation that silently dropped or reordered a neighbouring section would pass
    every size and substring check in this module, so the heading sequence is the
    invariant that actually pins "only 4.2's body moved".
    """
    spec = _live("SPEC.md")
    live_headings = _headings(spec)
    assert live_headings, "SPEC.md carries no Markdown heading at all"

    pointer = _section_body(spec, MOVED_HEADING, NEXT_HEADING)
    assert ARCHIVE_LINK in pointer, (
        f"the text under {MOVED_HEADING!r} names {ARCHIVE_NAME} but not as a relative "
        f"Markdown link ({ARCHIVE_LINK!r}), so the rendered SPEC has no way through to "
        f"the contract: {pointer!r}"
    )
    assert not _headings(pointer), (
        f"the pointer under {MOVED_HEADING!r} introduces headings of its own; behavior 2 "
        f"wants a one-paragraph summary plus a link: {pointer!r}"
    )

    if _move_has_landed_in_head():
        # Post-move, HEAD IS the sliced document, so comparing to it proves nothing.
        # The durable half of the same claim: the heading sequence is unambiguous and
        # the moved section still sits ahead of the one that bounded it.
        duplicated = sorted({h for h in live_headings if live_headings.count(h) > 1})
        assert not duplicated, (
            f"SPEC.md now spells these headings more than once: {duplicated}. A "
            "duplicated heading makes every content-anchored slice ambiguous"
        )
        assert live_headings.index(MOVED_HEADING) < live_headings.index(NEXT_HEADING), (
            f"{MOVED_HEADING!r} no longer precedes {NEXT_HEADING!r}, so the relocation "
            "reordered the document it was only supposed to shorten"
        )
        return

    head_headings = _headings(_head_text("SPEC.md"))
    lost = [h for h in head_headings if h not in live_headings]
    assert not lost, (
        f"SPEC.md lost {len(lost)} heading(s) the vision had, first {lost[:1]!r} -- this "
        "iteration relocates ONE section body and keeps every heading in place"
    )
    known = set(head_headings)
    assert [h for h in live_headings if h in known] == head_headings, (
        "SPEC.md's headings are all still present but no longer in the order "
        "HEAD:SPEC.md had them; a byte-preserving move may not reorder sections"
    )


def test_b9_the_relocation_ships_no_source_or_dependency_change() -> None:
    """Acceptance criteria: zero ``src/`` change and an untouched lockfile.

    Provenance-gated for the same reason behaviors 1 and 4 are: "did this pending
    change touch src?" is only answerable while the change is pending. Once it lands
    the tree is clean and the durable half is that the lockfile CI resolves against is
    still tracked and non-empty.
    """
    tracked = _tracked()
    assert "uv.lock" in tracked, (
        "uv.lock is not tracked, so CI's `uv sync --locked` has nothing to resolve "
        "against and every matrix leg reds"
    )
    assert (REPO / "uv.lock").stat().st_size > 0, "uv.lock is tracked but empty"

    if _move_has_landed_in_head():
        return

    porcelain = _git("status", "--porcelain", "--", *UNTOUCHED_PATHS)
    pending = [line for line in porcelain.splitlines() if line.strip()]
    assert not pending, (
        "this iteration is a documentation relocation that must ship zero source and "
        f"zero dependency change, but git reports pending edits under "
        f"{UNTOUCHED_PATHS}: {pending}. A src/ edit puts `make typecheck` at risk and "
        "lockfile drift reds CI's `uv sync --locked`"
    )
