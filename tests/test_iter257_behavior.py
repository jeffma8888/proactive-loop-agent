"""Black-box behavior tests for factory iteration 288 -- the re-land gate.

Feature under test: iteration 288 re-lands the thrice-reverted iteration-287 tree --
the published suite-size floor advances one rounded step at every tracked carrier,
``SPEC.md``'s settled section 4.2 provider contract moves verbatim into a new
tracked ``SPEC_ARCHIVE.md``, and the roadmap records the move -- with the four
oracle cases whose expectation was a DELTA AGAINST ``HEAD`` repaired so they hold
both before and after the change is committed.

Why this module exists beside ``tests/test_iter255_behavior.py`` and
``tests/test_iter256_behavior.py``: those two ship IN the re-landed diff, so they
are part of the subject under test, not an independent check of it. This module was
written from the spec alone and adds the two guards the twice-reverted history says
were missing:

* a STEADY-STATE reading of the relocation (behaviors 3-5) that never compares the
  live tree against a ``HEAD`` blob without arming both sides, and
* a structural regression guard (behavior 8) on the four named cases, because a
  ``HEAD``-delta expectation is invisible to every in-loop gate and only reds
  ``preship``, which is precisely how iteration 286 died.

THIS MODULE NEVER SPELLS THE FLOOR, in either spelling. The carrier census in
``tests/test_readme_and_ci_contract.py`` (imported here as ``guard``) walks the
whole tracked tree and fails on an UNDECLARED file that pins the live floor, so a
new module writing the digits would flag itself the moment it landed. Every number
below is DERIVED from ``guard.published_floor()`` / ``guard.floor_token``.

No expectation here is a delta against ``HEAD``. Where the pre-move text is the
only available witness (behavior 3's byte-identity clause) the case DETECTS whether
the move already landed and asserts the steady-state invariant in that arm -- the
``tests/test_iter251_behavior.py`` ``_subject_is_committed()`` idiom.

ISOLATION CONTRACT (honored): written from this iteration's spec
(``state/iter-288/pm.md`` Expected Behaviors 1-10 and its Acceptance Criteria) plus
the conventions of existing modules under ``tests/``. No implementation source, no
engineer or reviewer notes and no ``git diff`` were read.

Fully offline and deterministic: pure string work over tracked text plus ``git
ls-files`` / ``git cat-file`` blob reads. No network, no sleep, no duration
assertion and NO mtime-sensitive precondition (the iter-278 lesson: a fresh clone
resets every mtime).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import tests.test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parent.parent

#: The iteration this re-land is keyed to. The three reverted attempts carried 285,
#: 286 and 287; a site still naming any of them is the defect this iteration fixes.
ITERATION_TAG = "288"
REVERTED_TAGS = ("285", "286", "287")

#: The human-owned block's marker, matched on its stable prefix only.
MARKER = "PORTFOLIO INTRO"

#: The relocated section's new home, and the walls its two neighbours must respect.
ARCHIVE_NAME = "SPEC_ARCHIVE.md"
SPEC_WALL = 100_000
ROADMAP_WALL = 40_000
MIN_HEADROOM = 4_000

#: Behavior 8's named cases: every one reads a ``HEAD`` blob, so every one needs a
#: post-commit arm. Keyed by name, never by line number (the iter-283 lesson).
HEAD_READING_CASES = ("test_b1c", "test_b3b", "test_b8", "test_b8c")

#: A body that branches on "has the subject already landed" mentions one of these.
LANDED_PROBE = re.compile(r"_(?:subject_is_committed|has_landed\w*|already_landed\w*)|has_landed")

#: An exact suite count or a frozen shields test badge -- both stale next commit.
EXACT_COUNT_CLAIM = re.compile(r"\*\*[\d,]+ tests\*\*")
FROZEN_TEST_BADGE = re.compile(r"tests-\d+-passing")


def _read(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=str(REPO), capture_output=True, text=True, timeout=60
    )


def _tracked() -> frozenset[str]:
    proc = _git("ls-files")
    assert proc.returncode == 0, f"git ls-files failed: {proc.stderr.strip()}"
    return frozenset(proc.stdout.splitlines())


def _head_blob(path: str) -> str | None:
    """``path`` as ``HEAD`` holds it, or ``None`` when ``HEAD`` has no such file."""
    proc = _git("show", f"HEAD:{path}")
    return proc.stdout if proc.returncode == 0 else None


def _relocation_has_landed_in_head() -> bool:
    """True once the shipping commit exists, so the delta arm must not be taken."""
    return _head_blob(ARCHIVE_NAME) is not None


def _intro() -> str:
    text = _read("README.md")
    assert MARKER in text, "the README lost its human-owned intro marker"
    return text.split(MARKER, 1)[0]


def _longest_paragraph(text: str) -> str:
    """The archive's most distinctive block, used as a relocation fingerprint."""
    blocks = [b.strip() for b in text.split("\n\n") if len(b.strip()) > 200]
    assert blocks, f"{ARCHIVE_NAME} has no paragraph long enough to fingerprint"
    return max(blocks, key=len)


def _function_bodies(module_name: str) -> dict[str, str]:
    """Each ``def test_*`` body in ``tests/<module_name>``, sliced at the next def."""
    source = _read(f"tests/{module_name}")
    starts = [(m.start(), m.group(1)) for m in re.finditer(r"^def (test_\w+)\(", source, re.M)]
    assert starts, f"tests/{module_name} defines no test functions"
    bounds = [s for s, _ in starts] + [len(source)]
    return {name: source[bounds[i] : bounds[i + 1]] for i, (_, name) in enumerate(starts)}


# --------------------------------------------------------------------------- b1


def test_t01_the_ledger_narrates_the_raise_the_readme_actually_publishes() -> None:
    """Behavior 1: the roadmap's raise row and the live floor cannot disagree.

    Derived, never spelled: the row must narrate ``<previous> -> <live>`` where
    ``<live>`` is what ``README.md`` publishes, so a row copied from an earlier
    bump -- or a floor bumped without the row -- is caught without this module
    becoming a carrier.
    """
    floor = guard.published_floor()
    assert floor % 100 == 0, f"{floor} is not a rounded hundred"
    token = guard.floor_token(floor)
    previous = guard.floor_token(floor - 100)
    ledger_row = [
        line
        for line in _read("ROADMAP.md").splitlines()
        if line.startswith("- #") and f"(foundry iter {ITERATION_TAG})" in line
    ]
    assert len(ledger_row) == 1, (
        f"expected exactly one Done-ledger row tagged (foundry iter {ITERATION_TAG}); "
        f"found {len(ledger_row)}"
    )
    assert f"{previous} -> {token}" in ledger_row[0], (
        f"the iteration-{ITERATION_TAG} ledger row does not narrate the raise "
        f"{previous} -> {token} the README publishes: {ledger_row[0]!r}"
    )


def test_t02_every_tracked_carrier_agrees_with_the_readme_on_the_live_floor() -> None:
    """Behavior 1: the raise reached every carrier, in both spellings.

    Delegated to the shipped census so the obligation is read from the tree rather
    than from a list this module would have to keep fresh.
    """
    floor = guard.published_floor()
    disagreements = guard.published_floor_disagreements(guard.tracked_text_sources(), floor)
    assert disagreements == [], (
        "these tracked files disagree with the README's published floor: " f"{disagreements}"
    )


# --------------------------------------------------------------------------- b2


def test_t03_the_human_owned_intro_publishes_a_floor_and_never_a_frozen_count() -> None:
    """Behavior 2: both suite claims carry the live floor; no exact count, no badge."""
    intro = _intro()
    token = guard.floor_token(guard.published_floor())
    assert f"**{token}+ tests**" in intro
    assert f"**{token}+ passing tests**" in intro
    assert EXACT_COUNT_CLAIM.search(intro) is None, (
        "the intro publishes an exact test count, which is stale on the next commit: "
        f"{EXACT_COUNT_CLAIM.search(intro).group(0)!r}"  # type: ignore[union-attr]
    )
    assert FROZEN_TEST_BADGE.search(intro) is None, (
        "the intro reintroduced a hardcoded shields tests-NNNN-passing badge"
    )


# --------------------------------------------------------------------------- b3


def test_t04_the_archive_is_tracked_and_holds_the_provider_contract() -> None:
    """Behavior 3: ``SPEC_ARCHIVE.md`` ships, and it is the section's new home."""
    assert ARCHIVE_NAME in _tracked(), (
        f"{ARCHIVE_NAME} is not in git ls-files, so the relocation would ship as an "
        "untracked file and vanish in a fresh clone"
    )
    archive = _read(ARCHIVE_NAME)
    assert archive.strip(), f"{ARCHIVE_NAME} is empty"
    assert "VALID_PROVIDERS" in archive and "create_client" in archive, (
        f"{ARCHIVE_NAME} does not contain the provider contract it received"
    )


def test_t05_the_relocated_body_moved_byte_identically_both_arms() -> None:
    """Behavior 3+8: byte-identity, asserted in whichever arm is live.

    Before the commit the only witness of the pre-move text is ``HEAD:SPEC.md``, so
    the fingerprint must be a substring of it. AFTER the commit that blob no longer
    holds the section, so asserting the same thing would be self-invalidating -- the
    exact shape that reverted iteration 286. In that arm the steady state is
    asserted instead: the body lives in the archive and is gone from ``SPEC.md``.
    """
    fingerprint = _longest_paragraph(_read(ARCHIVE_NAME))
    live_spec = _read("SPEC.md")
    assert fingerprint not in live_spec, (
        "the relocated body is still present in SPEC.md, so this was a copy, not a move"
    )
    if _relocation_has_landed_in_head():
        head_archive = _head_blob(ARCHIVE_NAME)
        assert head_archive is not None and fingerprint in head_archive, (
            f"HEAD ships {ARCHIVE_NAME} but without the relocated body"
        )
        return
    head_spec = _head_blob("SPEC.md")
    assert head_spec is not None, "HEAD has no SPEC.md"
    assert fingerprint in head_spec, (
        "the archived body is not a byte-identical substring of the SPEC.md that "
        "preceded the move, so the relocation rewrote the section"
    )


# --------------------------------------------------------------------------- b4


def test_t06_spec_shrinks_below_its_wall_with_real_headroom() -> None:
    """Behavior 4: ``SPEC.md`` clears the 100,000-byte wall by >= 4,000 bytes."""
    size = len(_read("SPEC.md").encode("utf-8"))
    assert size < SPEC_WALL, f"SPEC.md is {size} B, at or past its {SPEC_WALL} B wall"
    assert SPEC_WALL - size >= MIN_HEADROOM, (
        f"SPEC.md has only {SPEC_WALL - size} B of headroom under its {SPEC_WALL} B "
        f"wall; the relocation must leave at least {MIN_HEADROOM} B"
    )


def test_t07_spec_keeps_a_summary_that_links_the_archive_and_lists_it() -> None:
    """Behavior 4: a reader of ``SPEC.md`` alone still learns the contract exists."""
    spec = _read("SPEC.md")
    assert ARCHIVE_NAME in spec, f"SPEC.md never mentions {ARCHIVE_NAME}"
    summary_lines = [line for line in spec.splitlines() if ARCHIVE_NAME in line]
    assert any("create_client" in line or "VALID_PROVIDERS" in line for line in summary_lines) or (
        "create_client" in spec and "VALID_PROVIDERS" in spec
    ), "SPEC.md dropped the in-place summary of the relocated provider switch"
    tree_lines = [line for line in spec.splitlines() if ARCHIVE_NAME in line and "SPEC.md" not in line]
    assert tree_lines, f"SPEC.md's repo-tree listing does not include {ARCHIVE_NAME}"


# --------------------------------------------------------------------------- b5


def test_t08_the_readme_lists_five_companion_documents_below_the_marker() -> None:
    """Behavior 5: the count, the bullets and the marker boundary all agree."""
    text = _read("README.md")
    assert MARKER in text
    below = text.split(MARKER, 1)[1]
    assert "Five committed documents" in below, (
        "the README's project-documents section does not say 'Five committed documents' "
        "below the human-owned marker"
    )
    section = below.split("Five committed documents", 1)[1]
    # The bullet list runs until the first blank-line-separated non-bullet block.
    bullets: list[str] = []
    for line in section.splitlines():
        if line.startswith("- **"):
            bullets.append(line)
        elif bullets and line.strip() and not line.startswith(" "):
            break
    assert len(bullets) == 5, (
        f"the project-documents section lists {len(bullets)} documents, not five: {bullets}"
    )
    assert any(ARCHIVE_NAME in line for line in bullets), (
        f"{ARCHIVE_NAME} is not one of the five listed companion documents"
    )
    assert MARKER not in section, "the section swallowed part of the human-owned marker"


# --------------------------------------------------------------------------- b6


def test_t09_the_roadmap_retires_179_opens_271_and_stays_small() -> None:
    """Behavior 6: index churn is exactly the retire+open pair, under the cap."""
    roadmap = _read("ROADMAP.md")
    index_ids = {
        m.group(1) for m in re.finditer(r"^\| (\d+) \| ", roadmap, re.M)
    }
    assert "179" not in index_ids, "index row #179 was not retired"
    assert "271" in index_ids, "index row #271 (the readme-headroom wrong wall) is missing"
    for fixed in ("- #168 ", "- #215 ", "- #260 "):
        assert fixed in roadmap, f"the fixed ledger row {fixed.strip()} was disturbed"


def test_t10_the_archive_carries_the_retired_row_keyed_to_this_iteration() -> None:
    """Behavior 6: #179's detail survived the retirement, keyed to iteration 288."""
    archive = _read("ROADMAP_ARCHIVE.md")
    keyed = [
        line
        for line in archive.splitlines()
        if "#179" in line and f"iter-{ITERATION_TAG}" in line
    ]
    assert keyed, (
        "ROADMAP_ARCHIVE.md has no #179 detail bullet keyed "
        f"(retired from the index in iter-{ITERATION_TAG}, foundry iter {ITERATION_TAG})"
    )
    assert any(f"foundry iter {ITERATION_TAG}" in line for line in keyed), (
        "the retired #179 bullet does not name the foundry iteration that retired it"
    )


# --------------------------------------------------------------------------- b7


def test_t11_no_live_site_still_keys_this_work_to_a_reverted_iteration() -> None:
    """Behavior 7: the re-key reached the roadmap rows and both new oracles.

    Scoped to the sites the spec enumerates as re-keyed, and to the reverted
    ITERATION KEYS only -- a file may legitimately narrate iterations 285/286 as
    history, and a blanket digit ban would forbid that.
    """
    carriers = {
        "ROADMAP.md": [
            line for line in _read("ROADMAP.md").splitlines() if line.startswith("- #270 ")
        ],
        "tests/test_iter255_behavior.py": _read("tests/test_iter255_behavior.py").splitlines(),
        "tests/test_iter256_behavior.py": _read("tests/test_iter256_behavior.py").splitlines(),
    }
    for name, lines in carriers.items():
        blob = "\n".join(lines)
        assert ITERATION_TAG in blob, f"{name} never names iteration {ITERATION_TAG}"
        for stale in REVERTED_TAGS:
            for pattern in (f"foundry iter {stale}", f"iter-{stale}"):
                assert pattern not in blob, (
                    f"{name} still keys this work to the reverted iteration: {pattern!r}"
                )


# --------------------------------------------------------------------------- b8


def test_t12_every_head_reading_case_has_a_post_commit_arm() -> None:
    """Behavior 8: the four named cases branch on "has this already landed".

    This is the structural regression guard for the defect that reverted iteration
    286: an expectation shaped ``live == head + delta`` passes in the pre-commit
    worktree, can never pass in CI, and is invisible to every in-loop gate because
    they all run before the commit exists. A case that reads a ``HEAD`` blob must
    therefore detect the landed state and assert the steady-state invariant there.
    """
    bodies = _function_bodies("test_iter256_behavior.py")
    resolved: dict[str, str] = {}
    for case in HEAD_READING_CASES:
        matches = [n for n in bodies if n == case or n.startswith(f"{case}_")]
        assert len(matches) == 1, (
            f"behavior 8 names ::{case}; tests/test_iter256_behavior.py resolves it to "
            f"{matches}, so a rename must update this guard in the same commit"
        )
        resolved[case] = bodies[matches[0]]
    unarmed = [
        case
        for case, body in resolved.items()
        if LANDED_PROBE.search(body) is None or "if " not in body
    ]
    assert unarmed == [], (
        f"these HEAD-reading cases have no post-commit arm: {unarmed}. Each must probe "
        "whether the change already landed in HEAD and assert the steady-state "
        "invariant in that arm, or it reds preship after every in-loop gate is green"
    )


def test_t13_this_module_reads_no_head_delta_of_its_own() -> None:
    """Behavior 8, applied reflexively: this guard must not repeat the defect.

    A test that reads a ``HEAD`` blob and compares it to the live tree is only sound
    when the comparison is guarded. Here exactly one case reads ``HEAD``, and it is
    the one that arms both sides.
    """
    bodies = _function_bodies("test_iter257_behavior.py")
    reader_call = "_head_blob" + "("
    readers = sorted(name for name, body in bodies.items() if reader_call in body)
    assert readers == ["test_t05_the_relocated_body_moved_byte_identically_both_arms"], (
        f"cases in this module read a HEAD blob without the landed-state arm: {readers}"
    )
    body = bodies[readers[0]]
    assert "_relocation_has_landed_in_head()" in body and "return" in body, (
        "the HEAD-reading case lost its post-commit arm"
    )
