"""Independent second opinion on factory iteration 303 -- sixteen byte-identical copies
of the six-spelling registry/version freeze guard retire from ``tests/``, one canonical
copy of each family survives, and a duplicate-body census ratchets the count down.

MODULE NAME, derived from the repo and never from the state-dir counter (the 2026-08-19
operator pin). The state dir is ``iter-411`` while the shipping tag is ``foundry iter
303``, so the two counters differ by 108 and that offset is NOT arithmetic anyone may
reuse. The name was derived the mandated way: ``git ls-files tests`` tops out at
``test_iter262_behavior.py``, +1 = ``263``, and ``git cat-file -e
HEAD:tests/test_iter263_behavior.py`` FAILED before a byte was written (the worktree
path was absent too, so nothing was overwritten). The file was then ``git add -N``-ed
BEFORE any census in this module measured the tree, so the instrument sees itself.

WHY THIS MODULE COLLECTS EXACTLY NINE ITEMS, and why the number is a measured
constraint rather than a style choice. The published floor opens a window of
``SUITE_ROUNDING_WINDOW`` collected items above itself, and factory iteration 301's
gauge reported ``binding_headroom=0`` -- the next collected item ANYWHERE would have
red-carded a public build. This iteration's sixteen deletions bought that room back
(``make readme-headroom`` -> ``binding_headroom=16``), and the spec spends at most ten
of it so ``binding_headroom`` lands at or above six. Nine arms leave one item of slack
for the next iteration's repair round.

WHAT IT GRADES. Expected Behaviors 1-7 of the iteration spec, in order, plus the
acceptance criterion that no ``src/`` file and no dependency moved. The census
instrument itself is two-sided on SYNTHETIC SOURCE TEXT before it is ever pointed at
the corpus, because a census that silently stops recognizing its own subject reports a
clean zero forever (this repo has paid for that shape more than once, which is why
every corpus arm below also asserts a fail-open floor on how many modules it reached).

THE NORMALIZATION IS A DELIBERATE, DOCUMENTED CHOICE, and the spec is ambiguous on it.
Behavior 4 asks for bodies compared "after dropping the ``def`` line, the docstring,
blank lines and comments, and collapsing whitespace". Whitespace is collapsed WITHIN
each surviving line (so indentation and run-length differences cannot hide a copy), and
line structure is PRESERVED. That reading is the one the iteration is coherent under:
it makes the census exactly as strong as the Feature statement asks for -- it reds a
re-added BYTE-IDENTICAL collected test -- while a stricter reading that also collapsed
newlines would flag three further copies whose only difference from a surviving
canonical copy is line WRAPPING, and deleting those would violate Behavior 3's pinned
per-module remainders. The three are named in the PM feedback of this iteration's
``tester.md`` as a follow-up bite, not silently absorbed here.

ISOLATION CONTRACT (honored). Every assertion is written from this iteration's spec
(``pm.md`` Expected Behaviors 1-7 and its Acceptance Criteria), from the repo's own
``tests/`` conventions, and from the product's OBSERVABLE output obtained by RUNNING
it. **No file under ``src/`` was read, no engineer's or reviewer's note was opened, no
``IMPLEMENTATION.patch`` and no ``git diff`` was inspected.** Fully offline and
deterministic: the census is a pure function of source text, and the one nested child
this module starts is the shipped ``--collect-only`` helper the floor guard already
owns. Nothing is written inside the product repo.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import tests.test_readme_and_ci_contract as guard

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: Behavior 7: the ledger line this iteration adds, and the tag it must cite.
LEDGER_ROW = "284"
SHIP_TAG = "foundry iter 303"

#: Behavior 6: the floor for ``binding_headroom`` after this commit. The published
#: floor itself is NEVER spelled here -- it is read out of the README through
#: ``guard.published_floor()`` so this module can never become a stale carrier.
MIN_BINDING_HEADROOM = 6

#: Behavior 5. The corpus-wide redundant-definition total, MEASURED on the tree this
#: commit ships (this module included) rather than transcribed from the spec.
#: RATCHET DIRECTION: this number may only ever go DOWN. Raising it is never a fix --
#: a rise records that a byte-identical collected test was re-added, which is the exact
#: defect the sixteen deletions below retired.
REDUNDANT_TEST_DEFINITIONS: int = 6

#: Behavior 1. The sixteen ``(module, function)`` pairs that must be ABSENT.
DELETED: dict[str, tuple[str, ...]] = {
    "test_iter82_behavior.py": (
        "test_b6_tool_registry_count_unchanged",
        "test_b6_provider_count_unchanged",
        "test_b6_version_frozen",
    ),
    "test_iter83_behavior.py": (
        "test_b8_tool_registry_count_unchanged",
        "test_b8_cli_subcommand_count_unchanged",
    ),
    "test_iter85_behavior.py": ("test_eb7_registry_counts_and_version_frozen",),
    "test_iter87_behavior.py": (
        "test_b7_tool_count_unchanged",
        "test_b7_provider_count_unchanged",
    ),
    "test_iter89_behavior.py": (
        "test_b7_tool_registry_count_unchanged",
        "test_b7_cli_subcommand_count_unchanged",
        "test_b7_provider_count_unchanged",
        "test_b7_version_frozen",
    ),
    "test_iter90_behavior.py": (
        "test_b7_tool_registry_count_unchanged",
        "test_b7_cli_subcommand_count_unchanged",
        "test_b7_version_frozen",
    ),
    "test_iter91_behavior.py": ("test_b08_registry_counts_and_version_unchanged",),
}

#: Behavior 3. The measured remainder each edited module must still collect. The spec
#: pins these exactly, and a module that empties would be a DELETED module -- which
#: ``tests/test_iter150_behavior.py`` separately forbids.
REMAINDERS: dict[str, int] = {
    "test_iter82_behavior.py": 10,
    "test_iter83_behavior.py": 11,
    "test_iter85_behavior.py": 7,
    "test_iter87_behavior.py": 14,
    "test_iter89_behavior.py": 12,
    "test_iter90_behavior.py": 19,
    "test_iter91_behavior.py": 17,
}

MIN_REMAINDER = 7

#: Behavior 2. One canonical copy of each of the six families, at a named address,
#: paired with the OTHER modules that held a copy of the same family before this
#: commit. THE RULE THAT CHOSE EVERY KEEPER, stated once: the LOWEST-numbered shipped
#: module holding a family keeps it. That rule is not merely narrated -- the arm below
#: re-derives the minimum from these holder sets and fails if a keeper is not it.
FAMILIES: dict[tuple[str, str], tuple[str, ...]] = {
    ("test_iter81_behavior.py", "test_b8_tool_registry_count_unchanged"): (
        "test_iter82_behavior.py",
        "test_iter83_behavior.py",
        "test_iter87_behavior.py",
        "test_iter89_behavior.py",
        "test_iter90_behavior.py",
    ),
    ("test_iter81_behavior.py", "test_b8_provider_count_unchanged"): (
        "test_iter82_behavior.py",
        "test_iter87_behavior.py",
        "test_iter89_behavior.py",
    ),
    ("test_iter81_behavior.py", "test_b8_version_frozen"): (
        "test_iter82_behavior.py",
        "test_iter89_behavior.py",
        "test_iter90_behavior.py",
    ),
    ("test_iter82_behavior.py", "test_b6_cli_subcommand_count_unchanged"): (
        "test_iter83_behavior.py",
        "test_iter89_behavior.py",
        "test_iter90_behavior.py",
    ),
    ("test_iter84_behavior.py", "test_eb6_registry_counts_and_version_frozen"): (
        "test_iter85_behavior.py",
    ),
    ("test_iter88_behavior.py", "test_b08_registry_counts_and_version_unchanged"): (
        "test_iter91_behavior.py",
    ),
}

_MODULE_NUMBER = re.compile(r"^test_iter(\d+)_behavior\.py$")
_WHITESPACE_RUN = re.compile(r"\s+")
_EMPTY_BODY = "<no statements>"


# ===========================================================================
# THE CENSUS INSTRUMENT -- Behavior 4. Pure functions of SOURCE TEXT. No path is
# accepted, nothing is read from disk, so every branch is reachable from a string
# literal and the synthetic arm below can prove both sides of the predicate.
# ===========================================================================
def code_lines(source_text: str) -> list[str]:
    """``source_text`` with every comment token blanked out, one entry per input line.

    Comments are removed by TOKENIZING rather than by looking for ``#``, so a ``#``
    inside a string literal is not mistaken for a comment and a trailing comment on a
    code line is removed as reliably as a whole-line one. Behavior 4 requires that a
    difference in comments alone still group, and a naive ``startswith('#')`` filter
    would leave the trailing case ungrouped.
    """
    lines = source_text.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(source_text).readline):
        if token.type is tokenize.COMMENT:
            row, column = token.start
            lines[row - 1] = lines[row - 1][:column]
    return lines


def body_fingerprint(
    lines: Sequence[str], node: ast.FunctionDef | ast.AsyncFunctionDef
) -> str:
    """The comparable body of one function: no ``def`` line, no docstring, no blank
    line, whitespace collapsed inside each surviving line, line structure kept.
    """
    body = list(node.body)
    if body:
        head = body[0]
        if (
            isinstance(head, ast.Expr)
            and isinstance(head.value, ast.Constant)
            and isinstance(head.value.value, str)
        ):
            body = body[1:]
    if not body:
        return _EMPTY_BODY
    first = body[0].lineno
    last = max(node.end_lineno or node.lineno for node in body)
    kept = [
        _WHITESPACE_RUN.sub(" ", raw.strip()) for raw in lines[first - 1 : last]
    ]
    return "\n".join(line for line in kept if line)


def normalized_test_bodies(source_text: str) -> dict[str, str]:
    """One module's SOURCE TEXT -> ``{collected test function name: fingerprint}``.

    Only module-level ``test_``-prefixed functions are collected subjects; a helper or
    a method on a ``Test`` class is deliberately out of the census's domain, because
    the defect this ratchets is a padded COLLECTED count.
    """
    lines = code_lines(source_text)
    return {
        node.name: body_fingerprint(lines, node)
        for node in ast.parse(source_text).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    }


def duplicate_body_groups(sources: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    """``{label: source text}`` -> ``{fingerprint: ('label::name', ...)}``, groups only.

    A group is any fingerprint shared by two or more collected tests. Labels are
    opaque strings the caller chooses; nothing here opens a file, so the corpus arms
    and the synthetic arms drive the identical code path.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for label in sorted(sources):
        for name, fingerprint in normalized_test_bodies(sources[label]).items():
            grouped[fingerprint].append(f"{label}::{name}")
    return {
        fingerprint: tuple(members)
        for fingerprint, members in grouped.items()
        if len(members) > 1
    }


def redundant_definition_total(sources: Mapping[str, str]) -> int:
    """How many collected definitions could be deleted with nothing lost: every group
    of ``n`` byte-equivalent bodies contributes ``n - 1``.
    """
    return sum(len(members) - 1 for members in duplicate_body_groups(sources).values())


# ===========================================================================
# Helpers -- reading the live tree.
# ===========================================================================
def _read(name: str) -> str:
    return (TESTS_DIR / name).read_text(encoding="utf-8")


def _collected(name: str) -> tuple[str, ...]:
    return tuple(normalized_test_bodies(_read(name)))


def _corpus() -> dict[str, str]:
    """Every module pytest collects from ``tests/``, keyed by file name.

    Filesystem glob, NOT ``git ls-files``: an untracked new module would otherwise sit
    outside the domain and the census would be blind to itself (OPERATOR 2026-08-14).
    """
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(TESTS_DIR.glob("test_*.py"))
    }


def _intro() -> str:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert guard.MARKER in text, "README lost its human-owned marker"
    return text.split(guard.MARKER, 1)[0]


def _module_number(name: str) -> int:
    match = _MODULE_NUMBER.match(name)
    assert match is not None, f"{name} is not a numbered behavior module"
    return int(match.group(1))


# ===========================================================================
# Behavior 1 -- the sixteen duplicates are gone.
# ===========================================================================
def test_b1_the_sixteen_duplicate_copies_are_absent() -> None:
    """Behavior 1: none of the sixteen named ``(module, function)`` pairs is still a
    collected test. Resolved by AST, not by grep, so a name that survives only inside
    a comment or a docstring is not mistaken for a deletion that did not happen.
    """
    survivors: list[str] = []
    for module, functions in sorted(DELETED.items()):
        collected = set(_collected(module))
        survivors += [f"{module}::{fn}" for fn in functions if fn in collected]
    assert sum(len(v) for v in DELETED.values()) == 16, "the delete list is not sixteen"
    assert survivors == [], (
        f"these duplicate copies were supposed to retire and still collect: {survivors}"
    )


# ===========================================================================
# Behavior 2 -- exactly one canonical copy of each family, at the named address,
# and the address obeys the stated rule.
# ===========================================================================
def test_b2_one_canonical_copy_per_family_survives_at_the_lowest_module() -> None:
    """Behavior 2: each of the six keepers still collects, and each keeper's module is
    genuinely the LOWEST-numbered module that held its family -- the rule is re-derived
    from the holder sets rather than trusted as prose.
    """
    missing: list[str] = []
    misplaced: list[str] = []
    for (module, function), others in sorted(FAMILIES.items()):
        if function not in _collected(module):
            missing.append(f"{module}::{function}")
        holders = (module, *others)
        lowest = min(holders, key=_module_number)
        if lowest != module:
            misplaced.append(f"{module}::{function} but {lowest} is lower-numbered")
    assert len(FAMILIES) == 6, "six families, one canonical copy each"
    assert missing == [], f"these canonical copies were deleted by mistake: {missing}"
    assert misplaced == [], (
        f"the keeper is not the lowest-numbered holder of its family: {misplaced}"
    )
    assert sorted({m for m, _ in FAMILIES}) == [
        "test_iter81_behavior.py",
        "test_iter82_behavior.py",
        "test_iter84_behavior.py",
        "test_iter88_behavior.py",
    ]


# ===========================================================================
# Behavior 3 -- no module was deleted and none emptied.
# ===========================================================================
def test_b3_every_edited_module_still_exists_and_still_collects() -> None:
    """Behavior 3: all seven edited modules are still files, each still collects at
    least seven tests, and each collects EXACTLY the measured remainder the spec pins.
    """
    for module, expected in sorted(REMAINDERS.items()):
        path = TESTS_DIR / module
        assert path.is_file(), f"{module} was deleted -- this iteration removes FUNCTIONS"
        live = len(_collected(module))
        assert live >= MIN_REMAINDER, f"{module} collects only {live} tests"
        assert live == expected, (
            f"{module} collects {live} tests, but the spec pins {expected} after the "
            "deletion -- either more or fewer functions left than were authorized"
        )
    assert sorted(REMAINDERS) == sorted(DELETED), (
        "the remainder table and the delete table must name the same seven modules"
    )


# ===========================================================================
# Behavior 4 -- the instrument is exported, takes source TEXT, and is two-sided,
# proven on synthetic strings before it is pointed at the corpus.
# ===========================================================================
def test_b4_the_census_is_two_sided_on_synthetic_source_text() -> None:
    """Behavior 4: identical bodies group; a one-token difference does not; a
    difference only in the docstring or in a comment still groups. Driven entirely
    from string literals, so the instrument is proven to need no filesystem at all.
    """
    identical = (
        "def test_alpha() -> None:\n"
        "    assert len(REGISTRY) == 14\n"
        "def test_beta() -> None:\n"
        "    assert len(REGISTRY) == 14\n"
    )
    assert duplicate_body_groups({"synthetic.py": identical}) == {
        "assert len(REGISTRY) == 14": (
            "synthetic.py::test_alpha",
            "synthetic.py::test_beta",
        )
    }

    one_token = (
        "def test_alpha() -> None:\n"
        "    assert len(REGISTRY) == 14\n"
        "def test_beta() -> None:\n"
        "    assert len(REGISTRY) == 15\n"
    )
    assert duplicate_body_groups({"synthetic.py": one_token}) == {}, (
        "a one-token difference is a different assertion and must NOT group"
    )

    prose_only = (
        "def test_alpha() -> None:\n"
        '    """The tool registry is frozen."""\n'
        "    assert len(REGISTRY) == 14\n"
        "def test_beta() -> None:\n"
        '    """Wholly different words, same assertion."""\n'
        "    # and a comment the sibling does not carry\n"
        "    assert len(REGISTRY) == 14  # trailing, too\n"
    )
    assert duplicate_body_groups({"synthetic.py": prose_only}) == {
        "assert len(REGISTRY) == 14": (
            "synthetic.py::test_alpha",
            "synthetic.py::test_beta",
        )
    }, "a docstring or a comment is narrative, not behavior -- these are duplicates"

    indented = (
        "def test_alpha() -> None:\n"
        "    assert  len(REGISTRY)   ==  14\n"
        "def test_beta() -> None:\n"
        "    assert len(REGISTRY) == 14\n"
    )
    assert len(duplicate_body_groups({"synthetic.py": indented})) == 1, (
        "whitespace inside a line is collapsed, so re-spacing cannot hide a copy"
    )

    helpers = (
        "def helper() -> None:\n"
        "    assert len(REGISTRY) == 14\n"
        "def test_alpha() -> None:\n"
        "    assert len(REGISTRY) == 14\n"
    )
    assert duplicate_body_groups({"synthetic.py": helpers}) == {}, (
        "a non-collected helper is out of the census's domain"
    )
    assert redundant_definition_total({"a.py": identical, "b.py": identical}) == 3


# ===========================================================================
# Behavior 5 -- the ratchet holds on the shipped tree.
# ===========================================================================
def test_b5_the_ratchet_constant_matches_the_shipped_corpus() -> None:
    """Behavior 5: on the live ``tests/`` tree the instrument reports ZERO duplicate
    copies for each of the six canonical families, and the corpus-wide redundant total
    equals the exported constant. Both sides matter: the second is the ratchet, and
    the first is what this iteration actually paid for.
    """
    corpus = _corpus()
    assert len(corpus) >= 100, (
        f"corpus scan reached only {len(corpus)} modules -- the glob is fail-open"
    )
    assert Path(__file__).name in corpus, (
        "the census cannot see its own module, so its zero proves nothing"
    )
    groups = duplicate_body_groups(corpus)
    still_duplicated: list[str] = []
    for module, function in sorted(FAMILIES):
        address = f"{module}::{function}"
        for members in groups.values():
            if address in members:
                still_duplicated.append(f"{address} -> {list(members)}")
    assert still_duplicated == [], (
        "these canonical copies still have a byte-equivalent sibling in the corpus, so "
        f"the retirement is incomplete: {still_duplicated}"
    )
    total = redundant_definition_total(corpus)
    assert total == REDUNDANT_TEST_DEFINITIONS, (
        f"the corpus now holds {total} redundant collected definitions but this module "
        f"pins {REDUNDANT_TEST_DEFINITIONS}. This number may only go DOWN: if it ROSE, "
        "a byte-identical collected test was re-added -- delete it instead of raising "
        "the constant. If it FELL, lower the constant in the same commit."
    )
    assert groups, "a corpus with zero duplicate groups would mean the census died"


# ===========================================================================
# Behavior 6 -- the wall moved and the published floor stays true.
# ===========================================================================
def test_b6_the_binding_wall_reopened_and_the_published_floor_is_still_true() -> None:
    """Behavior 6: the gauge reports at least ``MIN_BINDING_HEADROOM`` items of room
    again, the published floor is unchanged and still TRUE, and the slack wall is
    untouched. The floor is never spelled in this file -- it is read out of the README
    through the guard, so this module cannot become a stale seventh carrier.
    """
    floor = guard.published_floor()
    live = guard.collect_live_test_count()
    report = guard.headroom_report(_intro(), live)
    fields = dict(
        (key, int(value))
        for key, value in re.findall(r"(\w+)=(\d+)", report)
    )
    assert fields["published"] == floor, report
    assert fields["floor"] == floor, report
    assert fields["live"] == live, report
    assert live >= floor, report
    assert fields["red_at"] == floor + guard.SUITE_SIZE_SLACK, report
    assert fields["binding_at"] == floor + guard.SUITE_ROUNDING_WINDOW + 1, report
    assert fields["binding_headroom"] >= MIN_BINDING_HEADROOM, (
        "the deletions were supposed to reopen the collected-item window, but the "
        f"gauge still reports {fields['binding_headroom']} items of room: {report}"
    )
    assert guard.suite_size_problems(_intro(), live) == [], (
        "the published floor is no longer true or fresh after the deletions"
    )


# ===========================================================================
# Behavior 7 -- the record lands in ROADMAP.md and nowhere else.
# ===========================================================================
def test_b7_exactly_one_ledger_line_records_the_ship_and_the_archive_gains_nothing() -> (
    None
):
    """Behavior 7: ``ROADMAP.md`` gains exactly ONE plain ``- #284 ...`` ledger line
    citing this ship's tag, and the archive gains no bullet for the same row (a row
    created and shipped in one iteration never entered the index).

    THE FILE'S CHAR CEILING IS DELIBERATELY NOT ASSERTED HERE, and that omission is a
    measured decision rather than a gap. The spec's Behavior 7 also names a 36,000-char
    working ceiling, but ``tests/test_iter172_behavior.py`` runs a two-sided census over
    every module that bounds this document's size: an unsanctioned bound value reds
    ``test_no_tracked_module_bounds_the_document_at_an_unsanctioned_number`` and a new
    bounding module reds ``test_the_modules_bounding_the_document_equal_the_documented
    _allowlist``. I measured both firing on this module before removing the bound. The
    ceiling is already owned, on the allowlist, by ``tests/test_roadmap_size_budget.py``
    (``CHAR_LIMIT`` 40,000) with ``tests/test_iter214_behavior.py``'s headroom floor and
    ``tests/test_iter241_behavior.py``'s tighter literal on top -- so re-asserting it
    here would be a SEVENTH copy of an opinion this very iteration exists to retire.
    """
    roadmap = ROADMAP.read_text(encoding="utf-8")
    archive = ARCHIVE.read_text(encoding="utf-8")
    ledger = [
        line
        for line in roadmap.splitlines()
        if line.startswith(f"- #{LEDGER_ROW} ")
    ]
    assert len(ledger) == 1, f"expected exactly one ledger line for the row: {ledger}"
    assert SHIP_TAG in ledger[0], (
        f"the ledger line must cite the shipping tag verbatim: {ledger[0]!r}"
    )
    assert f"#{LEDGER_ROW}" not in archive, (
        "a row recorded in BOTH documents reds the ledger-conservation guard"
    )
    assert not re.search(rf"^\| {LEDGER_ROW} \|", roadmap, re.M), (
        "this row never entered the open index, so it must not appear as a table row"
    )


def test_b7b_the_floor_row_is_retired_and_recorded_in_both_documents() -> None:
    """Behavior 7, second half, RE-KEYED by the commit that PAYS row #282.

    What this graded before: the row stays QUEUED, and one line adjacent to the table
    voids the stale collected-item count the row was priced with. Both obligations
    died the moment the row shipped -- the correction cannot outlive the row it
    corrects, and a guard that still demands an open ``| 282 |`` row would veto the
    very commit the row existed to request (it did, for three attempts). What
    survives, and is what the guard was ever for, is the ACCOUNTING: a row that
    leaves the index is recorded in the shipped shape in BOTH documents, never
    silently dropped.
    """
    roadmap = ROADMAP.read_text(encoding="utf-8")
    lines = roadmap.splitlines()
    assert [line for line in lines if line.startswith("| 282 |")] == [], (
        "row #282 shipped in factory iter 307; it must not be an open index row again"
    )
    stale_note = [
        line
        for line in lines
        if "#282" in line and "readme-headroom" in line and not line.startswith("| ")
    ]
    assert stale_note == [], (
        "the note that voided row #282's stale collected-item price outlived the row "
        f"it corrected: {stale_note}"
    )
    ledger = [line for line in lines if line.startswith("- #282 ")]
    assert len(ledger) == 1, f"exactly one Done-ledger row must record #282: {ledger}"
    archive = ARCHIVE.read_text(encoding="utf-8")
    assert "- **#282 --" in archive, (
        "row #282 left the index leaving no retirement bullet in ROADMAP_ARCHIVE.md"
    )


# ===========================================================================
# Behaviors 2-4 -- the ONE worktree-keyed ``src/`` veto retires, and the shape it
# regressed to is ratcheted shut so no successor can re-add it silently.
# ===========================================================================
def test_ac_every_src_status_guard_is_provenance_gated() -> None:
    """Behaviors 2-4. This iteration deletes
    ``test_ac_no_source_or_dependency_moved_in_this_commit`` -- the one copy of the
    "a tests-only iteration touches no product code" criterion that sampled
    ``git status --porcelain`` over the LIVE worktree with NO provenance gate, which
    makes it a standing veto over every successor that edits product code rather than
    a claim about its own commit. The criterion is NOT weakened by the deletion: four
    provenance-gated siblings still assert it, and they are named here as literal
    strings so a blanket deletion of the family reds this module --
    ``test_iter245_behavior.py::test_b13_this_iteration_touches_nothing_under_src``,
    ``test_iter251_behavior.py::test_b10b_this_iteration_touches_no_source_or_dependency_file``,
    ``test_iter255_behavior.py::test_b9_the_relocation_ships_no_source_or_dependency_change``,
    ``test_iter256_behavior.py::test_b10b_the_iteration_touched_no_source_and_no_lockfile``.

    THE CENSUS IS BODY-LEVEL, NOT CALL-LEVEL, and that is a measured requirement
    rather than a convenience. Three of the four siblings pass NO pathspec at all --
    they filter in Python and reach ``src`` through a separate
    ``git show --name-only`` call -- and the fourth splats a module constant, so a
    predicate scoped to one call's argument list matches ONLY the function this
    commit deletes (measured: 1 match at HEAD, 0 after) and the non-vacuity floor
    below could never be satisfied.

    THE GATE TOKENS ARE SPELLED INSIDE THIS BODY ON PURPOSE. ``_corpus()`` globs the
    filesystem rather than ``git ls-files``, so this oracle is inside its own domain
    (``test_b5`` asserts exactly that self-visibility). Hoisting the tuple to module
    scope would leave this body carrying the trigger tokens and no gate, and the
    census would then report ITSELF as the sole violation.
    """
    gates = ("ITERATION_TAG", "_move_has_landed_in_head", "(foundry iter ")
    siblings = (
        (
            "test_iter245_behavior.py",
            "test_b13_this_iteration_touches_nothing_under_src",
        ),
        (
            "test_iter251_behavior.py",
            "test_b10b_this_iteration_touches_no_source_or_dependency_file",
        ),
        (
            "test_iter255_behavior.py",
            "test_b9_the_relocation_ships_no_source_or_dependency_change",
        ),
        (
            "test_iter256_behavior.py",
            "test_b10b_the_iteration_touched_no_source_and_no_lockfile",
        ),
    )
    sources = _corpus()
    assert len(sources) >= 200, (
        f"fail-open floor: the census reached only {len(sources)} modules, so a clean "
        "verdict would prove nothing"
    )

    matched: list[str] = []
    ungated: list[str] = []
    for module in sorted(sources):
        lines = code_lines(sources[module])
        for node in ast.parse(sources[module]).body:
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            body = body_fingerprint(lines, node)
            if not ("status" in body and "--porcelain" in body and "src" in body):
                continue
            matched.append(f"{module}::{node.name}")
            if not any(gate in body for gate in gates):
                ungated.append(f"{module}::{node.name}")

    assert ungated == [], (
        "Behavior 2: a collected test that samples `git status --porcelain` over "
        "`src` MUST key the sample to its own commit -- naming one of "
        f"{gates} -- or it becomes a permanent veto over every successor that edits "
        f"product code, which is the defect this iteration retires: {ungated}"
    )
    assert len(matched) >= 4, (
        "Behavior 3: the census must not be able to pass by matching nothing -- the "
        "four provenance-gated siblings are expected to match, plus this oracle "
        f"itself, but the predicate found {matched}"
    )
    for module, function in siblings:
        assert module in sources, (
            f"Behavior 4: {module} carries one of the four gated copies of this "
            "acceptance criterion and left the corpus"
        )
        assert f"def {function}(" in sources[module], (
            f"Behavior 4: {module}::{function} is one of the four provenance-gated "
            "guards that carry the acceptance criterion after this deletion, so it "
            "must survive; the criterion is asserted four times, not zero"
        )
