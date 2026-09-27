"""Black-box oracle for foundry iteration 324 (state-dir iteration 472, ROADMAP #303):
``SPEC.md`` 4.1's ``syntax_error`` bullet states the PEP 552 pyc skip the collector ships --
written by the tester from the spec alone (pm.md ``## Expected Behaviors``), the repo's own
``tests/`` tree, ``SPEC.md``, ``README.md``, ``ROADMAP.md`` / ``ROADMAP_ARCHIVE.md`` and by
IMPORTING the public collector module.

WHY THIS MODULE EXISTS. Commit 3f1455d (ROADMAP #299) taught ``SyntaxErrorCollector`` to
skip, unread, any ``.py`` whose ``__pycache__`` pyc carries a matching PEP 552 TIMESTAMP
header, but it never touched ``SPEC.md``: one iteration later the vision document still
promised a parse of "every ``*.py`` file" and claimed the size skip was "what keeps 'every
``*.py`` file' literally true". This module pins the corrected prose TWO-SIDED to the live
symbol ``proactive_loop.collectors.syntax_error._pyc_says_ok`` and to the module's stdlib
imports, so dropping the trust later reds the SPEC instead of silently re-opening the gap,
while dropping BOTH sides together still passes (an equality, not a one-way implication).

WHAT THIS MODULE GRADES (THREE collected items -- the gauge read ``binding_headroom=6 ==
MIN_BINDING_HEADROOM`` at the parent commit, so the module is funded 1:1 by three retired
assert-message-only duplicates of ``assert len(all_collectors()) == 17``, see
``RETIRED_TESTS``; extra assertions live INSIDE these three bodies, never as a fourth item
or a parametrization):
(1) behaviors 1+2: the ``syntax_error`` bullet is non-empty, no longer says ``literally
true`` (nor does any line of SPEC.md), names ``PEP 552`` / ``__pycache__`` /
``importlib.util.cache_from_source`` / ``_pyc_says_ok`` / ``it cannot already vouch for``,
still says ``every `*.py` file under `root``` exactly once, and the pyc prose is present IFF
``_pyc_says_ok`` is a callable attribute of the collector module (non-vacuity: the bullet
starts with the collector's own ``- `syntax_error.py:`` line and exceeds 500 chars);
(2) behavior 3: `````struct````` and `````importlib.util````` appear in the bullet IFF the
module source says ``import struct`` / ``import importlib.util`` (equalities), and ``Pure
stdlib`` occurs in the bullet exactly once;
(3) behaviors 4-7: ``SPEC.md`` stays under ``test_iter281::SPEC_CEILING_BYTES`` (imported,
never respelled); the README collector row is untouched; ROADMAP.md holds exactly one
verbatim 120-char ``- #303`` Done-ledger row tagged ``(foundry iter 324)``, the index keeps
its 20 rows and ROADMAP_ARCHIVE.md never mentions #303; the three named duplicates are gone,
their canonical copy survives, and this module holds exactly three collected items.

ISOLATION CONTRACT (honored). Every assertion was written from pm.md's Expected Behaviors,
the ``tests/`` tree, SPEC.md / README.md / the two roadmap files, and by importing the public
module. No file under ``src/`` was read by the tester (behavior 3 reads the module's source
AT TEST TIME through ``MOD.__file__`` because the spec binds prose to imports); no
engineer/reviewer notes, no ``git diff``.

Offline and deterministic: no subprocess, no network, no tmp files. Nothing here asserts on
docstring LAYOUT (3.13 strips the common indent, 3.12 does not) -- only on substrings.
"""

from __future__ import annotations

import ast
from pathlib import Path

from proactive_loop.collectors import syntax_error as MOD
from tests.test_iter172_behavior import roadmap_size_bounds
from tests.test_iter281_behavior import SPEC_CEILING_BYTES

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "SPEC.md"
README = REPO / "README.md"
ROADMAP = REPO / "ROADMAP.md"
ARCHIVE = REPO / "ROADMAP_ARCHIVE.md"

#: The bullet under test: from this line up to (not including) the next ``- ``` line.
BULLET_START = "- `syntax_error.py: SyntaxErrorCollector("
NEXT_BULLET = "- `"
MIN_BULLET_CHARS = 500
PYC_NEEDLES = (
    "PEP 552",
    "__pycache__",
    "importlib.util.cache_from_source",
    "_pyc_says_ok",
    "it cannot already vouch for",
)
EVERY_FILE_PHRASE = "every `*.py` file under `root`"
RETRACTED_CLAIM = "literally true"

#: Behavior 6 records.
LEDGER_ROW_NUMBER = 303
ITER_TAG = "(foundry iter 324)"
LEDGER_ROW = (
    "- #303 SPEC 4.1 syntax_error bullet states the PEP 552 pyc skip, bound to "
    "_pyc_says_ok; 3 dups retire (foundry iter 324)"
)
LEDGER_ROW_MAX_CHARS = 120  # tests/test_iter241_behavior.py cap
INDEX_ROWS = 20  # #303 never had an index row (mirrors #301 in 6051524)
README_COLLECTOR_ROW = (
    "| `syntax_error` | `syntax_error` | Python files that fail to parse "
    "(stdlib compile, parse-only). |"
)
COLLECTED_ITEMS = 3

#: Behavior 7 funding: the assert-message-only duplicates pm.md named, in order -- every
#: body is ``assert len(all_collectors()) == 17`` differing only in its message.
RETIRED_TESTS: tuple[tuple[str, str], ...] = (
    ("test_iter81_behavior.py", "test_b8_collector_registry_count_unchanged"),
    ("test_iter82_behavior.py", "test_b6_collector_registry_count_unchanged"),
    ("test_iter83_behavior.py", "test_b8_collector_registry_count_unchanged"),
)
#: The canonical copy that must SURVIVE (already a ``test_iter283::KEEPERS`` entry).
KEEPERS: tuple[tuple[str, str], ...] = (
    ("test_iter75_behavior.py", "test_b12_collector_count_fifteen"),
)


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _bullet(spec_text: str) -> str:
    """BULLET per pm.md: the ``syntax_error.py`` line through the line before the next ``- ```."""
    lines = spec_text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith(BULLET_START)]
    assert len(starts) == 1, f"precondition: exactly one {BULLET_START!r} line; got {starts}"
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(NEXT_BULLET)),
        len(lines),
    )
    return "".join(lines[start:end])


# ===========================================================================
# Behaviors 1 + 2 -- the contradiction is gone and the pyc prose is two-sided.
# ===========================================================================


def _b1_contradiction_gone_and_skip_stated(spec_text: str, bullet: str) -> None:
    assert bullet, "behavior 1: BULLET is non-empty"
    assert RETRACTED_CLAIM not in bullet, (
        f"behavior 1: {RETRACTED_CLAIM!r} must not occur in the syntax_error bullet"
    )
    assert RETRACTED_CLAIM not in spec_text, (
        f"behavior 1: {RETRACTED_CLAIM!r} must not occur anywhere in SPEC.md"
    )
    for needle in PYC_NEEDLES:
        assert needle in bullet, f"behavior 1: BULLET must state {needle!r}"
    assert bullet.count(EVERY_FILE_PHRASE) == 1, (
        f"behavior 1: {EVERY_FILE_PHRASE!r} occurs exactly once (the walk is still total; "
        f"only the parse is conditional); got {bullet.count(EVERY_FILE_PHRASE)}"
    )


def _b2_two_sided_pyc_binding(bullet: str) -> None:
    assert bullet.startswith("- `syntax_error.py:"), (
        "behavior 2 (non-vacuity): BULLET starts with the collector's own line"
    )
    assert len(bullet) > MIN_BULLET_CHARS, (
        f"behavior 2 (non-vacuity): BULLET > {MIN_BULLET_CHARS} chars; got {len(bullet)}"
    )
    prose_says_pyc = "PEP 552" in bullet and "__pycache__" in bullet
    code_has_trust = callable(getattr(MOD, "_pyc_says_ok", None))
    assert prose_says_pyc == code_has_trust, (
        "behavior 2: the SPEC's pyc prose and the collector's `_pyc_says_ok` must move "
        f"together; prose={prose_says_pyc} code={code_has_trust}"
    )


def test_b1_b2_spec_bullet_states_the_pyc_skip_and_is_bound_to_pyc_says_ok() -> None:
    spec_text = _spec_text()
    bullet = _bullet(spec_text)
    _b1_contradiction_gone_and_skip_stated(spec_text, bullet)
    _b2_two_sided_pyc_binding(bullet)


# ===========================================================================
# Behavior 3 -- the stdlib import list is bound to the module's real imports.
# ===========================================================================


def _b3_two_sided_stdlib_binding(bullet: str) -> None:
    module_file = getattr(MOD, "__file__", None)
    assert module_file, "precondition: the collector module has a source file"
    src = Path(module_file).read_text(encoding="utf-8")
    assert ("`struct`" in bullet) == ("import struct" in src), (
        "behavior 3: `struct` is listed in the bullet IFF the module imports struct; "
        f"bullet={'`struct`' in bullet} src={'import struct' in src}"
    )
    assert ("`importlib.util`" in bullet) == ("import importlib.util" in src), (
        "behavior 3: `importlib.util` is listed in the bullet IFF the module imports it; "
        f"bullet={'`importlib.util`' in bullet} src={'import importlib.util' in src}"
    )
    assert bullet.count("Pure stdlib") == 1, (
        f"behavior 3: 'Pure stdlib' occurs exactly once in BULLET; got {bullet.count('Pure stdlib')}"
    )


def test_b3_stdlib_import_list_matches_the_module_imports() -> None:
    _b3_two_sided_stdlib_binding(_bullet(_spec_text()))


# ===========================================================================
# Behaviors 4-7 -- size pins, untouched surfaces, records and funding (one item).
# ===========================================================================


def _index_rows(text: str) -> list[str]:
    rows = []
    for line in text.splitlines():
        parts = line.split("|")
        if len(parts) > 2 and line.startswith("|") and parts[1].strip().isdigit():
            rows.append(line)
    return rows


def _b4_spec_size_pin_holds() -> None:
    spec_bytes = SPEC.read_bytes()
    assert len(spec_bytes) <= SPEC_CEILING_BYTES, (
        f"behavior 4: SPEC.md is {len(spec_bytes)} B, over the imported "
        f"test_iter281::SPEC_CEILING_BYTES = {SPEC_CEILING_BYTES} pin"
    )
    # ROADMAP.md's `< 35_428` bound is owned by test_iter241::test_b09c and is deliberately
    # NOT respelled here (test_iter172's census forbids a second bound on that document).


def _b5_readme_collector_row_untouched() -> None:
    readme_lines = README.read_text(encoding="utf-8").splitlines()
    assert readme_lines.count(README_COLLECTOR_ROW) == 1, (
        "behavior 5: the README syntax_error collector row is unchanged and unique"
    )


def _b6_roadmap_records() -> None:
    text = ROADMAP.read_text(encoding="utf-8")
    non_empty = [line for line in text.splitlines() if line.strip()]
    assert non_empty, "precondition: ROADMAP.md is non-empty"
    # Membership, not position: the row was appended LAST in foundry iter 324, but every
    # later ship appends its own row below it (foundry iter 325's #304 was the first).
    assert LEDGER_ROW in non_empty, (
        f"behavior 6: ROADMAP.md holds the verbatim #303 ledger row; tail is {non_empty[-1]!r}"
    )
    assert len(LEDGER_ROW) == LEDGER_ROW_MAX_CHARS, (
        f"behavior 6: the pinned row is {LEDGER_ROW_MAX_CHARS} chars; got {len(LEDGER_ROW)}"
    )
    ledger = [line for line in text.splitlines() if line.startswith(f"- #{LEDGER_ROW_NUMBER} ")]
    assert len(ledger) == 1, (
        f"behavior 6: exactly one Done-ledger row for #{LEDGER_ROW_NUMBER}; got {ledger!r}"
    )
    assert text.count(ITER_TAG) == 1, (
        f"behavior 6: {ITER_TAG} appears exactly once in ROADMAP.md (one row per iteration)"
    )
    rows = _index_rows(text)
    numbers = [int(r.split("|")[1].strip()) for r in rows]
    assert len(rows) == INDEX_ROWS, (
        f"behavior 6: no index row is retired -- the index keeps {INDEX_ROWS} rows; got {len(rows)}"
    )
    assert LEDGER_ROW_NUMBER not in numbers, "behavior 6: #303 never had an index row"

    archive = ARCHIVE.read_text(encoding="utf-8")
    assert f"#{LEDGER_ROW_NUMBER}" not in archive, (
        "behavior 6: ROADMAP_ARCHIVE.md is untouched (no #303 bullet or row)"
    )


def _b7_funding() -> None:
    tests_dir = REPO / "tests"
    for module, name in RETIRED_TESTS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" not in source, (
            f"behavior 7: {module}::{name} was retired to fund this module; it is back"
        )
    for module, name in KEEPERS:
        source = (tests_dir / module).read_text(encoding="utf-8")
        assert f"def {name}(" in source, (
            f"behavior 7: canonical copy {module}::{name} must survive"
        )

    own_source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(own_source)
    collected = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert len(collected) == COLLECTED_ITEMS, (
        f"behavior 7: this module holds exactly {COLLECTED_ITEMS} collected items; "
        f"got {collected}"
    )
    marker = "param" + "etrize"
    assert marker not in own_source.replace('"param" + "etrize"', ""), (
        "behavior 7: no parametrization multiplies the collected count"
    )
    assert roadmap_size_bounds(own_source) == (), (
        "this module must not bound ROADMAP.md by size (test_iter172 census); "
        f"found {roadmap_size_bounds(own_source)}"
    )


def test_b4_b5_b6_b7_size_pins_untouched_surfaces_records_and_funding() -> None:
    _b4_spec_size_pin_holds()
    _b5_readme_collector_row_untouched()
    _b6_roadmap_records()
    _b7_funding()
