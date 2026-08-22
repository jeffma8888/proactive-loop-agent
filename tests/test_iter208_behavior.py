"""Per-PATH I/O-budget oracle for the perception layer (state dir ``iter-231``).

WHAT THIS MODULE PINS. One perception scan -- driven through the entry point every
front-door verb shares, ``cli._collect`` -- is allowed a bounded amount of *filesystem*
work **per path**: how many times any single path may be ``stat``ed, and how many times
any single path may be ``read_text``ed. The sibling oracle
``tests/test_iter192_behavior.py`` budgets a scan's traversals, parses and child
processes; its own header (line 9) records that ``collectors/text_source``'s
"583 -> 200 read_text" win was *"true when written and unenforced since"*, and it
declines to close that gap. Nothing anywhere budgets ``Path.stat``. This module closes
exactly those two holes and adds no third.

WHY PER PATH AND NOT AS AN ABSOLUTE TOTAL. A total is a function of how big the fixture
is, so it goes stale the moment the fixture grows a file and it says nothing about the
defect it is meant to catch. The defect is *fan-out*: the same path being interrogated
over and over by collectors that do not share their answers. Measured on this fixture,
the scan root itself is ``stat``ed 17 times and one Markdown file is decoded twice. A
per-path ceiling names that shape directly and is scale-free -- adding a file to the
fixture cannot move it.

WHY COUNTS AND NOT MILLISECONDS. A count is deterministic and regime-free: identical on
a loaded CI runner and on a laptop, and identical on both legs of the 3.12/3.13 matrix.
MEASURED, both legs, before either constant below was chosen: ``max stat = 17``,
``max read_text = 2``, 135 stats over 36 distinct paths and 6 decodes over 5 -- byte
for byte the same under CPython 3.12.7 and 3.13.0, which matters because pathlib was
rewritten between those releases. A millisecond threshold would be none of those things,
and a flaky timing assertion on a PUBLIC portfolio repo reds a badge for reasons no
contributor caused. Nothing here asserts a duration, a docstring or help-text
indentation.

WHY EVERY BUDGET IS A CEILING, AND WHY A CEILING ALONE IS NOT ENOUGH. Both budgets are
asserted with ``<=`` so that an improvement can never red the build -- the 17 stats this
fixture exhibits are WASTEFUL, and an ``==`` would bless that waste and fail on the day
someone removes it. But a ceiling set uselessly high is indistinguishable from no
ceiling at all, and it passes forever. So each budget is ALSO asserted to BIND: the
observed maximum must reach at least :data:`MIN_BINDING_FRACTION` of the published
ceiling, which fails if a future contributor "fixes" a red build by raising the
constant instead of measuring. Raising a constant here is legitimate only with a fresh
measurement recorded in the commit; every failure message says so, and names the path it
measured.

WHY THE CACHES ARE CLEARED FOR EVERY TEST. ``dir_source``'s walk cache is what makes a
second listing of a scope free, so a scan that INHERITS a warm cache performs fewer
stats than a real one and every budget below is satisfied by work it never did. Under
``-n auto`` test order is not stable, so a fail-open guard whose verdict depends on
which sibling ran first is not a guard. The autouse fixture clears the walk cache and
the digest-keyed parse memo in both directions.

WHY THE BUDGET IS SCOPED TO PATHS UNDER THE SCAN ROOT. Patching ``Path.stat`` is a
process-global rebind, so during the instrumented window pytest's own machinery is
counted too. Those paths are not the scan's and no collector controls them, so pricing
them would make this oracle's verdict depend on the test runner's internals. The tally
is kept whole and the budgets are priced over the sub-mapping rooted at the scanned
tree; :data:`_within` is where that restriction lives.

HERMETIC BY CONSTRUCTION. Every scan runs against a tree the test CREATES under
``tmp_path``, and Behavior 1 asserts that rather than assuming it: a count taken against
the ambient repository would pass only on this machine and break in the fresh-clone
release check (the 2026-08-11 operator lesson). No network and no gitignored path.

MODULE NAME, derived from the repo and never from the state-dir counter -- the operator
pin, and the defect that cost factory iteration 186 a shipped oracle. The highest
tracked ``tests/test_iterNN_behavior.py`` is 207, so this file is 208, and
``git cat-file -e HEAD:tests/test_iter208_behavior.py`` FAILED before a byte was
written, proving the path free in ``HEAD``. The filename is a free-slot marker, not a
claim about which iteration built it.

Coverage (numbered to match this iteration's ``pm.md`` Expected Behaviors):

1. The scan root is built under ``tmp_path``, is not the repository root, and exactly
   ONE ``cli._collect`` runs against it.
2. Both tallies are exposed as path-to-count mappings, keyed by RESOLVED path so two
   spellings of one file cannot split a count and hide fan-out.
3. ``STATS_PER_PATH`` and ``DECODES_PER_PATH`` are module-level ``Final[int]`` and are
   compared only with ``<=``; no comparison in this module tests ``==`` against either.
4. Each budget BINDS -- the observed maximum reaches at least ``MIN_BINDING_FRACTION``
   of the ceiling, so a uselessly high ceiling fails instead of passing.
5. Anti-vacuity: the scan stat'ed at least one path AND decoded at least one path AND
   produced at least one signal.
6. Two-sidedness: each shim is PROVED to count, by a control performing a known number
   of calls inside the window and asserting the tally observed exactly that many.
7. Teardown is unconditional: the real ``Path.stat`` and ``Path.read_text`` are restored
   even when the instrumented window raises.
8. Every budget failure message names its target path and states that the ceiling may be
   raised only with a fresh measurement recorded in the commit.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest

from proactive_loop import cli
from proactive_loop.collectors.dir_source import clear_walk_cache
from proactive_loop.collectors.syntax_error import clear_parse_memo

# Captured ONCE at import, BEFORE any fixture rebinds them. Patching a method on the
# class is a process-global rebind, so a shim that re-looked-up the live attribute at
# call time would recurse into itself.
_REAL_STAT: Final = Path.stat
_REAL_READ_TEXT: Final = Path.read_text

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# The budgets. Each is a CEILING measured on the fixture below, never a target.
# ---------------------------------------------------------------------------

# Times a scan may ``stat`` ONE path. MEASURED 17 on both matrix legs, all of it on the
# scan root, which every walking collector re-interrogates for itself. LOWER this as
# collectors learn to share one listing; raise it only with a fresh measurement in the
# commit message.
STATS_PER_PATH: Final[int] = 20

# Times a scan may ``read_text`` ONE path. MEASURED 2 on both matrix legs -- one
# Markdown file decoded by two content collectors. 1 is the defensible destination:
# a scan should decode a file once and share the text.
DECODES_PER_PATH: Final[int] = 3

# The share of a published ceiling the observed maximum must reach for that ceiling to
# count as BINDING. Without this, raising a constant is a way to make a red build green
# and a budget decays into decoration. 0.5 leaves honest headroom for a legitimate
# small change while still failing a ceiling set at twice the truth.
MIN_BINDING_FRACTION: Final[float] = 0.5

# Directories the package's walk policy prunes, each seeded with content the content
# collectors would otherwise decode -- so a pruning regression shows up as fan-out.
PRUNED_DIRS: Final[tuple[str, ...]] = (
    "node_modules",
    "dist",
    "__pycache__",
    ".tox",
    ".venv",
    ".git",
)

# ``.py`` files planted OUTSIDE any pruned directory, with DISTINCT content: the parse
# memo is digest-keyed, so byte-identical files would quietly change the work profile.
UNPRUNED_SOURCES: Final[dict[str, str]] = {
    "pkg/mod_a.py": "x = 1\n# TODO: wire this up\n",
    "pkg/mod_b.py": "def f() -> int:\n    return 2\n",
    # Deliberately INVALID, so the failing-parse path is exercised too.
    "pkg/broken.py": "def f(:\n",
}


@dataclass
class PathIoCounters:
    """One window's per-path tally of the two units of I/O this module budgets.

    Keys are the paths as the caller spelled them; :func:`_by_resolved_path` merges
    them afterwards. Resolving inside the shim would pay a syscall per call and change
    the very thing being measured.
    """

    stats: Counter[str] = field(default_factory=Counter)
    decodes: Counter[str] = field(default_factory=Counter)


@pytest.fixture(autouse=True)
def _isolate_perception_caches() -> Iterator[None]:
    """No test may inherit or leak a warm walk cache or memoized parse verdict.

    Both directions matter. A warm walk cache makes a scan cheaper than a real one, so
    the budgets would be met by work that never happened; leaking one makes some LATER
    module's count depend on this one.
    """
    clear_walk_cache()
    clear_parse_memo()
    yield
    clear_walk_cache()
    clear_parse_memo()


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """A small tmp tree that reaches the walking AND the content collectors."""
    root = tmp_path / "ws"
    root.mkdir()
    for rel, content in UNPRUNED_SOURCES.items():
        _write(root, rel, content)
    _write(root, "docs/notes.md", "- TODO: write the docs\n")
    _write(root, "README.md", "# ws\n")
    for name in PRUNED_DIRS:
        _write(root, f"{name}/pruned.py", "def g(:\n")
        _write(root, f"{name}/pruned.md", "- TODO: pruned todo\n")
    return root


@contextmanager
def _instrumented() -> Iterator[PathIoCounters]:
    """Count every ``Path.stat`` and ``Path.read_text`` for the duration of the block.

    Written as an explicit contextmanager rather than with ``monkeypatch`` so that
    Behavior 7 can assert the teardown DIRECTLY: a leaked ``Path.stat`` patch would
    corrupt every later module in the same xdist worker, so restoration happens in a
    ``finally`` and is proved by a test that raises inside the window.
    """
    tally = PathIoCounters()

    def stat_shim(self: Path, *args: Any, **kwargs: Any) -> Any:
        tally.stats[str(self)] += 1
        return _REAL_STAT(self, *args, **kwargs)

    def read_text_shim(self: Path, *args: Any, **kwargs: Any) -> Any:
        tally.decodes[str(self)] += 1
        return _REAL_READ_TEXT(self, *args, **kwargs)

    Path.stat = stat_shim  # type: ignore[method-assign]
    Path.read_text = read_text_shim  # type: ignore[method-assign]
    try:
        yield tally
    finally:
        Path.stat = _REAL_STAT  # type: ignore[method-assign]
        Path.read_text = _REAL_READ_TEXT  # type: ignore[method-assign]


def _by_resolved_path(tally: Counter[str]) -> Counter[str]:
    """Merge a raw tally onto RESOLVED paths.

    Load-bearing rather than cosmetic: on macOS ``tmp_path`` reaches collectors both as
    ``/var/...`` and ``/private/var/...``, and counting those separately would HALVE an
    observed fan-out and let the defect through.
    """
    merged: Counter[str] = Counter()
    for raw, count in tally.items():
        merged[os.path.realpath(raw)] += count
    return merged


def _within(root: Path, tally: Counter[str]) -> Counter[str]:
    """The resolved sub-tally for paths under *root*.

    The instrumented window is process-global, so pytest's own machinery is counted
    too. Those paths belong to the test runner, not the scan, and pricing them would
    make this oracle's verdict depend on the runner's internals.
    """
    real_root = Path(os.path.realpath(root))
    return Counter(
        {
            path: count
            for path, count in _by_resolved_path(tally).items()
            if Path(path).is_relative_to(real_root)
        }
    )


def _worst(counts: Counter[str]) -> tuple[str, int]:
    """The path with the highest count, and that count. ``("", 0)`` when empty."""
    if not counts:
        return ("", 0)
    path, count = counts.most_common(1)[0]
    return (path, count)


def _raise_only_with_a_measurement(constant: str) -> str:
    """The shared remedy sentence every budget failure ends with."""
    return (
        f"{constant} is a CEILING: lower it when the fan-out is removed, and raise it "
        "ONLY with a fresh measurement recorded in the commit -- never edit it to green "
        "a red build, because a ceiling above the truth stops catching anything."
    )


# ===========================================================================
# Behavior 1 -- the fixture's isolation is ASSERTED, not assumed
# ===========================================================================


class TestBehavior1FixtureIsolation:
    def test_the_scan_root_is_inside_tmp_path_and_is_not_the_repo_root(
        self, workspace: Path, tmp_path: Path
    ) -> None:
        root = workspace.resolve()
        assert root.is_relative_to(tmp_path.resolve()), (
            "the scan root must live under tmp_path; a budget counted against the "
            f"ambient tree passes only on this machine. root={root}"
        )
        assert root != REPO_ROOT, (
            "the scan root must NOT be the repository root -- the fresh-clone release "
            f"check has no gitignored local state. root={root}"
        )


# ===========================================================================
# Behavior 2 -- both tallies are exposed as per-resolved-path mappings
# ===========================================================================


class TestBehavior2PerPathMappings:
    def test_one_scan_yields_a_stat_mapping_and_a_decode_mapping(
        self, workspace: Path
    ) -> None:
        with _instrumented() as tally:
            cli._collect(workspace)

        stats = _within(workspace, tally.stats)
        decodes = _within(workspace, tally.decodes)

        assert stats and decodes, (
            "both tallies must be mappings from path to count over the scanned tree; "
            f"got stats={dict(stats)!r} decodes={dict(decodes)!r}"
        )
        assert all(isinstance(count, int) and count >= 1 for count in stats.values())
        assert all(isinstance(count, int) and count >= 1 for count in decodes.values())

    def test_counts_are_keyed_by_resolved_path_so_two_spellings_cannot_split_one(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "probe.txt"
        target.write_text("probe\n", encoding="utf-8")
        # The same file named two ways. Without resolution these are two keys of 1,
        # and a fan-out of 2 reads as no fan-out at all.
        spellings = (target, tmp_path / "." / "probe.txt")

        with _instrumented() as tally:
            for spelling in spellings:
                spelling.read_text(encoding="utf-8")

        merged = _by_resolved_path(tally.decodes)
        assert merged[os.path.realpath(target)] == 2, (
            "two spellings of ONE path must merge onto a single count, or an observed "
            f"fan-out is silently halved; merged={dict(merged)!r}"
        )


# ===========================================================================
# Behavior 3 -- the budgets are Final[int] ceilings, never equalities
# ===========================================================================


class TestBehavior3BudgetsAreCeilings:
    def test_both_budgets_are_positive_integer_constants(self) -> None:
        assert isinstance(STATS_PER_PATH, int) and STATS_PER_PATH > 0
        assert isinstance(DECODES_PER_PATH, int) and DECODES_PER_PATH > 0

    def test_no_stat_in_this_module_compares_a_budget_for_equality(self) -> None:
        # The needles are BUILT rather than written out, so this guard cannot match
        # itself -- a literal here would make the check unfalsifiable.
        source = Path(__file__).read_text(encoding="utf-8")
        for name in ("STATS_PER_PATH", "DECODES_PER_PATH"):
            needle = "== " + name
            assert needle not in source, (
                "a budget must be asserted with <= only: an equality BLESSES today's "
                "waste and reds the build on the day someone removes it, which is the "
                f"improvement this file exists to protect. found {needle!r}"
            )

    def test_the_observed_maximum_stats_per_path_stay_within_budget(
        self, workspace: Path
    ) -> None:
        with _instrumented() as tally:
            cli._collect(workspace)

        path, observed = _worst(_within(workspace, tally.stats))
        assert observed <= STATS_PER_PATH, (
            f"{observed} stat calls on ONE path in a single scan ({path}); the budget "
            f"is {STATS_PER_PATH} per path. Every walking collector re-interrogating "
            "the same path instead of sharing one listing is what this catches. "
            + _raise_only_with_a_measurement("STATS_PER_PATH")
        )

    def test_the_observed_maximum_decodes_per_path_stay_within_budget(
        self, workspace: Path
    ) -> None:
        with _instrumented() as tally:
            cli._collect(workspace)

        path, observed = _worst(_within(workspace, tally.decodes))
        assert observed <= DECODES_PER_PATH, (
            f"{observed} read_text calls on ONE path in a single scan ({path}); the "
            f"budget is {DECODES_PER_PATH} per path. This is the 583 -> 200 decode win "
            "that text_source won and nothing has protected since. "
            + _raise_only_with_a_measurement("DECODES_PER_PATH")
        )


# ===========================================================================
# Behavior 4 -- each budget BINDS, so a uselessly high ceiling fails
# ===========================================================================


class TestBehavior4TheBudgetsBind:
    def test_the_stat_budget_is_not_set_uselessly_high(self, workspace: Path) -> None:
        with _instrumented() as tally:
            cli._collect(workspace)

        path, observed = _worst(_within(workspace, tally.stats))
        floor = STATS_PER_PATH * MIN_BINDING_FRACTION
        assert observed >= floor, (
            f"the worst path ({path}) was stat'ed {observed} times against a published "
            f"ceiling of {STATS_PER_PATH}, below the {MIN_BINDING_FRACTION:.0%} floor "
            f"of {floor:g}. A ceiling this far above the truth cannot catch a "
            "regression, so LOWER it to the measured value -- if the fan-out really "
            "shrank, that is the fix and the new number belongs in the commit."
        )

    def test_the_decode_budget_is_not_set_uselessly_high(self, workspace: Path) -> None:
        with _instrumented() as tally:
            cli._collect(workspace)

        path, observed = _worst(_within(workspace, tally.decodes))
        floor = DECODES_PER_PATH * MIN_BINDING_FRACTION
        assert observed >= floor, (
            f"the worst path ({path}) was decoded {observed} times against a published "
            f"ceiling of {DECODES_PER_PATH}, below the {MIN_BINDING_FRACTION:.0%} floor "
            f"of {floor:g}. LOWER the ceiling to the measured value; a budget nobody "
            "can breach is decoration."
        )


# ===========================================================================
# Behavior 5 -- anti-vacuity: a scan that did nothing cannot pass
# ===========================================================================


class TestBehavior5AntiVacuity:
    def test_the_scan_stats_decodes_and_perceives_something(
        self, workspace: Path
    ) -> None:
        with _instrumented() as tally:
            snapshot = cli._collect(workspace)

        stats = _within(workspace, tally.stats)
        decodes = _within(workspace, tally.decodes)

        assert stats, (
            "a per-path stat ceiling met by stat'ing NOTHING is fail-open; the shim "
            "must observe the scan's real filesystem interrogation"
        )
        assert decodes, (
            "a per-path decode ceiling met by decoding NOTHING is fail-open -- exactly "
            "what a warm walk cache produces, which is why the autouse fixture clears it"
        )
        assert snapshot.signals, (
            "fixture regression -- this tree must reach the collectors, or every budget "
            "above is satisfied by doing no work"
        )


# ===========================================================================
# Behavior 6 -- the oracle is two-sided: every shim is proved to COUNT
# ===========================================================================


class TestBehavior6TheShimsActuallyCount:
    def test_the_stat_shim_counts_exactly_the_calls_made(self, tmp_path: Path) -> None:
        probe = tmp_path / "stat_probe.txt"
        probe.write_text("x\n", encoding="utf-8")

        with _instrumented() as tally:
            for _ in range(3):
                probe.stat()

        counted = _by_resolved_path(tally.stats)[os.path.realpath(probe)]
        assert counted == 3, (
            "the stat counter must record every Path.stat call, or every stat budget "
            f"above is vacuously green; got {counted} for {probe}"
        )

    def test_the_read_text_shim_counts_exactly_the_calls_made(
        self, tmp_path: Path
    ) -> None:
        probe = tmp_path / "decode_probe.md"
        probe.write_text("y\n", encoding="utf-8")

        with _instrumented() as tally:
            for _ in range(2):
                probe.read_text(encoding="utf-8")

        counted = _by_resolved_path(tally.decodes)[os.path.realpath(probe)]
        assert counted == 2, (
            "the decode counter must record every Path.read_text call, or every decode "
            f"budget above is vacuously green; got {counted} for {probe}"
        )

    def test_the_shims_are_absent_outside_an_instrumented_window(self) -> None:
        # Proves the teardown, not the install: this test opens no window, so a shim
        # visible here would be one leaked by a sibling.
        assert Path.stat is _REAL_STAT
        assert Path.read_text is _REAL_READ_TEXT


# ===========================================================================
# Behavior 7 -- teardown is unconditional, even when the window raises
# ===========================================================================


class TestBehavior7TeardownIsUnconditional:
    def test_the_real_callables_are_restored_when_the_window_raises(self) -> None:
        sentinel = "deliberate failure inside the instrumented window"

        with pytest.raises(RuntimeError, match="deliberate failure"):
            with _instrumented():
                raise RuntimeError(sentinel)

        assert Path.stat is _REAL_STAT, (
            "Path.stat was left patched after the window raised -- a leaked patch "
            "corrupts every later module in the same xdist worker"
        )
        assert Path.read_text is _REAL_READ_TEXT, (
            "Path.read_text was left patched after the window raised -- a leaked patch "
            "corrupts every later module in the same xdist worker"
        )

    def test_a_window_that_completes_normally_also_restores(self, tmp_path: Path) -> None:
        with _instrumented() as tally:
            (tmp_path / "ok.txt").write_text("z\n", encoding="utf-8")
            (tmp_path / "ok.txt").stat()

        assert tally.stats, "the window must have counted the probe's stat"
        assert Path.stat is _REAL_STAT
        assert Path.read_text is _REAL_READ_TEXT


# ===========================================================================
# Behavior 8 -- failure messages name their path and their remedy
# ===========================================================================


class TestBehavior8FailureMessagesAreActionable:
    @pytest.mark.parametrize("constant", ["STATS_PER_PATH", "DECODES_PER_PATH"])
    def test_the_remedy_sentence_names_the_constant_and_forbids_editing_to_green(
        self, constant: str
    ) -> None:
        message = _raise_only_with_a_measurement(constant)
        assert constant in message
        assert "fresh measurement recorded in the commit" in message
        assert "never edit it to green" in message

    def test_every_budget_assertion_reports_the_path_it_measured(self) -> None:
        # The messages interpolate ``path`` from ``_worst``; this pins that the helper
        # returns a path alongside the count, so a failure is actionable rather than a
        # bare number the reader has to go and re-derive.
        counts: Counter[str] = Counter({"/a": 4, "/b": 9})
        assert _worst(counts) == ("/b", 9)
        assert _worst(Counter()) == ("", 0), (
            "an empty tally must not raise here; anti-vacuity is Behavior 5's job and "
            "a crash would replace its verdict with an error"
        )
