"""Black-box behavior tests for state-dir iteration 171 (ships as ``factory iter
175``): ONE shared, scan-scoped directory-walk provider that performs the pruned
``os.walk`` once per root and serves the cached dirent listing to its callers,
landed with ``DependencyCollector`` and ``LockfileDriftCollector`` converted onto
it.

The perception layer used to re-walk the user's workspace once per collector, so
the cost scaled with the SIZE of the project rather than its content and ``watch``
re-paid it every tick.  This iteration removes the redundant TRAVERSAL for the
first two callers; content decode was already de-duplicated by
``collectors/text_source.py``.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. The provider yields the PRUNED tree -- no triple at or under a ``_SKIP_DIRS``
   directory or a hidden directory, and every returned ``dirnames`` list is
   already pruned by exactly ``not _is_hidden(d) and d not in _SKIP_DIRS``.
2. ONE traversal per root per scope, and the counters agree: five ``walk(root)``
   calls in one scope -> exactly 1 ``os.walk`` invocation, five equal results,
   and ``walk_cache_stats()`` reporting exactly 1 miss and 4 hits.
3. Distinct roots are cached independently -> exactly 2 invocations, and each
   result contains only its own tree's paths.
4. The cache never outlives its scope: zero cached entries after the block, a
   NEW invocation in a second scope, and a file created BETWEEN the two scopes is
   visible in the second result (load-bearing -- a ``watch`` tick must never be
   served a stale dirent listing).
5. The two converted collectors share ONE traversal inside a scope (it was 2),
   and with NO scope active they still work: 2 invocations and correct signals,
   i.e. the provider degrades to a direct walk rather than raising.
6. Signal output is UNCHANGED -- the equivalence oracle.  Exact count, ``kind``,
   ordering, ``source``, ``summary`` and ``path`` payload are asserted as
   literals, so a traversal change that alters what a collector sees fails here
   even though both collectors stay silent about their internals.
7. Determinism: ``walk(root)`` is a total function of the tree (sorted), never of
   platform ``os.walk`` enumeration order, and two calls in different scopes over
   an unchanged tree return identical content.

ISOLATION CONTRACT honored: every expectation below comes from this iteration's
``pm.md`` "Expected Behaviors", from RUNNING the shipped public interface, and
from the conventions of existing modules under ``tests/``
(``tests/test_iter141_behavior.py`` for the two collectors' fixture shape and
explicit ``os.utime`` mtimes, ``tests/test_iter70_behavior.py`` for the
module-level ``os`` patch).  **No file under ``src/`` was read, no engineer or
reviewer note was opened, and no ``git diff`` was consulted.**

Fully offline and deterministic: ``tmp_path`` trees only (never the ambient repo
tree, which a fresh clone would not carry), no network, no subprocess, no
``git``, and NO wall-clock assertion anywhere -- traversal COUNTS are the
regime-free oracle, so the suite behaves the same on a loaded box.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from proactive_loop.collectors.dependencies import DependencyCollector
from proactive_loop.collectors.dir_source import (
    clear_walk_cache,
    walk,
    walk_cache_stats,
    walk_scope,
)
from proactive_loop.collectors.filesystem import _SKIP_DIRS, _is_hidden
from proactive_loop.collectors.lockfile_drift import LockfileDriftCollector

WalkTriple = tuple[str, list[str], list[str]]

# Captured ONCE, at import, BEFORE any test rebinds ``os.walk``.  Patching
# ``os.walk`` is a PROCESS-GLOBAL rebind (the collectors package shares the one
# ``os`` module object), so a wrapper that re-looks-up ``os.walk`` at call time
# would recurse into itself.  Every wrapper below closes over this name instead.
_REAL_WALK = os.walk


@pytest.fixture(autouse=True)
def _isolate_walk_cache() -> Iterator[None]:
    """No test may inherit or leak provider cache entries or hit/miss counters."""
    clear_walk_cache()
    yield
    clear_walk_cache()


def _counting_walk(calls: list[str]) -> Callable[..., Any]:
    """A pass-through ``os.walk`` that records each invocation's root."""

    def wrapper(top: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(str(top))
        return _REAL_WALK(top, *args, **kwargs)

    return wrapper


def _rel_dirpaths(root: Path, triples: list[WalkTriple]) -> list[str]:
    return [Path(dirpath).relative_to(root).as_posix() for dirpath, _, _ in triples]


# ---------------------------------------------------------------------------
# Behavior 1: the provider yields the pruned tree
# ---------------------------------------------------------------------------


@pytest.fixture()
def pruning_tree(tmp_path: Path) -> Path:
    """A root holding a ``_SKIP_DIRS`` dir, a hidden dir, and an ordinary dir."""
    root = tmp_path / "ws"
    skipped = sorted(_SKIP_DIRS)[0]
    (root / skipped / "nested").mkdir(parents=True)
    (root / skipped / "nested" / "junk.py").write_text("1\n", encoding="utf-8")
    (root / ".hidden" / "nested").mkdir(parents=True)
    (root / ".hidden" / "nested" / "junk.py").write_text("1\n", encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "a.py").write_text("1\n", encoding="utf-8")
    (root / "top.py").write_text("1\n", encoding="utf-8")
    return root


class TestBehavior1PrunedTree:
    def test_skip_dirs_is_a_real_non_empty_prune_set(self) -> None:
        # Anti-vacuity: behavior 1 is meaningless if the shared prune set is
        # empty or if the hidden predicate does not classify a dotted name.
        assert _SKIP_DIRS, "the shared _SKIP_DIRS prune set must be non-empty"
        assert _is_hidden(".hidden") is True
        assert _is_hidden("pkg") is False

    def test_returns_root_and_ordinary_dir_only(self, pruning_tree: Path) -> None:
        with walk_scope():
            triples = walk(pruning_tree)
        assert _rel_dirpaths(pruning_tree, triples) == [".", "pkg"], (
            "walk() must yield the root and the ordinary directory and nothing "
            f"else; got {_rel_dirpaths(pruning_tree, triples)}"
        )

    def test_no_triple_at_or_under_a_skipped_or_hidden_directory(
        self, pruning_tree: Path
    ) -> None:
        with walk_scope():
            triples = walk(pruning_tree)
        for dirpath, _, _ in triples:
            parts = Path(dirpath).relative_to(pruning_tree).parts
            offenders = [p for p in parts if _is_hidden(p) or p in _SKIP_DIRS]
            assert not offenders, (
                f"{dirpath!r} is at or under a pruned directory {offenders!r}"
            )

    def test_every_returned_dirnames_list_is_already_pruned(
        self, pruning_tree: Path
    ) -> None:
        with walk_scope():
            triples = walk(pruning_tree)
        for dirpath, dirnames, _ in triples:
            kept = [d for d in dirnames if not _is_hidden(d) and d not in _SKIP_DIRS]
            assert dirnames == kept, (
                f"dirnames for {dirpath!r} must already be pruned by exactly "
                f"'not _is_hidden(d) and d not in _SKIP_DIRS'; got {dirnames!r}"
            )

    def test_ordinary_files_survive_the_prune(self, pruning_tree: Path) -> None:
        with walk_scope():
            triples = walk(pruning_tree)
        by_dir = {
            Path(dirpath).relative_to(pruning_tree).as_posix(): sorted(filenames)
            for dirpath, _, filenames in triples
        }
        assert by_dir["."] == ["top.py"]
        assert by_dir["pkg"] == ["a.py"]


# ---------------------------------------------------------------------------
# Behavior 2: one traversal per root per scope, and the counters agree
# ---------------------------------------------------------------------------


@pytest.fixture()
def small_tree(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "a.py").write_text("1\n", encoding="utf-8")
    return root


class TestBehavior2OneTraversalPerRootPerScope:
    def test_five_calls_one_traversal_five_equal_results(
        self, small_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(os, "walk", _counting_walk(calls))
        with walk_scope():
            results = [walk(small_tree) for _ in range(5)]
        assert len(calls) == 1, (
            f"five walk() calls on one root in one scope must traverse ONCE; "
            f"os.walk was invoked {len(calls)} time(s) on {calls!r}"
        )
        assert all(r == results[0] for r in results), (
            "every cached result must compare equal to the first"
        )
        assert results[0], "anti-vacuity: the traversal must return at least one triple"

    def test_stats_report_one_miss_and_four_hits(self, small_tree: Path) -> None:
        with walk_scope():
            for _ in range(5):
                walk(small_tree)
            stats = walk_cache_stats()
        assert stats["misses"] == 1, f"expected exactly 1 miss, got {stats!r}"
        assert stats["hits"] == 4, f"expected exactly 4 hits, got {stats!r}"


# ---------------------------------------------------------------------------
# Behavior 3: distinct roots are cached independently
# ---------------------------------------------------------------------------


class TestBehavior3DistinctRootsCachedIndependently:
    def test_two_roots_two_traversals_no_cross_contamination(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root_a = tmp_path / "alpha_ws"
        (root_a / "only_a").mkdir(parents=True)
        (root_a / "only_a" / "a.py").write_text("1\n", encoding="utf-8")
        root_b = tmp_path / "bravo_ws"
        (root_b / "only_b").mkdir(parents=True)
        (root_b / "only_b" / "b.py").write_text("1\n", encoding="utf-8")

        calls: list[str] = []
        monkeypatch.setattr(os, "walk", _counting_walk(calls))
        with walk_scope():
            result_a = walk(root_a)
            result_b = walk(root_b)
            stats = walk_cache_stats()

        assert len(calls) == 2, (
            f"two distinct roots must traverse twice; got {len(calls)}: {calls!r}"
        )
        assert stats["entries"] == 2, f"expected 2 cached entries, got {stats!r}"
        assert _rel_dirpaths(root_a, result_a) == [".", "only_a"]
        assert _rel_dirpaths(root_b, result_b) == [".", "only_b"]
        assert not [t for t in result_a if root_b.name in t[0]], (
            "root_a's result leaked root_b's paths"
        )
        assert not [t for t in result_b if root_a.name in t[0]], (
            "root_b's result leaked root_a's paths"
        )


# ---------------------------------------------------------------------------
# Behavior 4: the cache never outlives its scope
# ---------------------------------------------------------------------------


class TestBehavior4CacheNeverOutlivesItsScope:
    def test_no_entries_remain_after_the_block_and_a_second_scope_re_walks(
        self, small_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(os, "walk", _counting_walk(calls))

        with walk_scope():
            first = walk(small_tree)
        assert walk_cache_stats()["entries"] == 0, (
            "the scope-exit must leave ZERO cached entries; got "
            f"{walk_cache_stats()!r}"
        )
        assert len(calls) == 1

        # A file appearing between two watch ticks MUST be visible to the second.
        (small_tree / "pkg" / "appeared_later.py").write_text("1\n", encoding="utf-8")

        with walk_scope():
            second = walk(small_tree)
        assert len(calls) == 2, (
            "a second scope must record a NEW traversal, never reuse the first "
            f"scope's listing; os.walk invocations: {calls!r}"
        )

        def files_in(triples: list[WalkTriple], rel: str) -> list[str]:
            for dirpath, _, filenames in triples:
                if Path(dirpath).relative_to(small_tree).as_posix() == rel:
                    return sorted(filenames)
            raise AssertionError(f"{rel!r} missing from {triples!r}")

        assert files_in(first, "pkg") == ["a.py"]
        assert files_in(second, "pkg") == ["a.py", "appeared_later.py"], (
            "the second scope was served a STALE dirent listing"
        )


# ---------------------------------------------------------------------------
# Behaviors 5 + 6: the two converted collectors -- shared traversal, unchanged
# signals, and a working no-scope fallback
# ---------------------------------------------------------------------------


@pytest.fixture()
def collector_tree(tmp_path: Path) -> Path:
    """A ``pyproject.toml`` + nested ``requirements.txt`` (dependencies) whose
    manifest has NO lockfile (drift)."""
    root = tmp_path / "ws"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "requirements.txt").write_text("pydantic>=2\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    # Explicit mtimes: drift must not depend on write ORDER (see iter141).
    os.utime(root / "pyproject.toml", (2_000_000, 2_000_000))
    return root


def _run_both(root: Path) -> tuple[list[Any], list[Any]]:
    return DependencyCollector().collect(root), LockfileDriftCollector().collect(root)


class TestBehavior5ConvertedCollectorsShareOneTraversal:
    def test_inside_one_scope_the_pair_traverses_once(
        self, collector_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(os, "walk", _counting_walk(calls))
        with walk_scope():
            deps, drift = _run_both(collector_tree)
        assert len(calls) == 1, (
            "the two converted collectors must share ONE traversal inside a "
            f"scope (it was 2 before this iteration); got {len(calls)}: {calls!r}"
        )
        # Anti-vacuity: a shared walk that returns nothing would also count 1.
        assert deps and drift, "both collectors must still emit signals"

    def test_without_a_scope_each_walks_directly_and_still_works(
        self, collector_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(os, "walk", _counting_walk(calls))
        deps, drift = _run_both(collector_tree)  # no walk_scope() active
        assert len(calls) == 2, (
            "with no scope active the provider must degrade to a DIRECT walk "
            f"per caller, not raise or share; got {len(calls)}: {calls!r}"
        )
        assert [s.kind for s in deps] == ["dependency", "dependency"]
        assert [s.kind for s in drift] == ["lockfile_drift"]

    def test_scoped_and_unscoped_runs_produce_identical_signals(
        self, collector_tree: Path
    ) -> None:
        unscoped_deps, unscoped_drift = _run_both(collector_tree)
        with walk_scope():
            scoped_deps, scoped_drift = _run_both(collector_tree)

        def shape(signals: list[Any]) -> list[tuple[str, str, str, str]]:
            return [(s.source, s.kind, s.summary, s.path) for s in signals]

        assert shape(scoped_deps) == shape(unscoped_deps)
        assert shape(scoped_drift) == shape(unscoped_drift)


class TestBehavior6SignalOutputUnchanged:
    def test_dependency_signals_are_exactly_as_before(
        self, collector_tree: Path
    ) -> None:
        with walk_scope():
            deps, _ = _run_both(collector_tree)
        assert [(s.source, s.kind, s.summary) for s in deps] == [
            ("dependencies", "dependency", "Python: pkg/requirements.txt (1 deps)"),
            ("dependencies", "dependency", "Python: pyproject.toml (0 deps)"),
        ], f"dependency signals changed: {[s.model_dump() for s in deps]!r}"
        assert [Path(s.path).relative_to(collector_tree).as_posix() for s in deps] == [
            "pkg/requirements.txt",
            "pyproject.toml",
        ]

    def test_lockfile_drift_signals_are_exactly_as_before(
        self, collector_tree: Path
    ) -> None:
        with walk_scope():
            _, drift = _run_both(collector_tree)
        assert [(s.source, s.kind, s.summary) for s in drift] == [
            ("lockfile_drift", "lockfile_drift", "pyproject.toml: manifest has no lockfile"),
        ], f"lockfile-drift signals changed: {[s.model_dump() for s in drift]!r}"
        assert [
            Path(s.path).relative_to(collector_tree).as_posix() for s in drift
        ] == ["pyproject.toml"]

    def test_a_present_lockfile_still_silences_drift(self, collector_tree: Path) -> None:
        # Control in the other direction: the collector is not simply always-on.
        (collector_tree / "uv.lock").write_text("# lock\n", encoding="utf-8")
        os.utime(collector_tree / "uv.lock", (3_000_000, 3_000_000))
        with walk_scope():
            _, drift = _run_both(collector_tree)
        assert [s.summary for s in drift] == [], (
            f"a fresh lockfile must silence drift; got {[s.summary for s in drift]!r}"
        )

    def test_collectors_see_a_pruned_tree_through_the_provider(
        self, collector_tree: Path
    ) -> None:
        # A manifest hidden inside a pruned directory must stay invisible, which
        # is what makes the shared traversal equivalent to the old private ones.
        skipped = sorted(_SKIP_DIRS)[0]
        (collector_tree / skipped).mkdir()
        (collector_tree / skipped / "requirements.txt").write_text(
            "flask\n", encoding="utf-8"
        )
        with walk_scope():
            deps, _ = _run_both(collector_tree)
        assert not [s for s in deps if skipped in s.path], (
            f"a manifest under {skipped!r} must be pruned away; got "
            f"{[s.path for s in deps]!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 7: determinism -- order is a total function of the tree
# ---------------------------------------------------------------------------


class TestBehavior7Determinism:
    @staticmethod
    def _tree(root: Path) -> Path:
        for name in ("zeta", "alpha", "mid"):
            (root / name).mkdir(parents=True)
            for filename in ("z.py", "a.py"):
                (root / name / filename).write_text("1\n", encoding="utf-8")
        (root / "mid" / "deep").mkdir()
        (root / "mid" / "deep" / "m.py").write_text("1\n", encoding="utf-8")
        return root

    def test_results_are_sorted_and_not_platform_enumeration_order(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = self._tree(tmp_path / "ws")
        with walk_scope():
            natural = walk(root)
        assert _rel_dirpaths(root, natural) == [".", "alpha", "mid", "mid/deep", "zeta"]
        assert natural[0][1] == ["alpha", "mid", "zeta"], (
            f"dirnames must be sorted; got {natural[0][1]!r}"
        )

        def reversing(top: Any, *args: Any, **kwargs: Any) -> Any:
            # Hand back the SAME tree in the worst possible order.  There is no
            # pruned directory in this fixture, so materializing the generator
            # cannot change WHICH directories are reachable.
            triples = [
                (dirpath, list(dirnames), list(filenames))
                for dirpath, dirnames, filenames in _REAL_WALK(top, *args, **kwargs)
            ]
            for _, dirnames, filenames in triples:
                dirnames.sort(reverse=True)
                filenames.sort(reverse=True)
            return iter(list(reversed(triples)))

        clear_walk_cache()
        monkeypatch.setattr(os, "walk", reversing)
        with walk_scope():
            shuffled = walk(root)
        assert shuffled == natural, (
            "walk() must be a total function of the TREE, not of os.walk "
            f"enumeration order;\n natural={_rel_dirpaths(root, natural)!r}\n"
            f"shuffled={_rel_dirpaths(root, shuffled)!r}"
        )

    def test_two_scopes_over_an_unchanged_tree_agree(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path / "ws")
        with walk_scope():
            first = walk(root)
        with walk_scope():
            second = walk(root)
        assert first == second
