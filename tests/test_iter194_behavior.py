"""The walk-prune policy gets exactly ONE definition in the collectors package
(foundry state dir ``iter-190``).

WHAT THIS MODULE PINS.  ``collectors/dir_source.py`` justifies serving one shared
directory listing to every walking collector on a load-bearing claim: that the
product has "exactly ONE prune set and there is no set-difference risk to
reconcile".  Before this iteration that claim was FALSE -- ``notes.py`` and
``todos.py`` each hand-copied their own ``_SKIP_DIRS`` and ``_is_hidden``, and both
copies had already drifted from the owner set.  The divergence was invisible in
behavior only by luck (the single differing member was dot-prefixed, so the hidden
rule pruned it anyway); the first NON-dotted addition to the owner set would have
silently split the product's pruning in two, under a docstring asserting that
cannot happen.  This iteration deletes the copies so the two holdouts import the
single owner's rules, and guards the property with a census.

THE VACUOUS-PROOF TRAP, and the three things that guard against it here.  An
"unchanged behavior" test would pass just as well against two equal copies, so:

* Behavior 1 asserts object IDENTITY (``is``).  An equal-but-separate copy FAILS
  it, which an equality assertion would not notice.
* Behaviors 2/3 assert the census result is ``== 1`` and never ``<= 1``.  All
  three of the original definition sites were ANNOTATED assignments, so an
  ``ast.Assign``-only matcher finds ZERO -- and ``<= 1`` would pass VACUOUSLY on
  exactly that broken matcher.  ``== 1`` fails closed instead.
* Behavior 4 proves the census two-sided against synthetic module SOURCE TEXT: a
  planted second definition must make it report 2 and FAIL, while the same
  synthetic module WITHOUT the duplicate must still pass.  So the passing census
  in behaviors 2/3 cannot be an artifact of a matcher that can never fire.  No
  file is ever written into the real package to prove this.

DELIBERATELY NOT ASSERTED (the spec's Out of Scope, recorded so a later reader
does not mistake the omissions for gaps):

* ``.tox`` is NOT used as the feature's oracle.  ``_is_hidden`` is
  ``startswith(".")`` and every prune site ANDs it, so a ``.tox`` behavior
  assertion passed even against the drifted copies -- it is vacuous as a feature
  oracle.  Behavior 6 keeps it only as a REGRESSION assertion protecting the
  refactor, with the un-pruned ``pkg/a.py`` marker as its positive control.
* The three former ``_is_hidden`` definitions are NOT compared as source TEXT.
  The owner's carries a docstring and the copies did not, so a textual identity
  assertion reds the build on a correct tree.  The BODIES were identical, which
  is what made the deletion safe, and behavior 1 asserts the surviving OBJECT.

ISOLATION CONTRACT (honored): every assertion is written from this iteration's
spec (``pm.md`` "Expected Behaviors" 1-6 plus its Acceptance Criteria) and drives
public surfaces only -- ``TodoCollector().collect(root)``, module-level
introspection of imported objects, and an ``ast`` census, which is the oracle the
spec itself names for behaviors 2-5.  **No file under ``src/`` was read by the
author, no engineer / reviewer note was opened, and no ``git diff`` was
consulted.**  Where a runtime shape was needed (the collector's constructor takes
no required argument; the emitted signal exposes ``path`` / ``summary``) it was
taken from the RUNNING product and from existing usage under ``tests/``, which is
the "read the product's own help/output by running it" affordance the role grants.

Fully offline and deterministic: no network, no subprocess, no git dependency.
Every writable fixture is built under ``tmp_path``.

FRESH-CLONE SAFETY (the ``_platform`` iter-154 post-release break): the only reads
outside ``tmp_path`` are of GIT-TRACKED files under ``src/proactive_loop/`` and
``tests/`` -- never a count of, or an assertion about, gitignored ambient state --
so every oracle here holds in a throwaway clone.  The census domain is
``src/proactive_loop/collectors/*.py``, which does NOT contain this module, so the
2026-08-14 self-blindness pin does not bite.

AMBIGUITY NOTES (PM feedback, see ``tester.md``):

* The spec says "EXACTLY ONE module-level definition ... and its module is
  ``filesystem.py``".  That is pinned as an exact list equality
  (``== ["filesystem.py"]``), which asserts the count and the owner in one
  measurement; a separate ``len() == 1`` would be redundant.
* Nested definitions are excluded deliberately: the claim is about MODULE-LEVEL
  definitions, and a same-named local inside some function would be a different
  object with no drift risk.
* Behavior 5 says the message names "the offending module file(s)".  Read as the
  duplicate sites specifically, so the message lists the non-owner modules by
  name; the owner is named separately as the single owner.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest

from proactive_loop.collectors import TodoCollector, filesystem, notes, todos

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "proactive_loop"
COLLECTORS = SRC / "collectors"
FILESYSTEM_MOD = "proactive_loop.collectors.filesystem"
OWNER_FILE = "filesystem.py"
SINGLE_OWNER = "collectors/filesystem.py"

# The spec's owner value, measured from the RUNNING product (7 members).
SPEC_SKIP_DIRS = frozenset(
    {".git", ".tox", ".venv", "__pycache__", "build", "dist", "node_modules"}
)

# Synthetic module SOURCE TEXT for the two-sided census proof (behavior 4).  These
# are parsed as strings -- never written into the real package.
SYNTH_CLEAN = "from __future__ import annotations\n\nVALUE = 1\n"
SYNTH_ANNOTATED_SKIP_DIRS = '_SKIP_DIRS: frozenset[str] = frozenset({"x"})\n'
SYNTH_PLAIN_SKIP_DIRS = '_SKIP_DIRS = frozenset({"x"})\n'
SYNTH_IS_HIDDEN = 'def _is_hidden(name: str) -> bool:\n    return name.startswith(".")\n'
INTRUDER = "intruder.py"


# --------------------------------------------------------------------------
# helpers -- the ast census, driven off SOURCE TEXT so it is testable in-test
# --------------------------------------------------------------------------
def _module_level_bindings(tree: ast.Module) -> list[str]:
    """Module-level assigned names, counting BOTH ``Assign`` and ``AnnAssign``."""
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names


def _module_level_functions(tree: ast.Module) -> list[str]:
    return [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _census(kind: str, name: str, sources: Mapping[str, str]) -> list[str]:
    """Names of every source in ``sources`` whose MODULE LEVEL defines ``name``."""
    lookup = _module_level_functions if kind == "func" else _module_level_bindings
    return sorted(
        filename
        for filename, text in sources.items()
        if name in lookup(ast.parse(text, filename=filename))
    )


def _assert_single_owner(kind: str, name: str, sources: Mapping[str, str]) -> None:
    """Assert ``name`` is defined EXACTLY ONCE, by the owner module.

    ``== [OWNER_FILE]`` rather than ``<= 1``: a broken matcher finds zero sites and
    would pass a ``<=`` bound vacuously, and the owner must be pinned too.
    """
    owners = _census(kind, name, sources)
    offenders = [o for o in owners if o != OWNER_FILE]
    what = "definition" if kind == "func" else "assignment"
    assert owners == [OWNER_FILE], (
        f"duplicated name {name}: expected EXACTLY ONE module-level {what} of "
        f"{name} in the collectors package, found {len(owners)} in {owners} -- "
        f"offending module file(s): {offenders or owners}; the single owner is "
        f"{SINGLE_OWNER}"
    )


def _collectors_sources() -> dict[str, str]:
    """Source text of every module in the collectors package, keyed by file name."""
    files = sorted(COLLECTORS.glob("*.py"))
    assert len(files) >= 5, (
        f"census found only {len(files)} module(s) under {COLLECTORS} -- the "
        "oracle would be vacuous"
    )
    names = {p.name for p in files}
    for required in (OWNER_FILE, "notes.py", "todos.py", "dir_source.py"):
        assert required in names, f"census domain is missing {required}: {sorted(names)}"
    return {p.name: p.read_text(encoding="utf-8") for p in files}


def _from_imports(path: Path) -> dict[str, set[str]]:
    """Map absolute-resolved module -> imported names, for every ``from`` import."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    pkg_parts = path.relative_to(SRC.parent).with_suffix("").parts[:-1]
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:  # relative -- resolve against this file's package
            base = list(pkg_parts[: len(pkg_parts) - (node.level - 1)])
        else:
            base = []
        target = ".".join([*base, *([node.module] if node.module else [])])
        out.setdefault(target, set()).update(a.name for a in node.names)
    return out


def _normalised(path: Path) -> str:
    """Whitespace-collapsed file text, so a wrapped sentence still matches."""
    return " ".join(path.read_text(encoding="utf-8").split())


# --------------------------------------------------------------------------
# behavior 1 -- IDENTITY, not equality
# --------------------------------------------------------------------------
def test_b01_both_holdouts_share_the_owners_prune_rules_by_identity() -> None:
    assert todos._SKIP_DIRS is filesystem._SKIP_DIRS, (
        "todos._SKIP_DIRS must be the SAME OBJECT as filesystem._SKIP_DIRS; an "
        "equal-but-separate copy is exactly the drift this iteration removes"
    )
    assert notes._SKIP_DIRS is filesystem._SKIP_DIRS, (
        "notes._SKIP_DIRS must be the SAME OBJECT as filesystem._SKIP_DIRS"
    )
    assert todos._is_hidden is filesystem._is_hidden, (
        "todos._is_hidden must be the SAME FUNCTION OBJECT as filesystem._is_hidden"
    )
    assert notes._is_hidden is filesystem._is_hidden, (
        "notes._is_hidden must be the SAME FUNCTION OBJECT as filesystem._is_hidden"
    )
    # ...and the surviving object really is defined by the owner, not re-bound.
    assert filesystem._is_hidden.__module__ == FILESYSTEM_MOD


# --------------------------------------------------------------------------
# behavior 2 -- exactly ONE module-level _SKIP_DIRS, in filesystem.py
# --------------------------------------------------------------------------
def test_b02_skip_dirs_is_assigned_exactly_once_in_the_collectors_package() -> None:
    sources = _collectors_sources()
    assert _census("bind", "_SKIP_DIRS", sources) == [OWNER_FILE]
    _assert_single_owner("bind", "_SKIP_DIRS", sources)


# --------------------------------------------------------------------------
# behavior 3 -- exactly ONE module-level def _is_hidden, in filesystem.py
# --------------------------------------------------------------------------
def test_b03_is_hidden_is_defined_exactly_once_in_the_collectors_package() -> None:
    sources = _collectors_sources()
    assert _census("func", "_is_hidden", sources) == [OWNER_FILE]
    _assert_single_owner("func", "_is_hidden", sources)


# --------------------------------------------------------------------------
# behavior 4 -- the census is TWO-SIDED, proved against source strings
# --------------------------------------------------------------------------
def test_b04_control_an_extra_module_without_a_duplicate_still_passes() -> None:
    """The control for the two FAIL cases below.

    Without this, the failures could be an artifact of adding a module at all
    rather than of the duplicate definition it carries.
    """
    sources = {**_collectors_sources(), INTRUDER: SYNTH_CLEAN}
    assert _census("bind", "_SKIP_DIRS", sources) == [OWNER_FILE]
    assert _census("func", "_is_hidden", sources) == [OWNER_FILE]
    _assert_single_owner("bind", "_SKIP_DIRS", sources)
    _assert_single_owner("func", "_is_hidden", sources)


@pytest.mark.parametrize(
    "synthetic",
    [SYNTH_ANNOTATED_SKIP_DIRS, SYNTH_PLAIN_SKIP_DIRS],
    ids=["annotated", "plain"],
)
def test_b04_a_second_skip_dirs_makes_the_census_report_two_and_fail(
    synthetic: str,
) -> None:
    sources = {**_collectors_sources(), INTRUDER: synthetic}
    owners = _census("bind", "_SKIP_DIRS", sources)
    assert owners == [OWNER_FILE, INTRUDER], f"census missed the planted copy: {owners}"
    assert len(owners) == 2
    with pytest.raises(AssertionError):
        _assert_single_owner("bind", "_SKIP_DIRS", sources)


def test_b04_a_second_is_hidden_makes_the_census_report_two_and_fail() -> None:
    sources = {**_collectors_sources(), INTRUDER: SYNTH_IS_HIDDEN}
    owners = _census("func", "_is_hidden", sources)
    assert owners == [OWNER_FILE, INTRUDER], f"census missed the planted copy: {owners}"
    assert len(owners) == 2
    with pytest.raises(AssertionError):
        _assert_single_owner("func", "_is_hidden", sources)


def test_b04_the_census_counts_annotated_assignments_not_only_plain_ones() -> None:
    """An ``ast.Assign``-only matcher finds ZERO on this tree, so this is the
    assertion that stops behaviors 2/3 passing on a broken matcher."""
    assert _census("bind", "_SKIP_DIRS", {"only.py": SYNTH_ANNOTATED_SKIP_DIRS}) == [
        "only.py"
    ]
    assert _census("bind", "_SKIP_DIRS", {"only.py": SYNTH_PLAIN_SKIP_DIRS}) == ["only.py"]
    # ...and it does NOT fire on an unrelated module (no false positive).
    assert _census("bind", "_SKIP_DIRS", {"only.py": SYNTH_CLEAN}) == []


def test_b04_a_nested_same_named_definition_is_not_a_module_level_site() -> None:
    nested = (
        "def outer() -> None:\n"
        '    _SKIP_DIRS = frozenset({"x"})\n'
        "    def _is_hidden(name: str) -> bool:\n"
        "        return True\n"
    )
    assert _census("bind", "_SKIP_DIRS", {"nested.py": nested}) == []
    assert _census("func", "_is_hidden", {"nested.py": nested}) == []


# --------------------------------------------------------------------------
# behavior 5 -- the failure message identifies the offender
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "name", "synthetic"),
    [
        ("bind", "_SKIP_DIRS", SYNTH_ANNOTATED_SKIP_DIRS),
        ("func", "_is_hidden", SYNTH_IS_HIDDEN),
    ],
    ids=["skip_dirs", "is_hidden"],
)
def test_b05_failure_message_names_offender_duplicated_name_and_single_owner(
    kind: str, name: str, synthetic: str
) -> None:
    sources = {**_collectors_sources(), INTRUDER: synthetic}
    with pytest.raises(AssertionError) as excinfo:
        _assert_single_owner(kind, name, sources)
    message = str(excinfo.value)
    assert INTRUDER in message, f"message must name the offending module: {message}"
    assert name in message, f"message must name the duplicated name: {message}"
    assert SINGLE_OWNER in message, f"message must name the single owner: {message}"


# --------------------------------------------------------------------------
# behavior 6 -- prune REGRESSION, two-sided (positive control + negatives)
# --------------------------------------------------------------------------
def test_b06_todo_markers_inside_pruned_directories_are_never_collected(
    tmp_path: Path,
) -> None:
    fixture = {
        "pkg/a.py": "# TODO: alpha marker\n",
        "node_modules/b.py": "# TODO: beta marker\n",
        ".tox/c.py": "# TODO: gamma marker\n",
    }
    for rel, text in fixture.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    signals = TodoCollector().collect(tmp_path)
    paths = [s.path or "" for s in signals]

    # Positive control FIRST: an empty result would make the negatives vacuous.
    assert [s.summary for s in signals] == ["TODO: alpha marker"], (
        f"expected exactly the un-pruned pkg/a.py marker; got {paths!r}"
    )
    assert paths[0].startswith("pkg/a.py"), paths[0]

    for reported in paths:
        segments = reported.split(":")[0].split("/")
        assert "node_modules" not in segments, f"walked into node_modules: {reported}"
        assert ".tox" not in segments, f"walked into .tox: {reported}"


# --------------------------------------------------------------------------
# Acceptance Criteria that are checkable by SHAPE (never by guessed prose)
# --------------------------------------------------------------------------
def test_ac_holdouts_import_the_rules_and_declare_neither() -> None:
    sources = _collectors_sources()
    for mod_name in ("notes.py", "todos.py"):
        tree = ast.parse(sources[mod_name], filename=mod_name)
        assert "_SKIP_DIRS" not in _module_level_bindings(tree), (
            f"{mod_name} still declares its own _SKIP_DIRS"
        )
        assert "_is_hidden" not in _module_level_functions(tree), (
            f"{mod_name} still declares its own _is_hidden"
        )
        froms = _from_imports(COLLECTORS / mod_name)
        imported = froms.get(FILESYSTEM_MOD, set())
        for required in ("_SKIP_DIRS", "_is_hidden"):
            assert required in imported, (
                f"{mod_name} must import {required} from {FILESYSTEM_MOD}; its "
                f"from-imports are {froms}"
            )


def test_ac_owner_value_is_unchanged_and_immutable() -> None:
    assert filesystem._SKIP_DIRS == SPEC_SKIP_DIRS
    # A shared module-level constant is only safe to hoist if a caller cannot
    # mutate it; == alone cannot see the container type (set == frozenset).
    assert isinstance(filesystem._SKIP_DIRS, frozenset)


def test_ac_dir_sources_shared_listing_claim_survives_verbatim_and_is_now_true() -> None:
    """``dir_source.py`` is NOT edited -- the deletion makes its claim true.

    Pinned whitespace-normalised so the docstring's line wrapping is irrelevant.
    """
    text = _normalised(COLLECTORS / "dir_source.py")
    for sentence in ("exactly ONE prune set", "there is no set-difference risk to reconcile"):
        assert text.count(sentence) == 1, (
            f"dir_source.py must still carry {sentence!r} exactly once (found "
            f"{text.count(sentence)}) -- the fix makes the claim true, it does "
            "not weaken the claim"
        )
    # ...and the claim is TRUE, which is the whole point of behaviors 2/3.
    sources = _collectors_sources()
    assert _census("bind", "_SKIP_DIRS", sources) == [OWNER_FILE]
    assert _census("func", "_is_hidden", sources) == [OWNER_FILE]


def test_ac_large_file_keeps_its_own_is_hidden_import() -> None:
    """Row #210: ``large_file`` calls ``_is_hidden`` on FILES and is untouched."""
    froms = _from_imports(COLLECTORS / "large_file.py")
    assert "_is_hidden" in froms.get(FILESYSTEM_MOD, set()), (
        f"large_file.py must keep importing _is_hidden from {FILESYSTEM_MOD}; "
        f"its from-imports are {froms}"
    )


def test_ac_owner_does_not_import_the_holdouts_so_there_is_no_cycle() -> None:
    froms = _from_imports(COLLECTORS / OWNER_FILE)
    for holdout in ("notes", "todos"):
        target = f"proactive_loop.collectors.{holdout}"
        assert target not in froms, (
            f"{OWNER_FILE} must not import {target} -- that would be the import "
            f"cycle the acceptance criteria forbid; from-imports are {froms}"
        )


def test_ac_iter109_stale_declares_its_own_set_comment_is_repaired() -> None:
    """The coupled comment in ``tests/test_iter109_behavior.py``.

    Pinned as the ABSENCE of the measured stale claim, not as a guess at the new
    wording -- guessing prose is how a guard reds the build on its own author.
    ``notes`` now IMPORTS the 7-member owner set, so a comment saying the module
    declares that contract itself is false.
    """
    text = _normalised(REPO / "tests" / "test_iter109_behavior.py")
    assert "skip contract the module already declares" not in text, (
        "test_iter109_behavior.py still claims notes declares its own skip "
        "contract; notes now imports it from collectors/filesystem.py"
    )
