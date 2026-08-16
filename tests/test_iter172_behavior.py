"""Iteration 168 (factory iter 172) -- the ``ROADMAP.md`` size budget is single-sourced.

WHAT THIS ITERATION CLAIMS (restated from the PM spec so this file stands alone)
Three gauges bounded the live index and they disagreed. Foundry's ``doctor`` heuristic
warns at 54,000 chars; the operator's ceiling in ``tests/test_roadmap_size_budget.py``
is 40,000; and -- undocumented, and the one that actually bound -- a single assertion in
``tests/test_iter168_behavior.py`` required ``40000 - len(live) > 2000``, an effective
37,999-char ceiling with 88 chars of room. That third gauge was never a budget: it was a
claim about ONE PAST EVENT (iteration 162's trim bought more than 2,000 chars)
re-evaluated forever against a document that grows by design, and it reverted an
innocent iteration whose whole diff was its own index row plus its own ledger line.
The owner module's own rationale forbids exactly that shape: "It is deliberately a
CENSUS and not a size heuristic: a 'keep 2,500 chars spare' assertion would revert an
innocent iteration for being unlucky." This iteration re-anchors the claim to the text
the trim actually MOVED (nine archive bullets, 10,857 chars, a fact that cannot decay)
and adds the oracle below so a fourth gauge cannot appear silently.

HOW THIS FILE VERIFIES IT, INDEPENDENTLY
The unit under test is a property of the TEST CORPUS, so the instrument is a pure
function over SOURCE TEXT: :func:`roadmap_size_bounds` takes a module's source and
returns every integer a size bound on the budgeted document is asserted against. It
reads no file, so the live tree is never the instrument used to test the instrument, and
it is proven TWO-SIDED on synthetic strings before it is ever pointed at the corpus --
including on the verbatim body of the assertion this iteration removes, which it must
catch. The sanctioned numbers are DERIVED by parsing the owner module with ``ast``
rather than re-typed, because a copied literal would itself be another spelling of the
number this iteration is trying to single-source.

Two oracles are built on that function. A VALUE census: no tracked test module may bound
the document's size at a number the owner does not sanction. A MEMBERSHIP brake: the set
of modules that bound it at all must equal an enumerated allowlist, so a new module
acquiring a size opinion reds the build until someone adds it deliberately, with a
reason.

LIMITS OF THIS CENSUS, STATED RATHER THAN OVERCLAIMED
Recognition is LEXICAL and deliberately narrow: the argument of ``len(...)`` counts only
when the ROOT of that expression -- a call's callee, or a name/attribute path -- names
the budgeted document. ``len(_live_roadmap())`` is recognised; ``len(_read(path))`` in
``test_roadmap_size_budget.py:416`` is NOT, because a polymorphic wrapper over a loop
variable names nothing. So a module that bounds the size through a novel wrapper name
escapes BOTH oracles, and the membership brake will not see it either. That residual is
accepted on purpose: widening the rule to the arguments of the wrapped call is what makes
the census useless, because ``len(parse_index_rows(_live_roadmap()))`` is a ROW COUNT and
would then be misread as a size bound (proven below). Names mentioning ``archive`` are
excluded for the same reason -- ``ROADMAP_ARCHIVE.md`` is a different document, and a
bound on its size is not a bound on this one.

Four traps this file respects on purpose.
1. VACUOUS GREEN. An empty domain, an empty ``git`` listing, or an extractor that
   silently stopped recognising call sites would make every census pass. So the corpus
   listing, the domain size and the number of bounds actually FOUND all have floors.
2. AMBIENT / GITIGNORED STATE. Every path read here is git-tracked, so every
   precondition holds in the throwaway fresh clone each ship is re-verified from.
3. SELF-BLINDNESS. A census whose domain is ``git ls-files`` cannot see itself while it
   is untracked (OPERATOR 2026-08-14), and it is precisely this module that spells the
   retired ``2000`` most often -- inside string fixtures. So this module's own path is
   UNIONED into the domain rather than merely expected to appear there, and a test
   requires its own bounds to be empty.
4. INTERPRETER SKEW. CI runs 3.12 and 3.13 and 3.13 strips the common leading docstring
   indent at compile time, so nothing here asserts on indentation or on docstring text.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Final

REPO: Final[Path] = Path(__file__).resolve().parents[1]

#: The document whose size budget this module single-sources.
BUDGETED_DOC: Final[str] = "ROADMAP.md"

#: The module that OWNS the sanctioned numbers; the only place they may be edited.
BUDGET_OWNER: Final[str] = "tests/test_roadmap_size_budget.py"

#: The owner's two constants, read out of its source in this order.
SANCTIONED_CONSTANTS: Final[tuple[str, ...]] = (
    "ROADMAP_CHAR_LIMIT",
    "ROADMAP_CHAR_FLOOR",
)

#: This module's own repo-relative path, DERIVED so a rename cannot make the census
#: blind to itself (trap 3).
SELF_PATH: Final[str] = Path(__file__).resolve().relative_to(REPO).as_posix()

#: The enumerated allowlist for the membership brake, with the reason each entry is
#: allowed to hold a size opinion. MEASURED, not assumed: the other two modules that
#: spell the ceiling (``test_roadmap_size_budget.py``, ``test_iter164_behavior.py``)
#: never apply ``len`` to a named producer of this document inside an assert -- the
#: owner enforces its ceiling through a verdict object, not an assertion -- so they are
#: correctly absent. Adding an entry is a deliberate act that needs a reason here.
SIZE_BOUND_ALLOWLIST: Final[dict[str, str]] = {
    "tests/test_iter168_behavior.py": (
        "asserts the operator ceiling itself (len(live) < CEILING == 40000); it is the "
        "black-box restatement of the owner's limit and predates this census"
    ),
}

#: A ``len(...)`` argument counts only when its ROOT identifier chain mentions this.
_PRODUCER = re.compile(r"(?i)roadmap")

#: ...and mentions none of this. ``ROADMAP_ARCHIVE.md`` is a different document.
_NOT_PRODUCER = re.compile(r"(?i)archive")

#: Scope nodes: taint is tracked per scope so a local name in one function cannot
#: silently redefine what an assert in another function is measuring.
_SCOPES: Final[tuple[type[ast.AST], ...]] = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Lambda,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures -- the two-sided proof, none of which touch the live tree.
# ---------------------------------------------------------------------------
#: The VERBATIM body of the assertion this iteration removes. The extractor must catch
#: it, or the census cannot claim to prevent a recurrence.
PRE_FIX_SAMPLE: Final[str] = (
    "def test_b11_the_trim_left_more_than_two_thousand_chars_of_headroom() -> None:\n"
    '    """The stated purpose was buying headroom, not merely staying legal: the row\n'
    '    that shipped this claims 36,981 chars against 40,000."""\n'
    "    headroom = CEILING - len(_live_roadmap())\n"
    '    assert headroom > 2000, f"only {headroom} chars of headroom -- '
    'the trim did not land"\n'
)

#: The obvious false positive: a ROW COUNT, not a size bound.
ROW_COUNT_SAMPLE: Final[str] = "assert len(rows) >= 20\n"

#: The subtle false positive, and the reason recognition stays at the expression ROOT:
#: this counts parsed rows, and every character of the document is in the argument.
PARSED_ROWS_SAMPLE: Final[str] = (
    "assert len(parse_index_rows(_live_roadmap())) >= 20\n"
)

#: A bound on the ARCHIVE is not a bound on the index.
ARCHIVE_SAMPLE: Final[str] = "assert len(_live_roadmap_archive()) > 5000\n"


# ---------------------------------------------------------------------------
# The instrument: a pure function over source text.
# ---------------------------------------------------------------------------
def _root_identifiers(node: ast.expr) -> tuple[str, ...]:
    """The identifiers naming the ROOT of an expression: a callee, or a dotted path.

    A call's ARGUMENTS are deliberately not included. Including them is what turns
    ``len(parse_index_rows(_live_roadmap()))`` -- a row count -- into a false size bound.
    """
    root: ast.AST = node.func if isinstance(node, ast.Call) else node
    parts: list[str] = []
    while isinstance(root, ast.Attribute):
        parts.append(root.attr)
        root = root.value
    if isinstance(root, ast.Name):
        parts.append(root.id)
    return tuple(parts)


def _is_budgeted_length(node: ast.AST) -> bool:
    """True for ``len(<expression naming the budgeted document>)``."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        and len(node.args) == 1
        and not node.keywords
    ):
        return False
    names = _root_identifiers(node.args[0])
    return any(_PRODUCER.search(name) for name in names) and not any(
        _NOT_PRODUCER.search(name) for name in names
    )


def _module_level_ints(tree: ast.Module) -> dict[str, int]:
    """Module-level ``NAME = <int>`` bindings, so ``assert chars < CEILING`` resolves.

    Without this the census would be blind to every bound expressed through a named
    constant, which is how the ceiling is spelled today.
    """
    found: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        if isinstance(value, ast.Constant) and _is_plain_int(value.value):
            for target in targets:
                if isinstance(target, ast.Name):
                    found[target.id] = int(value.value)
    return found


def _is_plain_int(value: object) -> bool:
    """``True`` for a real integer. ``bool`` is an ``int`` subclass and is not one."""
    return isinstance(value, int) and not isinstance(value, bool)


def _own_statements(scope: ast.AST) -> list[ast.stmt]:
    """Statements belonging to ``scope`` in SOURCE ORDER, not descending into nested
    scopes.

    Source order matters: the taint that makes ``assert headroom > 2000`` a size bound is
    established by an assignment ABOVE it, and a breadth-first walk does not guarantee
    that ordering.
    """
    collected: list[ast.stmt] = []
    pending: list[ast.AST] = [scope]
    while pending:
        node = pending.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _SCOPES):
                continue
            if isinstance(child, ast.stmt):
                collected.append(child)
            pending.append(child)
    return sorted(collected, key=lambda stmt: (stmt.lineno, stmt.col_offset))


def _assigned_names(stmt: ast.stmt) -> tuple[str, ...]:
    targets: list[ast.expr]
    if isinstance(stmt, ast.Assign):
        targets = list(stmt.targets)
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    else:
        return ()
    return tuple(t.id for t in targets if isinstance(t, ast.Name))


def _measures_budgeted_length(node: ast.AST, tainted: frozenset[str]) -> bool:
    """Does this statement measure the document, directly or through a tainted name?"""
    for sub in ast.walk(node):
        if _is_budgeted_length(sub):
            return True
        if isinstance(sub, ast.Name) and sub.id in tainted:
            return True
    return False


def _integers(node: ast.AST, constants: dict[str, int]) -> tuple[int, ...]:
    """Every integer the statement compares against, literals and named constants."""
    found: set[int] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and _is_plain_int(sub.value):
            found.add(int(sub.value))
        elif isinstance(sub, ast.Name) and sub.id in constants:
            found.add(constants[sub.id])
    return tuple(sorted(found))


def located_roadmap_size_bounds(module_source: str) -> tuple[tuple[int, int], ...]:
    """``(lineno, bound)`` for every size bound asserted over the budgeted document.

    Pure: takes source TEXT and returns a value. It opens no file, so pointing it at the
    live tree is a choice the caller makes rather than a dependency of the instrument.
    """
    tree = ast.parse(module_source)
    constants = _module_level_ints(tree)
    scopes: list[ast.AST] = [tree]
    scopes.extend(node for node in ast.walk(tree) if isinstance(node, _SCOPES))
    found: set[tuple[int, int]] = set()
    for scope in scopes:
        tainted: set[str] = set()
        for stmt in _own_statements(scope):
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                if stmt.value is not None and _measures_budgeted_length(
                    stmt.value, frozenset(tainted)
                ):
                    tainted.update(_assigned_names(stmt))
            elif isinstance(stmt, ast.Assert):
                if _measures_budgeted_length(stmt, frozenset(tainted)):
                    found.update(
                        (stmt.lineno, bound) for bound in _integers(stmt, constants)
                    )
    return tuple(sorted(found))


def roadmap_size_bounds(module_source: str) -> tuple[int, ...]:
    """Every integer a size bound on the budgeted document is asserted against."""
    return tuple(bound for _, bound in located_roadmap_size_bounds(module_source))


# ---------------------------------------------------------------------------
# The corpus: what the oracles are pointed at.
# ---------------------------------------------------------------------------
def sanctioned_bounds() -> tuple[int, ...]:
    """The owner module's two constants, DERIVED from its source, never re-typed."""
    source = (REPO / BUDGET_OWNER).read_text(encoding="utf-8")
    ints = _module_level_ints(ast.parse(source))
    missing = [name for name in SANCTIONED_CONSTANTS if name not in ints]
    assert not missing, (
        f"{BUDGET_OWNER} no longer binds {missing} to a module-level integer, so the "
        "sanctioned set cannot be derived and this census would be vacuous"
    )
    return tuple(ints[name] for name in SANCTIONED_CONSTANTS)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def tracked_test_modules() -> tuple[str, ...]:
    """Every tracked module under ``tests/``, plus THIS one (trap 3)."""
    listed = _git("ls-files", "tests")
    assert listed.returncode == 0, (
        f"git ls-files exited {listed.returncode}, so the corpus is unknown and this "
        f"census would be fail-open: {listed.stderr.strip()!r}"
    )
    paths = {
        line.strip()
        for line in listed.stdout.splitlines()
        if line.strip().endswith(".py")
    }
    assert len(paths) >= 100, (
        f"git ls-files tests listed only {len(paths)} modules -- the listing is "
        "fail-open and every census below would pass vacuously"
    )
    return tuple(sorted(paths | {SELF_PATH}))


def census_domain() -> dict[str, str]:
    """``relpath -> source`` for every corpus module that mentions the document."""
    domain: dict[str, str] = {}
    for relpath in tracked_test_modules():
        source = (REPO / relpath).read_text(encoding="utf-8")
        if BUDGETED_DOC in source:
            domain[relpath] = source
    return domain


# ---------------------------------------------------------------------------
# Behavior 6 -- the instrument is two-sided, on synthetic strings only.
# ---------------------------------------------------------------------------
def test_the_instrument_catches_the_bound_this_iteration_removes() -> None:
    """The positive side, and the whole warrant for the census: fired on the verbatim
    body of the removed assertion, the extractor must report its 2,000."""
    assert 2000 in roadmap_size_bounds(PRE_FIX_SAMPLE), (
        "the extractor does not catch the very assertion this iteration removes, so it "
        f"cannot prevent a recurrence: {roadmap_size_bounds(PRE_FIX_SAMPLE)}"
    )


def test_the_instrument_ignores_a_row_count() -> None:
    """The negative side: a count of parsed rows is not a bound on the file's size."""
    assert roadmap_size_bounds(ROW_COUNT_SAMPLE) == ()


def test_the_instrument_ignores_a_count_taken_over_the_parsed_document() -> None:
    """The subtle negative side: the document IS in the argument, and it is still a row
    count. This is the case that fixes recognition at the expression root."""
    assert roadmap_size_bounds(PARSED_ROWS_SAMPLE) == ()


def test_the_instrument_ignores_a_bound_on_the_archive() -> None:
    """``ROADMAP_ARCHIVE.md`` is a different document with no operator ceiling."""
    assert roadmap_size_bounds(ARCHIVE_SAMPLE) == ()


def test_the_instrument_reports_a_line_number_for_every_bound() -> None:
    """The census failure message has to be actionable without opening this file."""
    located = located_roadmap_size_bounds(PRE_FIX_SAMPLE)
    assert located, "no bound located in the known-bad sample"
    assert all(lineno > 0 for lineno, _ in located), located
    assert {bound for _, bound in located} == set(roadmap_size_bounds(PRE_FIX_SAMPLE))


# ---------------------------------------------------------------------------
# Behavior 7 -- the sanctioned numbers are derived, never re-typed.
# ---------------------------------------------------------------------------
def test_the_sanctioned_bounds_are_derived_from_the_owner_module() -> None:
    """Parsed out of the owner's SOURCE. A copied literal would itself be another
    spelling of the number this iteration single-sources."""
    assert sanctioned_bounds() == (40000, 10000), (
        f"{BUDGET_OWNER} now sanctions {sanctioned_bounds()}; the operator's ceiling "
        "and anti-vacuity floor are 40000 and 10000 and only an operator may change them"
    )


# ---------------------------------------------------------------------------
# Behavior 8 -- the VALUE census: no unsanctioned bound anywhere in the corpus.
# ---------------------------------------------------------------------------
def test_no_tracked_module_bounds_the_document_at_an_unsanctioned_number() -> None:
    sanctioned = set(sanctioned_bounds())
    domain = census_domain()
    assert len(domain) >= 5, (
        f"only {len(domain)} corpus modules mention {BUDGETED_DOC} -- the domain "
        "collapsed and this census is now vacuous"
    )
    located = {
        relpath: located_roadmap_size_bounds(source)
        for relpath, source in domain.items()
    }
    assert any(located.values()), (
        "no module in the corpus bounds the document's size at all, which means the "
        "extractor has stopped recognising call sites: this census is vacuous"
    )
    offenders = [
        f"{relpath}:{lineno} bounds len({BUDGETED_DOC}) at {bound}"
        for relpath, bounds in sorted(located.items())
        for lineno, bound in bounds
        if bound not in sanctioned
    ]
    assert offenders == [], (
        f"these assertions bound the size of {BUDGETED_DOC} at a number "
        f"{BUDGET_OWNER} does not sanction ({sorted(sanctioned)}), so the real budget "
        "is whichever of them is tightest and nothing documents it: " + str(offenders)
    )


# ---------------------------------------------------------------------------
# Behavior 9 -- the MEMBERSHIP brake: a new size opinion must be deliberate.
# ---------------------------------------------------------------------------
def test_the_modules_bounding_the_document_equal_the_documented_allowlist() -> None:
    bounding = {
        relpath
        for relpath, source in census_domain().items()
        if located_roadmap_size_bounds(source)
    }
    assert bounding == set(SIZE_BOUND_ALLOWLIST), (
        "the set of modules bounding this document's size drifted from the allowlist. "
        f"Newly bounding: {sorted(bounding - set(SIZE_BOUND_ALLOWLIST))}. No longer "
        f"bounding: {sorted(set(SIZE_BOUND_ALLOWLIST) - bounding)}. Add an entry with a "
        "reason, or remove the bound"
    )


def test_every_allowlist_entry_names_a_real_module_and_states_a_reason() -> None:
    """An allowlist whose entries are stale or unexplained is a rubber stamp."""
    for relpath, reason in SIZE_BOUND_ALLOWLIST.items():
        assert (REPO / relpath).is_file(), f"{relpath} is allowlisted but absent"
        assert len(reason.split()) >= 8, f"{relpath}: reason is too thin: {reason!r}"


# ---------------------------------------------------------------------------
# Behavior 10 -- the census is not blind to itself.
# ---------------------------------------------------------------------------
def test_this_module_is_inside_the_domain_and_holds_no_size_opinion() -> None:
    """A census whose domain is ``git ls-files`` reads GREEN while its own file is
    untracked (OPERATOR 2026-08-14), and this module spells the retired ``2000`` more
    often than any other -- inside string fixtures. So it is unioned into the domain and
    required to contribute nothing."""
    domain = census_domain()
    assert SELF_PATH in domain, (
        f"{SELF_PATH} is outside its own census domain, so the census cannot see itself"
    )
    assert roadmap_size_bounds(domain[SELF_PATH]) == (), (
        "this module now asserts a size bound of its own -- most likely by wrapping a "
        "roadmap-named call in len() inside an assert. Compare tuples instead"
    )
    assert SELF_PATH not in SIZE_BOUND_ALLOWLIST


def test_the_string_fixtures_are_not_mistaken_for_real_assertions() -> None:
    """The fixtures hold real assert syntax, and it must stay data: a Constant in this
    module's AST, never a statement. This is the same distinction the census depends on
    when it reads any other module's source."""
    tree = ast.parse((REPO / SELF_PATH).read_text(encoding="utf-8"))
    literal_bounds = {
        text
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        for text in [node.value]
        if "assert " in text
    }
    assert literal_bounds, "the synthetic fixtures vanished; the two-sided proof is gone"
