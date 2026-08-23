"""Black-box oracle for factory iteration 237 -- shared-traversal batch 3.

Feature under test: ``merge_conflict`` and ``broken_link`` stop running their own
``os.walk`` of the workspace and read the shared per-scan dirent listing from
``collectors/dir_source``, taking the collectors served by the ONE shared
traversal from 4 to 6 and a scan's traversal count from 8 to 6.

MODULE NAME (derived from the repo, never from the state dir). ``git ls-files
tests`` tops out at ``test_iter215_behavior.py`` and ``git cat-file -e
HEAD:tests/test_iter216_behavior.py`` exits 128, so 216 is the next free number.
The foundry state dir for this ship is ``iter-237``; naming a module from that
counter is how a shipped oracle gets overwritten, so the repo wins.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived
from this iteration's ``pm.md`` "Expected Behaviors" 1-8, from the conventions of
``tests/test_iter187_behavior.py`` (the batch-2 oracle: the autouse cache
isolation fixture, the counting/reversing ``os.walk`` wrappers, the signal
projection) and ``tests/test_iter206_behavior.py`` (the broken-link fixture
shape), and from RUNNING the public interface. **No file under ``src/`` was read
as source text, no engineer or reviewer note was opened, and no ``git diff`` was
consulted.** Behavior 8 measures tracked source BYTES mechanically (token
counts), which is a census, not design reading.

SPEC DEVIATION, recorded as PM feedback. ``pm.md`` names the class
``BrokenLinkCollector``; the shipped public name is ``BrokenDocLinkCollector``
in ``proactive_loop.collectors.broken_link`` (``kind == "broken_link"``), which
is what ``tests/test_iter206_behavior.py`` and ``tests/test_iter144_behavior.py``
already drive. The real name wins.

Offline and deterministic: ``tmp_path`` fixture trees only, no network, no
subprocess, no wall-clock or timing assertion anywhere -- traversal COUNTS and
signal EQUALITY only, both regime-free integers/strings. Nothing asserts on
docstring or help-text indentation, so the 3.12/3.13 matrix legs cannot diverge.

Coverage (numbered to match the spec's Expected Behaviors):

1. One ``cli._collect`` reports ``hits == 5`` / ``misses == 1`` and leaves
   ``entries == dirs == 0`` (parent commit measured 3 hits, 1 miss).
2. Inside ONE ``walk_scope()`` the pair performs exactly ONE physical
   ``os.walk`` rooted at the shared root (parent commit: two). Each collector
   alone inside a scope also walks once.
3. Signals are unchanged, pinned as literals captured from the PARENT commit,
   with an anti-vacuity assertion on the literals themselves.
4. The hidden-FILE guard is RETAINED, two-sided: hidden carriers stay silent
   while non-hidden siblings with identical content report.
5. Dir-prune parity is inherited from the provider, two-sided.
6. No-scope pass-through still works and ``misses`` rises by 2 (parent: 0).
7. Traversal order cannot change output, with a control proving the reversing
   wrapper reverses.
8. Source census, two-sided and allowlisted, over a domain asserted non-empty.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from proactive_loop import cli
from proactive_loop.collectors.broken_link import BrokenDocLinkCollector
from proactive_loop.collectors.dir_source import (
    clear_walk_cache,
    walk_cache_stats,
    walk_scope,
)
from proactive_loop.collectors.merge_conflict import MergeConflictCollector
from proactive_loop.models import ContextSignal

WalkTriple = tuple[str, list[str], list[str]]

# Captured ONCE at import, BEFORE any test rebinds ``os.walk``. Patching
# ``os.walk`` is a process-global rebind, so a wrapper that re-looked-up
# ``os.walk`` at call time would recurse into itself (``test_iter175`` idiom).
_REAL_WALK = os.walk

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTORS_DIR = REPO_ROOT / "src" / "proactive_loop" / "collectors"

# The two modules this batch converts. Deliberately NOT added to
# ``test_iter187_behavior.CONVERTED``: that tuple drives an ``_is_hidden``-absent
# assertion which is true for batch 2 and FALSE BY DESIGN here (behavior 4).
BATCH3 = ("merge_conflict.py", "broken_link.py")

# One pruned by name, one pruned as a hidden directory -- both arms of the
# provider's single dir predicate.
PRUNED_DIRS = ("node_modules", ".dotted")

CONFLICT = (
    "def f():\n"
    "<<<<<<< HEAD\n"
    "    return 1\n"
    "=======\n"
    "    return 2\n"
    ">>>>>>> branch\n"
)
BROKEN_DOC = "See [spec](nope/missing.md) for details.\n"
RESOLVING_DOC = "See [sibling](guide.md) which exists.\n"

# ---------------------------------------------------------------------------
# Behavior 3 / 6 / 7 literals -- CAPTURED FROM THE PARENT COMMIT.
#
# Provenance (this is what makes the module a before/after regression oracle
# rather than a restatement of the new code): a detached ``git worktree`` was
# created at HEAD -- the parent commit, i.e. WITHOUT this iteration's change --
# and the fixture below was collected under ``PYTHONPATH=<worktree>/src``. The
# rows pinned here are that PARENT run's output; the same probe under the
# working tree produced them byte-identically. The provider counters DID move
# across the two runs and are asserted in behaviors 1, 2 and 6: parent
# ``hits=3 misses=1`` / two physical walks for the pair / no-scope miss delta 0
# -> this change ``hits=5 misses=1`` / ONE physical walk / miss delta 2.
# ---------------------------------------------------------------------------

Row = tuple[str, str, str, str, str | None, float, Any]

PARENT_MERGE_CONFLICT: list[Row] = [
    ("merge_conflict", "merge_conflict", "conflicted.py: 2 conflict markers", "",
     "conflicted.py", 0.9, None),
    ("merge_conflict", "merge_conflict", "visible.py: 2 conflict markers", "",
     "visible.py", 0.9, None),
]

PARENT_BROKEN_LINK: list[Row] = [
    ("broken_link", "broken_link", "docs/guide.md:1: broken link -> nope/missing.md",
     "See [spec](nope/missing.md) for details.", "docs/guide.md", 0.6, None),
    ("broken_link", "broken_link", "visible.md:1: broken link -> nope/missing.md",
     "See [spec](nope/missing.md) for details.", "visible.md", 0.6, None),
]


@pytest.fixture(autouse=True)
def _isolate_walk_cache() -> Iterator[None]:
    """No test may inherit or leak provider cache entries or hit/miss counters."""
    clear_walk_cache()
    yield
    clear_walk_cache()


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A tmp workspace that trips BOTH collectors and seeds every silent case.

    Hermetic on purpose: the ambient repo tree is never asserted on in this
    module, because a fresh clone (the release re-verification) does not carry
    gitignored local state.
    """
    root = tmp_path / "ws"
    root.mkdir()
    # Positives, one per collector, outside every pruned or hidden path.
    _write(root, "conflicted.py", CONFLICT)
    _write(root, "docs/guide.md", BROKEN_DOC)
    # A RESOLVING relative link: proves the collector is discriminating, not
    # reporting every link it sees.
    _write(root, "docs/ok.md", RESOLVING_DOC)
    # Hidden FILES: silent (behavior 4). ``dir_source`` prunes DIRECTORIES and
    # sorts filenames -- it does not filter hidden files -- so this is the one
    # guard the conversion must not sweep away.
    _write(root, ".hidden.md", BROKEN_DOC)
    _write(root, ".hidden.py", CONFLICT)
    # Non-hidden siblings carrying IDENTICAL content: reported (behavior 4's
    # other arm, without which the silent arm passes on a blind collector).
    _write(root, "visible.md", BROKEN_DOC)
    _write(root, "visible.py", CONFLICT)
    # Pruned directories hold the same two carriers (behavior 5).
    for name in PRUNED_DIRS:
        _write(root, f"{name}/inner.py", CONFLICT)
        _write(root, f"{name}/inner.md", BROKEN_DOC)
    return root


def _projection(root: Path, signals: list[ContextSignal]) -> list[Row]:
    """The full public signal contract, with paths made workspace-relative."""
    rows: list[Row] = []
    for sig in signals:
        raw = None if sig.path is None else str(sig.path)
        if raw is not None and str(root) in raw:
            raw = Path(raw).relative_to(root).as_posix()
        rows.append(
            (sig.source, sig.kind, sig.summary, sig.detail, raw, sig.weight, sig.timestamp)
        )
    return rows


def _conflicts(root: Path) -> list[Row]:
    return _projection(root, MergeConflictCollector().collect(root))


def _links(root: Path) -> list[Row]:
    return _projection(root, BrokenDocLinkCollector().collect(root))


def _counting_walk(calls: list[str]) -> Callable[..., Any]:
    """A pass-through ``os.walk`` that records each invocation's root."""

    def wrapper(top: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(str(top))
        return _REAL_WALK(top, *args, **kwargs)

    return wrapper


def _reversing_walk() -> Callable[..., Any]:
    """``os.walk`` yielding each triple with its entries REVERSED.

    Mutates the real lists IN PLACE and yields those same objects, so a caller's
    in-place ``dirnames[:]`` prune still controls descent -- a wrapper that
    materialised copies would silently disable pruning and test nothing.
    """

    def wrapper(top: Any, *args: Any, **kwargs: Any) -> Iterator[WalkTriple]:
        for dirpath, dirnames, filenames in _REAL_WALK(top, *args, **kwargs):
            dirnames.reverse()
            filenames.reverse()
            yield dirpath, dirnames, filenames

    return wrapper


def _source(name: str) -> str:
    return (COLLECTORS_DIR / name).read_text(encoding="utf-8")


# ===========================================================================
# Behavior 1 -- SIX collectors now share ONE traversal per scan
# ===========================================================================


class TestBehavior1SharedTraversalCounters:
    def test_one_collect_reports_five_hits_and_one_miss(self, workspace: Path) -> None:
        clear_walk_cache()
        cli._collect(workspace)

        stats = walk_cache_stats()
        assert (stats["hits"], stats["misses"]) == (5, 1), (
            "one _collect must serve SIX collectors from ONE traversal: expected "
            f"hits=5 misses=1 (parent commit measured hits=3 misses=1); got {stats!r}"
        )

    def test_scope_leaves_no_cached_dirents_behind(self, workspace: Path) -> None:
        clear_walk_cache()
        cli._collect(workspace)

        stats = walk_cache_stats()
        assert (stats["entries"], stats["dirs"]) == (0, 0), (
            f"the per-scan cache must not outlive the scope; got {stats!r}"
        )


# ===========================================================================
# Behavior 2 -- the pair performs exactly ONE physical os.walk
# ===========================================================================


class TestBehavior2OnePhysicalWalkForThePair:
    def test_pair_inside_one_scope_walks_once(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(os, "walk", _counting_walk(calls))

        with walk_scope():
            conflicts = MergeConflictCollector().collect(workspace)
            links = BrokenDocLinkCollector().collect(workspace)

        assert calls == [str(workspace)], (
            "merge_conflict + broken_link inside ONE scope must perform exactly one "
            f"physical os.walk rooted at the workspace (it was two); got {calls!r}"
        )
        # Anti-vacuity: one walk is only meaningful if both collectors reported.
        assert conflicts and links, (
            "fixture regression -- both collectors must report signals here; got "
            f"merge_conflict={conflicts!r} broken_link={links!r}"
        )

    def test_each_collector_alone_inside_a_scope_walks_once(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for collector in (MergeConflictCollector(), BrokenDocLinkCollector()):
            calls: list[str] = []
            monkeypatch.setattr(os, "walk", _counting_walk(calls))
            clear_walk_cache()
            with walk_scope():
                signals = collector.collect(workspace)
            assert calls == [str(workspace)], (
                f"{type(collector).__name__} must walk exactly once inside a scope; "
                f"got {calls!r}"
            )
            assert signals, (
                f"{type(collector).__name__} reported nothing -- a collector that "
                "sees no files also walks once, so this arm would be vacuous"
            )


# ===========================================================================
# Behavior 3 -- signals are UNCHANGED (literals captured from the parent commit)
# ===========================================================================


class TestBehavior3SignalsUnchanged:
    def test_merge_conflict_signals_match_the_parent_commit(self, workspace: Path) -> None:
        with walk_scope():
            rows = _conflicts(workspace)
        assert rows == PARENT_MERGE_CONFLICT, (
            "merge_conflict's signals must be field-for-field identical to the parent "
            f"commit's output, INCLUDING order; got {rows!r}"
        )

    def test_broken_link_signals_match_the_parent_commit(self, workspace: Path) -> None:
        with walk_scope():
            rows = _links(workspace)
        assert rows == PARENT_BROKEN_LINK, (
            "broken_link's signals must be field-for-field identical to the parent "
            f"commit's output, INCLUDING the line/column detail; got {rows!r}"
        )

    def test_pinned_literals_are_not_vacuous(self) -> None:
        # A pinned-literal oracle is worthless if the literals are empty: an
        # emitting-nothing collector would satisfy an empty pin on both sides.
        assert len(PARENT_MERGE_CONFLICT) == 2
        assert len(PARENT_BROKEN_LINK) == 2
        for row in PARENT_MERGE_CONFLICT:
            assert row[1] == "merge_conflict" and "conflict markers" in row[2]
        for row in PARENT_BROKEN_LINK:
            assert row[1] == "broken_link" and "broken link -> nope/missing.md" in row[2]
            assert ":1:" in row[2], "the summary must carry the 1-based line number"

    def test_a_resolving_relative_link_is_still_silent(self, workspace: Path) -> None:
        # Discrimination check: docs/ok.md links to a target that EXISTS, so the
        # pinned rows above are a filter's output, not "every link in the tree".
        with walk_scope():
            reported = {row[4] for row in _links(workspace)}
        assert "docs/ok.md" not in reported, (
            f"a resolving relative link must never be reported; got {reported!r}"
        )


# ===========================================================================
# Behavior 4 -- the hidden-FILE filter is RETAINED, two-sided
# ===========================================================================


class TestBehavior4HiddenFileGuardRetained:
    def test_hidden_carriers_produce_no_signal(self, workspace: Path) -> None:
        with walk_scope():
            reported = {row[4] for row in _conflicts(workspace) + _links(workspace)}

        for hidden in (".hidden.md", ".hidden.py"):
            assert hidden not in reported, (
                f"{hidden} is a hidden FILE and must stay silent: dir_source prunes "
                "directories and sorts filenames only, so each converted collector "
                f"must keep its own _is_hidden(fname) guard; got {reported!r}"
            )

    def test_the_same_content_in_non_hidden_siblings_does_report(
        self, workspace: Path
    ) -> None:
        # Anti-vacuity for the arm above: prove the hidden files carry content the
        # collectors DO report when the leading dot is removed.
        with walk_scope():
            reported = {row[4] for row in _conflicts(workspace) + _links(workspace)}

        assert {"visible.md", "visible.py"} <= reported, (
            "visible.md/visible.py carry byte-identical content to the hidden pair "
            f"and must both be reported, or behavior 4 is vacuous; got {reported!r}"
        )

    def test_both_modules_still_name_the_hidden_file_guard(self) -> None:
        for name in BATCH3:
            text = _source(name)
            assert text.count("_is_hidden") >= 1, (
                f"{name} must still name _is_hidden -- the conversion deletes the "
                "DIRECTORY prune, never the hidden-FILE guard"
            )


# ===========================================================================
# Behavior 5 -- dir-prune parity is INHERITED from the provider
# ===========================================================================


class TestBehavior5PruneParityInherited:
    def test_no_signal_comes_from_any_pruned_directory(self, workspace: Path) -> None:
        with walk_scope():
            rows = _conflicts(workspace) + _links(workspace)

        for name in PRUNED_DIRS:
            offenders = [
                row for row in rows
                if row[4] is not None and row[4].split("/")[0] == name
            ]
            assert offenders == [], (
                f"{name}/ must be pruned by the shared provider, which now owns the "
                f"package dir-prune policy; got {offenders!r}"
            )

    def test_the_same_files_outside_a_pruned_dir_ARE_reported(
        self, workspace: Path
    ) -> None:
        # Anti-vacuity for the arm above: identical carriers, unpruned location.
        _write(workspace, "keepdir/inner.py", CONFLICT)
        _write(workspace, "keepdir/inner.md", BROKEN_DOC)

        with walk_scope():
            reported = {row[4] for row in _conflicts(workspace) + _links(workspace)}

        assert {"keepdir/inner.py", "keepdir/inner.md"} <= reported, (
            "the same carriers outside a pruned directory must both be reported, or "
            f"the prune assertion passes on a blind collector; got {reported!r}"
        )

    def test_neither_module_still_spells_a_prune_expression(self) -> None:
        for name in BATCH3:
            text = _source(name)
            assert "dirnames[:]" not in text, (
                f"{name} must no longer re-implement the in-place dirnames prune"
            )


# ===========================================================================
# Behavior 6 -- no-scope pass-through still works (deliberate degradation)
# ===========================================================================


class TestBehavior6NoScopePassThrough:
    def test_signals_are_identical_with_no_scope_active(self, workspace: Path) -> None:
        assert _conflicts(workspace) == PARENT_MERGE_CONFLICT, (
            "merge_conflict must work with NO scope active; got "
            f"{_conflicts(workspace)!r}"
        )
        assert _links(workspace) == PARENT_BROKEN_LINK, (
            f"broken_link must work with NO scope active; got {_links(workspace)!r}"
        )

    def test_misses_increase_when_no_scope_is_active(self, workspace: Path) -> None:
        clear_walk_cache()
        before = walk_cache_stats()["misses"]

        MergeConflictCollector().collect(workspace)
        BrokenDocLinkCollector().collect(workspace)

        after = walk_cache_stats()["misses"]
        assert after - before == 2, (
            "with no scope active the provider must degrade to a direct walk per "
            "call, so misses must rise by 2 (parent commit: 0, these collectors did "
            f"not touch the provider at all); got {after - before}"
        )


# ===========================================================================
# Behavior 7 -- traversal order cannot change output, adversarially
# ===========================================================================


class TestBehavior7ReversedTraversalOrder:
    def test_reversed_order_inside_a_scope_changes_nothing(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "walk", _reversing_walk())

        with walk_scope():
            conflicts = _conflicts(workspace)
            links = _links(workspace)

        assert conflicts == PARENT_MERGE_CONFLICT, (
            f"merge_conflict must be independent of os.walk order; got {conflicts!r}"
        )
        assert links == PARENT_BROKEN_LINK, (
            f"broken_link must be independent of os.walk order; got {links!r}"
        )

    def test_reversed_order_with_no_scope_changes_nothing(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "walk", _reversing_walk())

        assert _conflicts(workspace) == PARENT_MERGE_CONFLICT
        assert _links(workspace) == PARENT_BROKEN_LINK

    def test_the_reversing_wrapper_really_reverses(self, workspace: Path) -> None:
        # Control assertion: an order-independence proof is worthless if the
        # wrapper is a no-op.
        plain = [
            (dirpath, list(dirnames), list(filenames))
            for dirpath, dirnames, filenames in _REAL_WALK(workspace / "docs")
        ]
        flipped = [
            (dirpath, list(dirnames), list(filenames))
            for dirpath, dirnames, filenames in _reversing_walk()(workspace / "docs")
        ]
        assert [t[2] for t in plain] != [[]], "fixture regression: docs/ must hold files"
        assert len(plain[0][2]) >= 2, (
            "the control needs at least two filenames or reversal is a no-op; got "
            f"{plain[0][2]!r}"
        )
        assert [t[2] for t in flipped] == [list(reversed(t[2])) for t in plain], (
            "the reversing wrapper must actually reverse each filenames list"
        )


# ===========================================================================
# Behavior 8 -- source census, two-sided and allowlisted
# ===========================================================================


class TestBehavior8SourceCensus:
    def test_converted_modules_no_longer_call_os_walk_or_import_os(self) -> None:
        for name in BATCH3:
            text = _source(name)
            assert text.count("os.walk(") == 0, (
                f"{name} must not call os.walk( any more; "
                f"found {text.count('os.walk(')} occurrence(s)"
            )
            assert text.count("import os") == 0, (
                f"{name} must not import os any more -- the shared provider owns the "
                f"traversal; found {text.count('import os')} occurrence(s)"
            )

    def test_converted_modules_no_longer_name_the_prune_symbol(self) -> None:
        for name in BATCH3:
            text = _source(name)
            assert text.count("_SKIP_DIRS") == 0, (
                f"{name} must not mention _SKIP_DIRS any more (import or prose); "
                f"found {text.count('_SKIP_DIRS')} occurrence(s)"
            )

    def test_converted_modules_read_the_shared_provider(self) -> None:
        # The positive side of the census: deleting a walk without adopting the
        # provider would satisfy every "zero occurrences" assertion above.
        for name in BATCH3:
            text = _source(name)
            assert "dir_source" in text, (
                f"{name} must name dir_source -- the zero-occurrence assertions "
                "above are also satisfied by a collector that walks nothing"
            )

    def test_exactly_six_collector_modules_still_walk(self) -> None:
        modules = sorted(p.name for p in COLLECTORS_DIR.glob("*.py"))
        assert len(modules) >= 15, (
            "census domain regression -- an empty or truncated glob reads as a pass; "
            f"expected the collectors package, got {modules!r}"
        )
        walkers = sorted(
            name for name in modules
            if "os.walk(" in (COLLECTORS_DIR / name).read_text(encoding="utf-8")
        )
        assert walkers == [
            "dir_source.py",
            "filesystem.py",
            "large_file.py",
            "notes.py",
            "syntax_error.py",
            "todos.py",
        ], (
            "exactly 6 collector modules may still own an os.walk (was 8 before this "
            "batch converted merge_conflict + broken_link: dir_source and filesystem "
            "keep theirs by design, plus the four collectors row #210 leaves for "
            "batch 4). A later batch that converts one of these must update this "
            f"iteration-scoped pin. Got {walkers!r}"
        )
        # A second, named-symbol view of the same claim, so a regression says WHICH
        # module came back rather than just showing a changed list.
        for converted in ("secret_file.py", "test_posture.py", *BATCH3):
            assert converted not in walkers, (
                f"{converted} was converted to dir_source.walk by row #210's "
                "program; it must never own an os.walk again"
            )
