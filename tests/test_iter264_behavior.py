"""Independent second opinion on factory iteration 304 -- the ONE worktree-keyed
``src/`` ban retires, a corpus ratchet keeps the shape out, and two self-declared-dead
roadmap rows move to the archive to pay for the Done-ledger record.

MODULE NAME, derived from the REPO and never from the state-dir counter (the 2026-08-19
operator pin). The foundry state dir for this ship is ``iter-417`` while the shipping tag
is ``foundry iter 304``: the two counters differ by 113 and that offset is not arithmetic
anyone may reuse. Derived the mandated way instead -- ``git ls-files tests`` tops out at
``test_iter263_behavior.py``, +1 = ``264``, and ``git cat-file -e
HEAD:tests/test_iter264_behavior.py`` FAILED (``path ... does not exist in 'HEAD'``)
before the first byte was written, with no worktree file at that path either. The module
was then ``git add -N``-ed BEFORE any census here measured the tree, so every
``git ls-files``-scoped instrument in this file sees ITSELF.

WHY THIS MODULE COLLECTS EXACTLY ONE ITEM, and why the number is a measured constraint
rather than a style choice. ``tests/test_iter263_behavior.py`` pins
``MIN_BINDING_HEADROOM = 6`` and asserts it against the LIVE tree with no provenance
gate, so the wall prices every collected item ANYWHERE in the suite, including this
module's. Measured with ``make readme-headroom`` on the tree under test, before this file
existed: ``live=5991 binding_at=5999 binding_headroom=7``. One new collected item lands
``binding_headroom`` at exactly 6, which is the floor; two would red a public build. So
the eight Expected Behaviors are graded as eight labelled sections of one function, each
with its own failure message, rather than as eight arms.

THE TRIGGER TOKENS ARE HOISTED TO MODULE SCOPE ON PURPOSE. The census below looks for a
function body that names ``git status``, ``--porcelain`` and ``src``, and the oracle in
``tests/test_iter263_behavior.py`` runs the same predicate over a filesystem glob that
INCLUDES this file. Spelling those three literals inside a ``test_``-prefixed body here
would make this module report itself -- so they live in module constants, which no
function body carries.

BEHAVIOR 2 IS AMBIGUOUS AND THE AMBIGUITY IS LOAD-BEARING; both readings are measured
here. The spec scopes the census to a function that names ``src`` "in the same call's
pathspec arguments", then requires the same census to match at least four functions.
Measured on the tree under test: the same-call reading matches **0** functions (three of
the four surviving siblings pass NO pathspec at all -- they filter in Python -- and the
fourth splats a module constant, so no single call carries all three literals), which
makes Behavior 3 unsatisfiable under the literal reading. The BODY-scoped reading matches
**5** and is the one the iteration is coherent under, so it is what the assertion uses;
the strict reading is asserted to be a SUBSET, which keeps the safety property true under
both. This is recorded as PM feedback in ``tester.md``, not silently absorbed.

ISOLATION CONTRACT (honored, no exception). Every assertion below is derived from this
iteration's spec (``pm.md`` Expected Behaviors 1-11 and its Acceptance Criteria), from the
two tracked Markdown documents themselves, and from the conventions of the existing
modules under ``tests/``. **No file under ``src/`` was read, no engineer's or reviewer's
note was opened, no ``IMPLEMENTATION.patch`` and no ``git diff`` was inspected.** Fully
offline and deterministic: every check is a pure function of tracked text, no subprocess
other than ``git ls-files``, no network, no mtime, no clock, and nothing is written inside
the product repo.

WHAT IS DELIBERATELY NOT ASSERTED HERE. Expected Behavior 10 ("``git status --porcelain
-- src uv.lock pyproject.toml`` is empty at commit time") is exactly the worktree-keyed
shape this iteration RETIRES: shipping it as a test would be caught by the census two
sections above it and would re-create the veto. It is verified out of band and reported in
``tester.md`` instead.

Expected Behaviors 8 and 9 are OWNED elsewhere and restating them here is not free -- a
first draft of this module did restate them and reded eight shipped censuses in one run:

* Behavior 8 (``len(ROADMAP.md)`` inside both walls). Any assert that bounds the size of
  this document makes the module a size-bounding module, and
  ``tests/test_iter172_behavior.py`` brakes that twice over: the VALUE census sanctions
  only the two numbers parsed out of ``tests/test_roadmap_size_budget.py`` (40000 and
  10000), so the binding ``35_428`` ratchet is by construction unsanctionable, and the
  MEMBERSHIP census freezes the set of bounding modules to a one-entry allowlist. The
  ratchet's owner is ``tests/test_iter241_behavior.py`` and the floor's owner is
  ``tests/test_roadmap_size_budget.py``; both already run against the live tree.
* Behavior 9 (the published ``N,N00+`` floor token does not move). Spelling that token in
  a tracked file makes the file a floor CARRIER, and six shipped censuses -- in
  ``test_iter238``, ``test_iter245``, ``test_iter250``, ``test_iter256``, ``test_iter257``
  and ``test_readme_and_ci_contract`` -- fail any carrier absent from their declared
  roster. The collected-item side of the same behavior is already asserted by
  ``tests/test_iter263_behavior.py::test_b6_the_gauge_reports_room_for_the_next_module``.

Both are therefore verified out of band and their measurements reported in ``tester.md``.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tests"
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: Behavior 1. The function whose keying made it a standing veto, and the section banner
#: that introduced it -- both must be gone, banner included, with no orphan left behind.
#: The banner is looked for as a COMMENT line and not as a substring, because this
#: module has to carry the needle itself and a substring scan self-hits (measured).
RETIRED_VETO = "test_ac_no_source_or_dependency_moved_in_this_commit"
ORPHAN_BANNER = "Acceptance criterion -- a tests-only iteration touches no product code."

#: Behavior 2. The census trigger, hoisted out of every function body (see docstring).
TRIGGER_STATUS = "status"
TRIGGER_PORCELAIN = "--porcelain"
TRIGGER_SRC = "src"

#: Behavior 2. A body that names any of these keys its sample to a specific commit
#: instead of to the live worktree, so it cannot veto a successor.
GATE_TOKENS = ("ITERATION_TAG", "_move_has_landed_in_head", "(foundry iter ")

#: Behavior 3/4. The four provenance-gated siblings that carry the acceptance criterion
#: after the deletion. Named as literals so a blanket deletion of the family reds this
#: module, and asserted to be MATCHED by the census so non-vacuity is concrete.
SURVIVING_SIBLINGS: tuple[tuple[str, str], ...] = (
    ("test_iter245_behavior.py", "test_b13_this_iteration_touches_nothing_under_src"),
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

#: Fail-open floor: the corpus is ~280 modules, so a census that reached a handful of
#: them would prove nothing by coming back clean.
MIN_CORPUS_MODULES = 200

#: Behavior 5. Rows that must have LEFT the live index, the row that must STAY, and the
#: floor ``tests/test_iter168_behavior.py`` puts under the index.
RETIRED_ROWS = (173, 205)
KEPT_ROW = 165
MIN_INDEX_ROWS = 20

#: Behavior 6/7. RUNNING TOTALS over the whole corpus, not this iteration's delta: both
#: counts move whenever ANY later iteration retires a row, so they must be re-keyed with
#: each such bump rather than frozen (the lesson
#: ``tests/test_iter258_behavior.py::test_ac1`` records). Factory iter 304 retired TWO
#: rows in one commit (#173, #205), so 81 -> 83 archive bullets and 72 -> 73 ledger rows;
#: factory iter 305 then retired ROADMAP row #169 (``addopts`` gains ``--dist worksteal``)
#: as SHIPPED and added ledger row #286, so 83 -> 84 and 73 -> 74. Factory iters 306, 307
#: and 308 then added ledger rows #287, #282 and #288 with NO index retirement between
#: them (307 retired row #282 from the index, which is why the bullet count moved once),
#: so the ledger ran 74 -> 75 -> 76 -> 77 while the bullets stopped at 85. Factory iter
#: 309 then added ledger row #289 (the nine-key roster single-sourced in the test corpus)
#: with no index retirement either, so 77 -> 78 and the bullets still stop at 85.
#: Factory iter 310 added ledger row #290 (`SPEC.md`'s `Makefile` bullet names every
#: declared recipe), again with no index retirement, so 78 -> 79 and the bullets hold.
#: Foundry iter 312 added ledger row #291 (41 duplicate version-freeze tests retire),
#: once more with no index retirement, so 79 -> 80 and the bullets still stop at 85.
#: Foundry iter 313 added ledger row #292 (the root `git` spawn is skipped where no
#: repo can exist), again with no index retirement, so 80 -> 81 and the bullets hold.
EXPECTED_ARCHIVE_BULLETS = 85
EXPECTED_LEDGER_ROWS = 81
LEDGER_NUMBER = "285"
SHIP_TAG = "foundry iter 304"
MAX_LEDGER_ROW_CHARS = 120

#: Behavior 6. Every pipe in a relocated index row must become one of these labels, so
#: the bullet can never be re-parsed as a table row.
FIELD_LABELS = ("LAYER:", "VALUE:", "RISK:", "SOURCE:", "STATUS:")
RETIREMENT_RATIONALE = "WHY IT WAS RETIRED RATHER THAN SHIPPED:"

#: Behavior 6. A relocated row carries a number-plus-five-field shape, so a verbatim
#: comparison that walked fewer cells than this would be checking almost nothing.
MIN_ROW_CELLS = 5

#: Behaviors 8 and 9 carry NO constant here, deliberately. Naming a ``ROADMAP.md``
#: char bound makes this module a size-bounding module, which
#: ``tests/test_iter172_behavior.py`` allows only for an enumerated allowlist and only at
#: the two sanctioned values (40000 / 10000); spelling the published floor makes it an
#: undeclared floor CARRIER, which six shipped censuses reject. Both are owned elsewhere
#: -- see the module docstring. Measured values live in the tester report.

INDEX_ROW = re.compile(r"^\|\s*(\d+)\s*\|")
LEDGER_ROW = re.compile(r"^- #(\d+) ")

_UNGATED_SAMPLE = '''
def test_regressed_shape() -> None:
    """A sampler keyed to the live worktree, with no provenance gate."""
    dirty = _git("status", "--porcelain", "--", "src", "uv.lock")
    assert dirty == ""
'''

_GATED_SAMPLE = '''
def test_gated_shape() -> None:
    """The same sampler, keyed to its own commit."""
    files = _git("show", "--name-only", _sha_of(ITERATION_TAG))
    dirty = _git("status", "--porcelain", "--", "src", "uv.lock")
    assert dirty == "" or files
'''


def _tracked_test_modules() -> dict[str, str]:
    """Every git-tracked ``tests/test_*.py``, keyed by file name.

    ``git ls-files`` and not a filesystem glob, because the domain this iteration cares
    about is the tree the commit SHIPS. This module was ``git add -N``-ed before any
    measurement, so it is inside its own domain (asserted below).
    """
    listing = subprocess.run(
        ["git", "ls-files", "tests"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    modules: dict[str, str] = {}
    for entry in listing:
        name = Path(entry).name
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        path = REPO / entry
        if path.exists():
            modules[name] = path.read_text(encoding="utf-8")
    return modules


def _code_body(source: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """One function's body as source text: no ``def`` line and no docstring.

    Docstrings are dropped because the census asks what a body INVOKES, and prose that
    merely describes the retired shape (this module's own header does) is not a sample.
    """
    statements = list(node.body)
    if statements:
        head = statements[0]
        if (
            isinstance(head, ast.Expr)
            and isinstance(head.value, ast.Constant)
            and isinstance(head.value.value, str)
        ):
            statements = statements[1:]
    if not statements:
        return ""
    lines = source.splitlines()
    first = statements[0].lineno
    last = max(stmt.end_lineno or stmt.lineno for stmt in statements)
    return "\n".join(lines[first - 1 : last])


def _call_literals(call: ast.Call) -> list[str]:
    """Every string constant reachable from one call's arguments."""
    return [
        node.value
        for node in ast.walk(call)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _census(sources: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """``(body_matches, ungated, same_call_matches)`` over a name -> source mapping.

    ``body_matches`` is the BODY-scoped reading of Behavior 2 (the three trigger literals
    anywhere in the body); ``same_call_matches`` is the literal same-call reading, kept so
    the report can name what each reading actually finds. ``ungated`` is the body-scoped
    match set minus every body that names a provenance gate.
    """
    body_matches: list[str] = []
    ungated: list[str] = []
    same_call: list[str] = []
    for name in sorted(sources):
        source = sources[name]
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            body = _code_body(source, node)
            if not body:
                continue
            triggered = (
                TRIGGER_STATUS in body
                and TRIGGER_PORCELAIN in body
                and TRIGGER_SRC in body
            )
            gated = any(gate in body for gate in GATE_TOKENS)
            if triggered:
                body_matches.append(f"{name}::{node.name}")
                if not gated:
                    ungated.append(f"{name}::{node.name}")
            for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                literals = _call_literals(call)
                if (
                    TRIGGER_STATUS in literals
                    and TRIGGER_PORCELAIN in literals
                    and any(
                        literal == TRIGGER_SRC
                        or literal.startswith(f"{TRIGGER_SRC}/")
                        for literal in literals
                    )
                ):
                    same_call.append(f"{name}::{node.name}")
                    break
    return body_matches, ungated, same_call


def _head_index_rows(numbers: tuple[int, ...]) -> dict[int, str]:
    """The index rows for ``numbers`` exactly as they stand in ``HEAD:ROADMAP.md``.

    PROVENANCE GATE, and the reason this is keyed to HEAD rather than to the worktree.
    Before this iteration's commit lands, HEAD still carries the rows being relocated, so
    their text is available to compare cell-by-cell against the archive bullets that claim
    to preserve it verbatim. Once the commit has landed -- the state every fresh-clone
    re-verification sees -- HEAD no longer carries them, the mapping comes back empty and
    the comparison retires itself instead of turning into a standing veto. That is the
    shipped ``_move_has_landed_in_head`` shape from ``tests/test_iter255_behavior.py``,
    reused deliberately: this module must not add a second worktree-keyed guard while its
    whole subject is retiring the first one.
    """
    blob = subprocess.run(
        ["git", "show", "HEAD:ROADMAP.md"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found: dict[int, str] = {}
    for line in blob.splitlines():
        match = INDEX_ROW.match(line)
        if match and int(match.group(1)) in numbers:
            found[int(match.group(1))] = line
    return found


def _row_cells(row: str) -> list[str]:
    """One index row's cells with the leading row number dropped, each stripped.

    The pipes are the row's field separators, so the cells ARE the units the archive
    bullet promises to carry over with each pipe replaced by a field label.
    """
    return [cell.strip() for cell in row.strip().strip("|").split("|")][1:]


def _index_rows(text: str) -> list[int]:
    return [
        int(match.group(1))
        for match in (INDEX_ROW.match(line) for line in text.splitlines())
        if match
    ]


def _ledger_rows(text: str) -> list[str]:
    return [line for line in text.splitlines() if LEDGER_ROW.match(line)]


def _archive_bullets(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- **#")]


def test_the_worktree_keyed_src_veto_retires_and_the_ratchet_holds() -> None:
    """Expected Behaviors 1-9 of factory iteration 304, in spec order.

    Graded as one collected item because ``tests/test_iter263_behavior.py``'s
    ``MIN_BINDING_HEADROOM = 6`` leaves room for exactly one (measured
    ``binding_headroom=7`` before this file existed). Each section carries its own
    failure message, so a red still names the behavior that broke.
    """
    sources = _tracked_test_modules()
    assert len(sources) >= MIN_CORPUS_MODULES, (
        f"fail-open floor: the census reached only {len(sources)} tracked test modules, "
        "so a clean verdict would prove nothing"
    )
    assert Path(__file__).name in sources, (
        "this module must be inside its own git-tracked domain before it measures the "
        "corpus (`git add -N` it first); otherwise the census is blind to itself"
    )

    # Behavior 1 -- the veto is gone, banner included, and its module survives.
    still_defining = sorted(
        name for name, text in sources.items() if f"def {RETIRED_VETO}(" in text
    )
    assert still_defining == [], (
        f"Behavior 1: `{RETIRED_VETO}` is keyed to the LIVE worktree with no provenance "
        "gate, so it vetoes every successor that edits product code and must not be "
        f"defined anywhere in the tracked corpus; still defined in {still_defining}"
    )
    orphan_banners = sorted(
        name
        for name, text in sources.items()
        if any(
            line.lstrip().startswith("#") and ORPHAN_BANNER in line
            for line in text.splitlines()
        )
    )
    assert orphan_banners == [], (
        "Behavior 1: the deleted guard's section banner must go with it rather than "
        f"survive as an orphan introducing nothing; found in {orphan_banners}"
    )
    host = "test_iter263_behavior.py"
    assert host in sources, (
        f"Behavior 1: {host} must survive the deletion -- only the one function and its "
        "banner were in scope, not the module"
    )
    host_tests = [
        node.name
        for node in ast.parse(sources[host]).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    ]
    assert len(host_tests) >= 5, (
        f"Behavior 1: {host} must still collect after the deletion, but it defines only "
        f"{len(host_tests)} test functions: {host_tests}"
    )

    # Behaviors 2-4 -- the shape is ratcheted shut, non-vacuously, and the criterion
    # still ships four times.
    body_matches, ungated, same_call = _census(sources)
    assert ungated == [], (
        "Behavior 2: a test body that samples `git status` with the porcelain flag over "
        f"`src` must key the sample to its own commit -- naming one of {GATE_TOKENS} -- "
        "or it becomes a standing veto over every successor that edits product code, "
        f"which is the defect this iteration retires: {ungated}"
    )
    assert len(body_matches) >= 4, (
        "Behavior 3: the census must not be able to pass by matching nothing, or a "
        "future iteration could re-add the veto silently; the body-scoped predicate "
        f"found only {body_matches}"
    )
    assert set(same_call) <= set(body_matches), (
        "the strict same-call reading of Behavior 2 must be a SUBSET of the body-scoped "
        f"reading, so `ungated == []` holds under both: {sorted(set(same_call) - set(body_matches))}"
    )
    for module, function in SURVIVING_SIBLINGS:
        assert module in sources, (
            f"Behavior 4: {module} carries one of the four provenance-gated copies of "
            "the acceptance criterion and must not leave the corpus"
        )
        assert f"def {function}(" in sources[module], (
            f"Behavior 4: {module}::{function} is one of the four gated guards that "
            "carry the criterion after the deletion, so the criterion is asserted four "
            "times and not zero; it must survive"
        )
        assert f"{module}::{function}" in body_matches, (
            f"Behavior 3: {module}::{function} is expected to MATCH the census, so the "
            f"non-vacuity floor is concrete rather than incidental; matches: {body_matches}"
        )

    # The instrument is two-sided on synthetic text, so it cannot go quietly blind.
    _, synthetic_ungated, _ = _census({"synthetic_ungated.py": _UNGATED_SAMPLE})
    assert synthetic_ungated == ["synthetic_ungated.py::test_regressed_shape"], (
        "the census must still RECOGNIZE the retired shape on synthetic source text; a "
        f"census that stopped matching would report a clean zero forever: {synthetic_ungated}"
    )
    gated_matches, gated_ungated, _ = _census({"synthetic_gated.py": _GATED_SAMPLE})
    assert gated_matches == ["synthetic_gated.py::test_gated_shape"], (
        f"the gated sample must still MATCH the census predicate: {gated_matches}"
    )
    assert gated_ungated == [], (
        f"a body naming a provenance gate must NOT be reported ungated: {gated_ungated}"
    )

    # Behavior 5 -- rows #173 and #205 leave the live index, #165 stays, floor holds.
    roadmap = ROADMAP.read_text(encoding="utf-8")
    index = _index_rows(roadmap)
    for row in RETIRED_ROWS:
        assert row not in index, (
            f"Behavior 5: row #{row} is self-declared dead and must leave the live "
            f"index to buy ratchet room; the index still lists {sorted(index)}"
        )
    assert KEPT_ROW in index, (
        f"Behavior 5: row #{KEPT_ROW} records a LIVE residual and is explicitly out of "
        f"scope, so it must stay in the index; index is {sorted(index)}"
    )
    assert len(index) >= MIN_INDEX_ROWS, (
        f"Behavior 5: the live index must keep at least {MIN_INDEX_ROWS} rows "
        f"(tests/test_iter168_behavior.py), but only {len(index)} survive"
    )

    # Behavior 6 -- both retirements are preserved verbatim, unparseable as table rows.
    archive = ARCHIVE.read_text(encoding="utf-8")
    bullets = _archive_bullets(archive)
    assert len(bullets) == EXPECTED_ARCHIVE_BULLETS, (
        f"Behavior 6: the archive must hold {EXPECTED_ARCHIVE_BULLETS} retirement "
        "bullets (81 -> 83 for rows #173/#205 in factory iter 304, +1 for row #169 in "
        f"factory iter 305) with existing bullets untouched; it holds {len(bullets)}. "
        "If you just retired a row, bump this literal by one per row and say which in "
        "the comment above it; if you did not, a bullet was lost or duplicated"
    )
    pre_land = _head_index_rows(RETIRED_ROWS)
    for row in RETIRED_ROWS:
        preserved = [line for line in bullets if line.startswith(f"- **#{row} -- ")]
        assert len(preserved) == 1, (
            f"Behavior 6: row #{row} must be preserved by exactly one `- **#{row} -- ` "
            f"archive bullet, found {len(preserved)}"
        )
        bullet = preserved[0]
        assert "|" not in bullet, (
            f"Behavior 6: every pipe in the relocated row #{row} must become a field "
            "label so the bullet can never be re-parsed as an index table row"
        )
        for label in FIELD_LABELS:
            assert label in bullet, (
                f"Behavior 6: the archive bullet for row #{row} must carry the "
                f"{label} field the retired index row's pipes stood for"
            )
        assert RETIREMENT_RATIONALE in bullet, (
            f"Behavior 6: the archive bullet for row #{row} must state why it was "
            f"retired rather than shipped, naming `{RETIREMENT_RATIONALE}`"
        )
        if row not in pre_land:
            continue
        cells = _row_cells(pre_land[row])
        assert len(cells) >= MIN_ROW_CELLS, (
            f"Behavior 6: row #{row} as it stands at HEAD parses into only {len(cells)} "
            "fields, so a verbatim comparison against it would prove almost nothing: "
            f"{pre_land[row]!r}"
        )
        dropped = [cell for cell in cells if cell and cell not in bullet]
        assert dropped == [], (
            f"Behavior 6: the archive bullet for row #{row} must carry the retired index "
            "row's text VERBATIM -- relocation, not paraphrase -- but these fields of the "
            f"row at HEAD are absent from the bullet: {dropped}"
        )

    # Behavior 7 -- the iteration records itself exactly once.
    ledger = _ledger_rows(roadmap)
    assert len(ledger) == EXPECTED_LEDGER_ROWS, (
        f"Behavior 7: the Done ledger must hold {EXPECTED_LEDGER_ROWS} rows (73 -> 74 in "
        "factory iter 305, then +1 each for row #287 in factory iter 306, row #282 in 307, "
        "row #288 in 308, row #289 in 309, row #290 in 310 and row #291 in 312); it "
        "holds "
        f"{len(ledger)}. One new row per iteration: re-key this literal, never freeze it"
    )
    mine = [line for line in ledger if line.startswith(f"- #{LEDGER_NUMBER} ")]
    assert len(mine) == 1, (
        f"Behavior 7: exactly one Done-ledger row must be numbered #{LEDGER_NUMBER}, "
        f"the next free number; found {mine}"
    )
    assert len(mine[0]) <= MAX_LEDGER_ROW_CHARS, (
        f"Behavior 7: the ledger row must be at most {MAX_LEDGER_ROW_CHARS} chars, but "
        f"it is {len(mine[0])}: {mine[0]!r}"
    )
    assert SHIP_TAG in mine[0], (
        f"Behavior 7: the ledger row must cite `{SHIP_TAG}` so the record is traceable "
        f"to its commit: {mine[0]!r}"
    )
    numbers = [int(LEDGER_ROW.match(line).group(1)) for line in ledger]  # type: ignore[union-attr]
    assert numbers.count(int(LEDGER_NUMBER)) == 1, (
        f"Behavior 7: #{LEDGER_NUMBER} must appear once, not twice: {numbers[-6:]}"
    )

    # Behaviors 8 and 9 are asserted by their OWNER oracles, not restated here; adding
    # either shape to this module reds four shipped censuses. See the docstring.
