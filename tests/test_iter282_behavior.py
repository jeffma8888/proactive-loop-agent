"""Black-box oracle for foundry iteration 322 (state-dir iteration 470, ROADMAP #301): the
"find the installed ``pla`` console script" test helper is DEFINED ONCE, in
``tests/test_iter158_behavior.py``, and every process-level module that used to hand-copy the
body now IMPORTS that one object -- written by the tester from the spec alone (pm.md
``## Expected Behaviors``), the repo's own ``tests/`` tree and ``ROADMAP.md``.

WHY THIS MODULE EXISTS. At the parent commit the corpus carried 27 module-level
``def _console_script()`` bodies that all resolve the same way (the interpreter's ``bin/pla``,
then ``bin/pla.exe``, then ``shutil.which``); 20 were byte-identical once the docstring was
dropped and the rest differed only in docstring or assert message. The shipped duplicate census
(``tests/test_iter263_behavior.py``) fingerprints COLLECTED tests only, so a helper class is
invisible to it: nothing stopped copy 28. ROADMAP #289 (foundry iter 309) already made
test_iter158 the import hub for ``DISPATCHED_RUN_KEYS`` under exactly this contract shape and
``tests/test_iter268_behavior.py`` ratchets THAT roster; this module ratchets the helper the
same way, and deliberately owns nothing else.

WHAT THIS MODULE GRADES (three collected items -- the gauge read ``binding_headroom=6 ==
MIN_BINDING_HEADROOM`` at the parent commit, so the module is funded 1:1 by three retired
assert-message-only duplicates -- two ``len(ToolRegistry.tool_names()) == 14`` copies and one
collector-count copy, see ``RETIRED_TESTS``; extra assertions live
INSIDE these three bodies, never as a fourth item or a ``parametrize``):
(1) exactly ONE module-level ``FunctionDef`` named ``_console_script`` exists across every
tracked test module (``git ls-files tests`` with this file unioned in), and it lives in
test_iter158 -- at the parent commit the same walk found 27;
(2) each of the 26 dependents carries an ``ImportFrom tests.test_iter158_behavior`` naming the
helper, all 27 modules share ONE object after import, and no tracked module other than the
owner defines a function whose docstring-stripped body equals the canonical one under a
different name (the renamed-copy ratchet);
(3) the one definition still WORKS -- it returns an existing file named ``pla``/``pla.exe`` and
``pla --version`` run from that path exits 0 naming ``pla`` -- keeps the canonical shape
(``sys.executable`` parent, both candidate names, ``shutil.which``, an assert, a return), and
carries the test_iter268 contract-comment cues (``single definition``, ``do not``, ``localize``)
within six lines above the ``def``;
(4) the funding is real and the keepers survive: test_iter79 no longer defines its
``== 14`` tool-count twin nor its ``== 17`` collector-count twin and test_iter92 no longer
defines its ``== 14`` twin (three collected items retired, zero net delta); test_iter75 still
defines ``test_b12_tool_count_fourteen`` (the earliest ``== 14`` copy) and test_iter81 still
defines ``test_b8_tool_registry_count_unchanged`` -- pm.md listed that one for deletion, but
``tests/test_iter263_behavior.py::FAMILIES`` already pins it as the family KEEPER, so deleting
it would red a shipped oracle and the tree rightly kept it; each donor still collects at least
``MIN_SURVIVING_COLLECTED`` tests and still uses ``ToolRegistry`` outside its import line, and
this module holds exactly three collected items with no ``parametrize``;
(5) the Done ledger records the ship in exactly one ``#301`` row tagged ``(foundry iter 322)``
that names the helper, the ledger count matches test_iter264's pin (which this ship bumps to
90), the index keeps its 20 rows, and the archive gains no ``#301`` bullet;
(6) this module holds NO size opinion on ROADMAP.md (``roadmap_size_bounds`` of its own source
is empty), so the test_iter172 census grades it identically in the worktree and in preship's
fresh clone.

ISOLATION CONTRACT (honored). Every assertion was written from pm.md's Expected Behaviors, the
``tests/`` tree, ``ROADMAP.md`` / ``ROADMAP_ARCHIVE.md`` and by RUNNING the installed ``pla``
script. No file under ``src/`` was read, no engineer/reviewer notes, no ``git diff``.

Offline and deterministic: the only subprocesses are ``git ls-files`` (via the test_iter172
helper, with this module unioned in unconditionally so the domain can never drop the
measurer) and ``pla --version``. Nothing here asserts on docstring layout (3.13 strips the
common indent, 3.12 does not), and the helper body is compared as ``ast.unparse`` text.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from typing import Final

from proactive_loop.cli import main as _pla_main  # noqa: F401  -- proves the package imports

from tests.test_iter158_behavior import _console_script
from tests.test_iter172_behavior import roadmap_size_bounds, tracked_test_modules
from tests.test_iter264_behavior import EXPECTED_LEDGER_ROWS
from tests.test_iter270_behavior import MIN_SURVIVING_COLLECTED

REPO: Final[Path] = Path(__file__).resolve().parents[1]
TESTS_DIR: Final[Path] = REPO / "tests"
ROADMAP: Final[Path] = REPO / "ROADMAP.md"
ROADMAP_ARCHIVE: Final[Path] = REPO / "ROADMAP_ARCHIVE.md"
SELF: Final[Path] = Path(__file__).resolve()
SELF_REL: Final[str] = SELF.relative_to(REPO).as_posix()

# --------------------------------------------------------------------------
# The spec's own vocabulary (pm.md), encoded here rather than imported, to keep
# these tests black-box against the contract.
# --------------------------------------------------------------------------
HELPER: Final[str] = "_console_script"
OWNER_REL: Final[str] = "tests/test_iter158_behavior.py"
OWNER_MODULE: Final[str] = "tests.test_iter158_behavior"
DEPENDENT_ITERS: Final[tuple[int, ...]] = (
    128, 130, 132, 138, 139, 147, 155, 157, 163, 169, 173, 174, 177, 179, 180,
    202, 203, 205, 212, 232, 236, 241, 253, 267, 274, 281,
)
DEPENDENT_MODULES: Final[tuple[str, ...]] = tuple(
    f"tests.test_iter{n}_behavior" for n in DEPENDENT_ITERS
)
#: How many copies the parent commit carried (the number behavior 1 retires to one).
COPIES_AT_PARENT: Final[int] = 27

#: Cues the owner's contract comment must carry (behavior 3; test_iter268 vocabulary).
SINGLE_DEFINITION_CUE: Final[str] = "single definition"
DO_NOT_CUE: Final[str] = "do not"
LOCALIZE_CUE: Final[str] = "localize"
COMMENT_LOOKBACK_LINES: Final[int] = 6

#: The three duplicates that fund this module (behavior 4). pm.md named
#: ``test_iter81::test_b8_tool_registry_count_unchanged`` as the third, but
#: ``tests/test_iter263_behavior.py`` (``FAMILIES``) already pins THAT test as the KEEPER of
#: its family -- deleting it reds a shipped oracle -- so the third funder is the byte-identical
#: collector-count duplicate in test_iter79 instead (twins: test_iter84/86/88), and the
#: spec's third name is asserted to SURVIVE below. Noted for the PM in tester.md.
RETIRED_TESTS: Final[tuple[tuple[str, str], ...]] = (
    ("tests/test_iter79_behavior.py", "test_b03_live_tool_count_is_fourteen"),
    ("tests/test_iter79_behavior.py", "test_b05_live_collector_count_is_fifteen"),
    ("tests/test_iter92_behavior.py", "test_b7_tool_count_unchanged"),
)
#: The copies that must SURVIVE: the earliest ``== 14`` copy the spec keeps, and the
#: test_iter263 family keeper the spec mistakenly listed for deletion.
SURVIVING_TESTS: Final[tuple[tuple[str, str], ...]] = (
    ("tests/test_iter75_behavior.py", "test_b12_tool_count_fourteen"),
    ("tests/test_iter81_behavior.py", "test_b8_tool_registry_count_unchanged"),
)
DONOR_SYMBOL: Final[str] = "ToolRegistry"
OWN_COLLECTED_ITEMS: Final[int] = 3

#: Ledger row this iteration owes ``ROADMAP.md``, and the commit tag it must cite (behavior 5).
LEDGER_ROW: Final[str] = "- #301 "
LEDGER_TAG: Final[str] = "(foundry iter 322)"
ARCHIVE_BULLET: Final[str] = "- **#301 "
LEDGER_FLOOR: Final[int] = 90
INDEX_ROWS: Final[int] = 20

_LEDGER_RE: Final[re.Pattern[str]] = re.compile(r"^- #\d+ ")
_INDEX_RE: Final[re.Pattern[str]] = re.compile(r"^\| \d+ \|")


# --------------------------------------------------------------------------
# Helpers -- pure functions of source text.
# --------------------------------------------------------------------------
def _domain() -> dict[str, str]:
    """``relpath -> source`` for every tracked test module, this one unioned in."""
    rels = set(tracked_test_modules()) | {SELF_REL}
    return {rel: (REPO / rel).read_text(encoding="utf-8") for rel in sorted(rels)}


def _module_functions(source: str) -> list[ast.FunctionDef]:
    return [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)]


def _body_text(fn: ast.FunctionDef) -> str:
    """``ast.unparse`` of the body with a leading docstring dropped."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:]
    return "\n".join(ast.unparse(stmt) for stmt in body)


def _imports_helper_from_owner(source: str) -> bool:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == OWNER_MODULE:
            if any(alias.name == HELPER for alias in node.names):
                return True
    return False


def _owner_imports_of_owner(source: str) -> int:
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module == OWNER_MODULE
    )


def _names(source: str) -> set[str]:
    return {fn.name for fn in _module_functions(source)}


def _collected_defs(source: str) -> int:
    """Module-level ``test_*`` defs -- a floor on what pytest collects (no parametrize here)."""
    return sum(1 for fn in _module_functions(source) if fn.name.startswith("test_"))


def _uses_symbol_outside_imports(source: str, symbol: str) -> bool:
    return any(
        symbol in line
        for line in source.splitlines()
        if not line.lstrip().startswith(("from ", "import "))
    )


# --------------------------------------------------------------------------
# Behaviors 1 + 2 -- one definition, 26 importers, one shared object, no renamed copy.
# --------------------------------------------------------------------------
def test_b1_b2_one_definition_in_test_iter158_imported_by_every_dependent() -> None:
    domain = _domain()
    assert SELF_REL in domain and OWNER_REL in domain, sorted(domain)[:3]

    # Behavior 1 -- exactly one module-level def, and it is the owner's.
    definers = sorted(rel for rel, src in domain.items() if HELPER in _names(src))
    assert definers == [OWNER_REL], (
        f"behavior 1: `def {HELPER}` must be defined exactly once, in {OWNER_REL}; "
        f"found {len(definers)} definition(s) (parent commit had {COPIES_AT_PARENT}): {definers}"
    )
    owner_fns = [fn for fn in _module_functions(domain[OWNER_REL]) if fn.name == HELPER]
    assert len(owner_fns) == 1, "behavior 1: the owner defines the helper exactly once"
    canonical_body = _body_text(owner_fns[0])

    # Behavior 2a -- each dependent imports the helper from the owner, on ONE import line.
    for module in DEPENDENT_MODULES:
        rel = module.replace(".", "/") + ".py"
        assert rel in domain, f"behavior 2: dependent {rel} is not a tracked module"
        assert _imports_helper_from_owner(domain[rel]), (
            f"behavior 2: {rel} must `from {OWNER_MODULE} import {HELPER}`"
        )
        assert _owner_imports_of_owner(domain[rel]) == 1, (
            f"behavior 2: {rel} must import from {OWNER_MODULE} on exactly ONE line "
            "(existing DISPATCHED_RUN_KEYS lines are extended, not duplicated)"
        )
    assert len(DEPENDENT_MODULES) == COPIES_AT_PARENT - 1

    # Behavior 2b -- one shared object across all 27 modules.
    owner = importlib.import_module(OWNER_MODULE)
    objects = {id(importlib.import_module(m)._console_script) for m in DEPENDENT_MODULES}
    objects.add(id(owner._console_script))
    assert objects == {id(_console_script)}, (
        f"behavior 2: all 27 modules must share ONE helper object; saw {len(objects)}"
    )

    # Behavior 2c -- renamed-copy ratchet over the WHOLE domain (26 dependents included).
    renamed = [
        f"{rel}::{fn.name}"
        for rel, src in domain.items()
        if rel != OWNER_REL
        for fn in _module_functions(src)
        if _body_text(fn) == canonical_body
    ]
    assert renamed == [], (
        f"behavior 2: a copy of the canonical body survives under another name: {renamed}"
    )


# --------------------------------------------------------------------------
# Behavior 3 -- the one definition works, keeps its shape, and carries the contract comment.
# --------------------------------------------------------------------------
def test_b3_canonical_helper_resolves_pla_and_carries_the_contract_comment() -> None:
    import subprocess

    script = _console_script()
    assert isinstance(script, Path), type(script)
    assert script.is_file(), f"behavior 3: {script} must exist"
    assert script.name in {"pla", "pla.exe"}, script.name
    proc = subprocess.run(
        [str(script), "--version"], capture_output=True, text=True, timeout=30, check=False
    )
    assert proc.returncode == 0, f"behavior 3: `pla --version` exited {proc.returncode}: {proc.stderr}"
    assert "pla" in proc.stdout, f"behavior 3: `pla --version` must name pla; got {proc.stdout!r}"

    source = (REPO / OWNER_REL).read_text(encoding="utf-8")
    fn = next(f for f in _module_functions(source) if f.name == HELPER)
    body = _body_text(fn)
    for needle in ("sys.executable", "shutil.which('pla')", "'pla'", "'pla.exe'", "is_file()"):
        assert needle in body, f"behavior 3: canonical body lost {needle!r}:\n{body}"
    kinds = {type(stmt) for stmt in fn.body}
    assert ast.Assert in kinds and ast.Return in kinds, (
        "behavior 3: the canonical helper must still assert the script exists and return it"
    )
    assert fn.returns is not None and ast.unparse(fn.returns) == "Path", (
        "behavior 3: the canonical helper is annotated `-> Path`"
    )

    lines = source.splitlines()
    def_index = fn.lineno - 1
    assert lines[def_index].startswith(f"def {HELPER}("), lines[def_index]
    above = lines[max(0, def_index - COMMENT_LOOKBACK_LINES) : def_index]
    comment = "\n".join(line for line in above if line.startswith("#:")).lower()
    for cue in (SINGLE_DEFINITION_CUE, DO_NOT_CUE, LOCALIZE_CUE):
        assert cue in comment, (
            f"behavior 3: the `#:` contract comment within {COMMENT_LOOKBACK_LINES} lines above "
            f"`def {HELPER}` must say {cue!r}; got:\n" + "\n".join(above)
        )


# --------------------------------------------------------------------------
# Behaviors 4 + 5 + 6 -- funding, ledger record, and no size opinion of our own.
# --------------------------------------------------------------------------
def test_b4_b5_b6_three_duplicates_fund_the_module_and_the_ledger_records_it() -> None:
    domain = _domain()

    # Behavior 4 -- the three named duplicates are gone, the earliest copy survives.
    for rel, name in RETIRED_TESTS:
        assert rel in domain, rel
        assert name not in _names(domain[rel]), (
            f"behavior 4: {rel}::{name} is an assert-message-only duplicate retired to fund "
            "this module (see RETIRED_TESTS) and must stay deleted"
        )
        assert _collected_defs(domain[rel]) >= MIN_SURVIVING_COLLECTED, (
            f"behavior 4: {rel} must keep >= {MIN_SURVIVING_COLLECTED} tests"
        )
        assert _uses_symbol_outside_imports(domain[rel], DONOR_SYMBOL), (
            f"behavior 4: {rel} must still use {DONOR_SYMBOL} outside its import line"
        )
    for surviving_rel, surviving_name in SURVIVING_TESTS:
        assert surviving_name in _names(domain[surviving_rel]), (
            f"behavior 4: {surviving_rel}::{surviving_name} must survive -- it is either the "
            "earliest `== 14` copy the spec keeps or the test_iter263 FAMILIES keeper"
        )
    own = domain[SELF_REL]
    assert _collected_defs(own) == OWN_COLLECTED_ITEMS, (
        f"behavior 4: this module funds exactly {OWN_COLLECTED_ITEMS} collected items"
    )
    decorated = [
        fn.name
        for fn in _module_functions(own)
        if any("parametrize" in ast.unparse(d) for d in fn.decorator_list)
    ]
    assert decorated == [], (
        f"behavior 4: no parametrize -- every param would be a collected item at the wall: {decorated}"
    )

    # Behavior 5 -- exactly one #301 ledger row, tagged, naming the helper; pins agree.
    roadmap = ROADMAP.read_text(encoding="utf-8")
    rows = [line for line in roadmap.splitlines() if line.startswith(LEDGER_ROW)]
    assert len(rows) == 1, f"behavior 5: expected exactly one {LEDGER_ROW!r} row; got {rows}"
    assert rows[0].rstrip().endswith(LEDGER_TAG), f"behavior 5: row must end {LEDGER_TAG!r}: {rows[0]}"
    assert HELPER in rows[0] and "test_iter158" in rows[0], (
        f"behavior 5: the #301 row must name {HELPER} and its home test_iter158: {rows[0]}"
    )
    ledger = [line for line in roadmap.splitlines() if _LEDGER_RE.match(line)]
    assert len(ledger) == EXPECTED_LEDGER_ROWS, (
        f"behavior 5: ROADMAP.md holds {len(ledger)} ledger rows but test_iter264 pins "
        f"{EXPECTED_LEDGER_ROWS} -- bump the pin (with its `#:` comment) in the same commit"
    )
    assert len(ledger) >= LEDGER_FLOOR, f"behavior 5: ledger fell below {LEDGER_FLOOR}: {len(ledger)}"
    index = [line for line in roadmap.splitlines() if _INDEX_RE.match(line)]
    assert len(index) == INDEX_ROWS, f"behavior 5: index must keep {INDEX_ROWS} rows; got {len(index)}"
    archive = ROADMAP_ARCHIVE.read_text(encoding="utf-8")
    assert ARCHIVE_BULLET not in archive, (
        "behavior 5: #301 retires no index row, so ROADMAP_ARCHIVE.md gains no bullet"
    )

    # Behavior 6 -- this module holds no ROADMAP byte-size literal.
    assert roadmap_size_bounds(own) == (), (
        f"behavior 6: this module must not bound ROADMAP.md by size; found {roadmap_size_bounds(own)}"
    )
