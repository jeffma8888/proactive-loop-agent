"""Black-box oracle for factory iteration 187 (state dir ``iter-183``).

Feature under test: ``secret_file`` and ``test_posture`` stop running their own
``os.walk`` of the workspace and read the shared per-scan dirent listing from
``collectors/dir_source``, taking the number of collectors served by the one
shared traversal from 2 to 4.

MODULE NAME (deliberate deviation from this iteration's spec, recorded because it
is a real defect this stage caught). ``pm.md`` names the new module
``tests/test_iter183_behavior.py``. That file ALREADY EXISTS and is TRACKED -- it
is the shipped oracle for factory iteration 183 (the README <-> Makefile
``.PHONY`` documentation binding). This repo names behavior modules by the
FACTORY iteration number, which runs ahead of the state-dir counter; state dir
183 ships as factory **187**, so this file is 187. Writing the spec's filename
would DESTROY a shipped oracle, so the number, not the spec string, wins.

ISOLATION CONTRACT (honored, no exceptions). Every assertion below is derived
from this iteration's ``pm.md`` "Expected Behaviors", from the conventions of
existing modules under ``tests/`` (``tests/test_iter175_behavior.py`` for the
provider API, the autouse cache-isolation fixture and the counting-``os.walk``
wrapper), and from RUNNING the shipped public interface. **No file under ``src/``
was read as source text, no engineer or reviewer note was opened, and no ``git
diff`` was consulted.** The census in Behavior 7 measures tracked source files
mechanically (a token count over bytes) rather than reading them for design.

Offline and deterministic: ``tmp_path`` fixture trees only, no network, no
subprocess, no wall-clock assertion. Traversal COUNTS are the regime-free
oracle. Nothing asserts on docstring or help-text indentation, so the 3.12/3.13
matrix legs cannot diverge here.

Coverage (numbered to match the spec's Expected Behaviors):

1. One ``cli._collect`` over the repo root reports ``hits == 3`` / ``misses == 1``
   from ``walk_cache_stats()`` (baseline before this change: 1 hit, 1 miss).
2. Inside ONE ``walk_scope()``, the two collectors together perform exactly ONE
   physical ``os.walk`` rooted at the shared root (it was two).
3. Signals are unchanged, pinned as literals captured from the PARENT commit.
4. Prune parity is inherited from the provider, not re-implemented.
5. With no scope active both collectors still work and the provider degrades to a
   direct walk (misses increase).
6. Traversal-order independence: with ``os.walk`` yielding reversed directory
   entries, both collectors return byte-identical signals.
7. Source census: neither module names ``os.walk(``, ``_SKIP_DIRS`` or
   ``_is_hidden``, and exactly 8 files under ``collectors/`` still call
   ``os.walk(``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from proactive_loop import cli
from proactive_loop.collectors.dir_source import (
    clear_walk_cache,
    walk_cache_stats,
    walk_scope,
)
from proactive_loop.collectors.secret_file import SecretFileCollector

# Aliased so the module-level name is NOT ``Test*``: pytest would otherwise try
# to collect the collector class itself (same trick as ``test_iter16_*``).
from proactive_loop.collectors.test_posture import TestPostureCollector as PostureCollector
from proactive_loop.models import ContextSignal

WalkTriple = tuple[str, list[str], list[str]]

# Captured ONCE at import, BEFORE any test rebinds ``os.walk``. Patching
# ``os.walk`` is a process-global rebind, so a wrapper that re-looked-up
# ``os.walk`` at call time would recurse into itself (``test_iter175`` idiom).
_REAL_WALK = os.walk

REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTORS_DIR = REPO_ROOT / "src" / "proactive_loop" / "collectors"
CONVERTED = ("secret_file.py", "test_posture.py")

# The directories the shared provider prunes, each seeded in the fixture with a
# file BOTH collectors would otherwise report.
PRUNED_DIRS = ("node_modules", "dist", "__pycache__", ".git", ".secrets")

# ---------------------------------------------------------------------------
# Behavior 3 / 5 / 6 literals -- CAPTURED FROM THE PARENT COMMIT.
#
# Provenance (this is what makes the module a before/after regression oracle
# rather than a restatement of the new code): a detached ``git worktree`` was
# created at HEAD (the parent commit, i.e. WITHOUT this iteration's change) and
# the fixture below was collected under ``PYTHONPATH=<worktree>/src``. The rows
# pinned here are that PARENT run's output, and the same script under the
# working tree produced them byte-identically. The provider counters differed
# across the two runs and are asserted in Behavior 1: parent
# ``{"hits": 1, "misses": 1}`` -> this change ``{"hits": 3, "misses": 1}``.
# ---------------------------------------------------------------------------

PARENT_SECRET_FILE: list[tuple[str, str, str, str, str | None, float, Any]] = [
    (
        "secret_file",
        "secret_file",
        "pkg/sub/.env.local: secret-shaped file",
        "",
        "pkg/sub/.env.local",
        0.85,
        None,
    ),
]

PARENT_TEST_POSTURE: list[tuple[str, str, str, str, str | None, float, Any]] = [
    ("test_posture", "test_posture", "api: 1 src, 0 test files (untested)", "", "api", 0.7, None),
    ("test_posture", "test_posture", "svc: 1 src, 1 test files", "", "svc", 0.4, None),
]


@pytest.fixture(autouse=True)
def _isolate_walk_cache() -> Iterator[None]:
    """No test may inherit or leak provider cache entries or hit/miss counters."""
    clear_walk_cache()
    yield
    clear_walk_cache()


def _write(root: Path, rel: str, content: str = "x = 1\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A tmp workspace that trips BOTH collectors and seeds every pruned dir.

    Hermetic on purpose: the ambient repo tree is not asserted on anywhere in
    this module, because a fresh clone (the release re-verification) does not
    carry gitignored local state.
    """
    root = tmp_path / "ws"
    root.mkdir()
    # secret_file positive case (a hidden FILE, deliberately kept)
    _write(root, "pkg/sub/.env.local", "TOKEN=abc\n")
    # test_posture positive cases: one untested project, one tested project
    _write(root, "api/server.py")
    _write(root, "svc/app.py")
    _write(root, "svc/test_app.py")
    # every pruned directory holds a file EACH collector would otherwise report
    for name in PRUNED_DIRS:
        _write(root, f"{name}/.env", "TOKEN=zzz\n")
        _write(root, f"{name}/mod.py")
    return root


def _projection(
    root: Path, signals: list[ContextSignal]
) -> list[tuple[str, str, str, str, str | None, float, Any]]:
    """The full public signal contract, with paths made workspace-relative."""
    rows: list[tuple[str, str, str, str, str | None, float, Any]] = []
    for sig in signals:
        raw = None if sig.path is None else str(sig.path)
        if raw is not None and str(root) in raw:
            raw = Path(raw).relative_to(root).as_posix()
        rows.append(
            (sig.source, sig.kind, sig.summary, sig.detail, raw, sig.weight, sig.timestamp)
        )
    return rows


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
# Behavior 1 -- four collectors now share ONE traversal per scan
# ===========================================================================


class TestBehavior1SharedTraversalCounters:
    def test_one_collect_reports_three_hits_and_one_miss(self, workspace: Path) -> None:
        clear_walk_cache()
        cli._collect(workspace)

        stats = walk_cache_stats()
        assert (stats["hits"], stats["misses"]) == (3, 1), (
            "one _collect must serve FOUR collectors from ONE traversal: expected "
            f"hits=3 misses=1 (parent commit measured hits=1 misses=1); got {stats!r}"
        )

    def test_scope_leaves_no_cached_dirents_behind(self, workspace: Path) -> None:
        # ``entries``/``dirs`` are 0 after the scope exits by walk_scope's
        # documented no-staleness contract; only hits/misses survive.
        clear_walk_cache()
        cli._collect(workspace)

        stats = walk_cache_stats()
        assert (stats["entries"], stats["dirs"]) == (0, 0), (
            f"the per-scan cache must not outlive the scope; got {stats!r}"
        )


# ===========================================================================
# Behavior 2 -- the two collectors together perform ONE physical os.walk
# ===========================================================================


class TestBehavior2OnePhysicalWalkForThePair:
    def test_pair_inside_one_scope_walks_once(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        monkeypatch.setattr(os, "walk", _counting_walk(calls))

        with walk_scope():
            secrets = SecretFileCollector().collect(workspace)
            posture = PostureCollector().collect(workspace)

        assert calls == [str(workspace)], (
            "secret_file + test_posture inside ONE scope must perform exactly one "
            f"physical os.walk rooted at the workspace (it was two); got {calls!r}"
        )
        # Anti-vacuity: one walk is only meaningful if both collectors reported.
        assert secrets and posture, (
            "fixture regression -- both collectors must report signals here; got "
            f"secret_file={secrets!r} test_posture={posture!r}"
        )

    def test_each_collector_alone_inside_a_scope_walks_once(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for collector in (SecretFileCollector(), PostureCollector()):
            calls: list[str] = []
            monkeypatch.setattr(os, "walk", _counting_walk(calls))
            clear_walk_cache()
            with walk_scope():
                collector.collect(workspace)
            assert calls == [str(workspace)], (
                f"{type(collector).__name__} must walk exactly once inside a scope; "
                f"got {calls!r}"
            )


# ===========================================================================
# Behavior 3 -- signals are UNCHANGED (literals captured from the parent commit)
# ===========================================================================


class TestBehavior3SignalsUnchanged:
    def test_secret_file_signals_match_the_parent_commit(self, workspace: Path) -> None:
        with walk_scope():
            rows = _projection(workspace, SecretFileCollector().collect(workspace))
        assert rows == PARENT_SECRET_FILE, (
            "secret_file's signals must be field-for-field identical to the parent "
            f"commit's output; got {rows!r}"
        )

    def test_test_posture_signals_match_the_parent_commit(self, workspace: Path) -> None:
        with walk_scope():
            rows = _projection(workspace, PostureCollector().collect(workspace))
        assert rows == PARENT_TEST_POSTURE, (
            "test_posture's signals must be field-for-field identical to the parent "
            f"commit's output, INCLUDING order; got {rows!r}"
        )

    def test_pinned_literals_are_not_vacuous(self) -> None:
        # A pinned-literal oracle is worthless if the literals are empty.
        assert len(PARENT_SECRET_FILE) == 1
        assert len(PARENT_TEST_POSTURE) == 2
        assert PARENT_SECRET_FILE[0][4] == "pkg/sub/.env.local"
        assert "(untested)" in PARENT_TEST_POSTURE[0][2]


# ===========================================================================
# Behavior 4 -- prune parity is INHERITED from the provider, not re-implemented
# ===========================================================================


class TestBehavior4PruneParityInherited:
    def test_no_signal_comes_from_any_pruned_directory(self, workspace: Path) -> None:
        with walk_scope():
            rows = _projection(workspace, SecretFileCollector().collect(workspace))
            rows += _projection(workspace, PostureCollector().collect(workspace))

        for name in PRUNED_DIRS:
            offenders = [
                row for row in rows if row[4] is not None and row[4].split("/")[0] == name
            ]
            assert offenders == [], (
                f"{name}/ must be pruned by the shared provider; got {offenders!r}"
            )
            assert [row for row in rows if row[2].startswith(f"{name}:")] == [], (
                f"{name}/ must not surface as a test_posture project; rows={rows!r}"
            )

    def test_the_same_files_outside_a_pruned_dir_ARE_reported(self, workspace: Path) -> None:
        # Anti-vacuity for the assertion above: prove the seeded files are the
        # kind both collectors do report when they are not under a pruned dir.
        _write(workspace, "keepdir/.env", "TOKEN=zzz\n")
        _write(workspace, "keepdir/mod.py")

        with walk_scope():
            secret_rows = _projection(workspace, SecretFileCollector().collect(workspace))
            posture_rows = _projection(workspace, PostureCollector().collect(workspace))

        assert "keepdir/.env" in [row[4] for row in secret_rows], (
            f"a .env outside a pruned dir must be reported; got {secret_rows!r}"
        )
        assert any(row[2].startswith("keepdir:") for row in posture_rows), (
            f"a project outside a pruned dir must be reported; got {posture_rows!r}"
        )

    def test_neither_module_still_spells_a_prune_expression(self) -> None:
        for name in CONVERTED:
            text = _source(name)
            assert "dirnames[:]" not in text, (
                f"{name} must no longer re-implement the in-place dirnames prune"
            )


# ===========================================================================
# Behavior 5 -- no-scope pass-through still works (deliberate degradation)
# ===========================================================================


class TestBehavior5NoScopePassThrough:
    def test_signals_are_identical_with_no_scope_active(self, workspace: Path) -> None:
        secret_rows = _projection(workspace, SecretFileCollector().collect(workspace))
        posture_rows = _projection(workspace, PostureCollector().collect(workspace))

        assert secret_rows == PARENT_SECRET_FILE, (
            f"secret_file must work with NO scope active; got {secret_rows!r}"
        )
        assert posture_rows == PARENT_TEST_POSTURE, (
            f"test_posture must work with NO scope active; got {posture_rows!r}"
        )

    def test_misses_increase_when_no_scope_is_active(self, workspace: Path) -> None:
        clear_walk_cache()
        before = walk_cache_stats()["misses"]

        SecretFileCollector().collect(workspace)
        PostureCollector().collect(workspace)

        after = walk_cache_stats()["misses"]
        assert after - before == 2, (
            "with no scope active the provider must degrade to a direct walk per "
            f"call, so misses must rise by 2 (parent commit: 0, the collectors did "
            f"not touch the provider at all); got {after - before}"
        )


# ===========================================================================
# Behavior 6 -- traversal-order independence, adversarially
# ===========================================================================


class TestBehavior6ReversedTraversalOrder:
    def test_reversed_order_inside_a_scope_changes_nothing(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "walk", _reversing_walk())

        with walk_scope():
            secret_rows = _projection(workspace, SecretFileCollector().collect(workspace))
            posture_rows = _projection(workspace, PostureCollector().collect(workspace))

        assert secret_rows == PARENT_SECRET_FILE, (
            f"secret_file must be independent of os.walk order; got {secret_rows!r}"
        )
        assert posture_rows == PARENT_TEST_POSTURE, (
            f"test_posture must be independent of os.walk order; got {posture_rows!r}"
        )

    def test_reversed_order_with_no_scope_changes_nothing(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "walk", _reversing_walk())

        secret_rows = _projection(workspace, SecretFileCollector().collect(workspace))
        posture_rows = _projection(workspace, PostureCollector().collect(workspace))

        assert secret_rows == PARENT_SECRET_FILE
        assert posture_rows == PARENT_TEST_POSTURE

    def test_the_reversing_wrapper_really_reverses(self, workspace: Path) -> None:
        # Anti-vacuity: an order-independence proof is worthless if the wrapper
        # is a no-op.
        plain = [
            (dirpath, list(dirnames), list(filenames))
            for dirpath, dirnames, filenames in _REAL_WALK(workspace / "svc")
        ]
        reversed_triples = [
            (dirpath, list(dirnames), list(filenames))
            for dirpath, dirnames, filenames in _reversing_walk()(workspace / "svc")
        ]
        assert [t[2] for t in plain] != [], "fixture regression: svc/ must hold files"
        assert [t[2] for t in reversed_triples] == [
            list(reversed(t[2])) for t in plain
        ], "the reversing wrapper must actually reverse each filenames list"


# ===========================================================================
# Behavior 7 -- source census
# ===========================================================================


class TestBehavior7SourceCensus:
    """The converted modules no longer own a walk or the shared prune symbols."""

    def test_converted_modules_no_longer_call_os_walk(self) -> None:
        for name in CONVERTED:
            text = _source(name)
            assert text.count("os.walk(") == 0, (
                f"{name} must not call os.walk( any more; "
                f"found {text.count('os.walk(')} occurrence(s)"
            )

    def test_converted_modules_no_longer_name_the_prune_symbols(self) -> None:
        for name in CONVERTED:
            text = _source(name)
            for symbol in ("_SKIP_DIRS", "_is_hidden"):
                assert text.count(symbol) == 0, (
                    f"{name} must not mention {symbol} any more (import or prose); "
                    f"found {text.count(symbol)} occurrence(s)"
                )

    def test_exactly_eight_collector_modules_still_walk(self) -> None:
        modules = sorted(p.name for p in COLLECTORS_DIR.glob("*.py"))
        assert len(modules) >= 15, (
            f"census domain regression -- expected the collectors package; got {modules!r}"
        )
        walkers = sorted(
            name for name in modules if "os.walk(" in (COLLECTORS_DIR / name).read_text(
                encoding="utf-8"
            )
        )
        assert walkers == [
            "broken_link.py",
            "dir_source.py",
            "filesystem.py",
            "large_file.py",
            "merge_conflict.py",
            "notes.py",
            "syntax_error.py",
            "todos.py",
        ], (
            "exactly 8 collector modules may still own an os.walk (was 10 before this "
            "iteration: dir_source and filesystem keep theirs by design, plus the six "
            "unconverted collectors). A later batch that converts one of these must "
            f"update this iteration-scoped pin. Got {walkers!r}"
        )
        assert "secret_file.py" not in walkers and "test_posture.py" not in walkers
