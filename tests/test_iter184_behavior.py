"""Iteration 184 behavior oracle -- aggregated per-manifest absorb WARNINGs.

MODULE NAME (why not ``test_iter180_behavior.py``, which the spec asked for).
This repo names behavior modules by the FACTORY iteration number, which runs
ahead of the state-dir counter: ``tests/test_iter180_behavior.py`` is ALREADY
TRACKED and is factory iter 180's oracle for ``pla verify
--fail-on-unresolved`` (commit ``6c8f0d3``), and the newest tracked module is
``tests/test_iter183_behavior.py`` (commit ``96a5336``, "factory iter 183").
Writing this iteration's oracle at the spec's literal path would have
OVERWRITTEN a shipped oracle, so state-dir 180 ships as factory 184 and this
module takes the next free number. Measured, not assumed: ``git ls-files`` lists
that module and ``git log`` attributes it to iteration 180.

Feature under test (state-dir iteration 180). ``DependencyCollector`` and
``LockfileDriftCollector`` each wrap their per-manifest signal build in a bare
``except Exception: continue``, so a manifest that fails to build was
indistinguishable from a tree with nothing to report -- on every surface the
user has. This iteration adds ONE aggregated ``logging.WARNING`` per
``collect()`` call, on the collector's OWN module logger, naming how many
manifests were absorbed and which one (deterministically).

Coverage, numbered to match the spec's Expected Behaviors:

1. Aggregated record, ``dependencies``: 3 recognized manifests, 2 raising ->
   the healthy signal is still returned AND exactly ONE ``WARNING`` record
   arrives on ``dependencies``' own module logger.
2. That record's formatted message carries the absorbed count (``2``), the
   offending manifest's RELATIVE path (no absolute path leaks), and the
   collector's name.
3. The same properties for ``LockfileDriftCollector`` -- covered by the
   ``lockfile_drift`` parameter of the classes below, which is why they are
   parametrized rather than duplicated.
4. Silence stays silent (anti-vacuity): on a tree where NOTHING raises, each
   collector returns its normal signals and emits ZERO ``WARNING``-or-above
   records -- not just on its own logger, but on ANY ``proactive_loop`` logger.
   Without this, behaviors 1-3 would also pass against a collector that screams
   on every scan.
5. The named path is DETERMINISTIC (the lexicographically SMALLEST failing
   relative path), not encounter-ordered.
6. The no-raise contract survives the worst case: when EVERY recognized manifest
   raises, each collector still returns a list (``[]``) instead of propagating,
   and still emits exactly ONE record whose count is the total.

HOW BEHAVIOR 5 IS MADE NON-VACUOUS, and a MEASURED note for the PM. The spec
suggested forcing a walk order opposite to the sort order. I tried that first via
the ``collectors.dir_source`` traversal seam (``monkeypatch.setattr(dir_source.os,
"walk", ...)``, the shape ``tests/test_iter70_behavior.py`` uses) and MEASURED it
to be INERT for ordering: with directory and file names re-yielded in DESCENDING
order, both collectors still called their per-manifest build in ASCENDING order
(``['aa_healthy', 'mm_fails', 'zz_fails']`` both ways), so that fixture cannot
distinguish "smallest" from "first encountered" and any assertion built on it
passes for the wrong reason. This module instead exploits ASCII collation, which
needs no seam at all: ``-`` (0x2D) sorts BEFORE ``/`` (0x2F), so
``a-x/pyproject.toml`` < ``a/pyproject.toml`` while a traversal that orders
directory names ascending meets ``a`` BEFORE ``a-x``. The lexicographic minimum
is therefore the SECOND failing manifest encountered, and the test ASSERTS that
disagreement from the recorded call order before asserting on the record -- so it
is self-proving inside the suite, not only in an out-of-repo probe.

ISOLATION CONTRACT honored. Every expectation comes from this iteration's
``pm.md`` "Expected Behaviors" plus the conventions of existing modules under
``tests/`` (``test_iter169_behavior.py`` for the ``caplog`` record filter and the
runtime-derived logger name, ``test_iter09_behavior.py`` for the ``dependencies``
manifest fixtures, ``test_iter70_behavior.py`` for the ``lockfile_drift`` pairing
rules). NO file under ``src/`` was read, NO engineer or reviewer note was opened,
and NO ``git diff`` was consulted. Logger names are DERIVED at runtime from each
collector's ``__module__`` rather than hardcoded, and the per-manifest build seam
is patched signature-agnostically (``*args, **kwargs``), because the two sibling
``_signal_for`` methods do NOT share a signature and a wrong-arity patch would
raise ``TypeError`` INSIDE the collector's own ``except`` -- absorbed, and
indistinguishable from "the emit never fired".

Fully offline and deterministic: ``tmp_path`` trees only (never the in-repo
tree), no network, no API key, no ``git`` subprocess, no clock or duration
assertion, and nothing asserted about indentation or docstring text (so the
3.12 / 3.13 matrix legs cannot diverge here).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

import pytest

from proactive_loop.collectors import DependencyCollector, LockfileDriftCollector
from proactive_loop.models import ContextSignal

# ---------------------------------------------------------------------------
# Derived expectations -- no hardcoded module paths.
# ---------------------------------------------------------------------------

DEPENDENCIES_LOGGER = DependencyCollector.__module__
LOCKFILE_DRIFT_LOGGER = LockfileDriftCollector.__module__

PACKAGE = "proactive_loop"

# A manifest recognized by BOTH collectors at once: ``dependencies`` reports any
# ``pyproject.toml`` it finds, and ``lockfile_drift`` reports a pyproject whose
# sibling lockfile is MISSING. Planting no lockfile therefore yields exactly one
# signal per directory from each collector.
MANIFEST = "pyproject.toml"
_PYPROJECT = '[project]\nname = "demo"\nversion = "0.1.0"\ndependencies = ["a", "b"]\n'

# Default fixture: one healthy manifest plus two that fail.
HEALTHY_DIR = "aa_healthy"
ALL_DIRS = ("aa_healthy", "mm_fails", "zz_fails")
TWO_FAILING = ("mm_fails", "zz_fails")

# Behavior 5 fixture -- see the module docstring. ``a-x/<M>`` sorts BEFORE
# ``a/<M>`` (ASCII ``-`` < ``/``) yet is encountered SECOND, so "lexicographic
# minimum" and "first encountered" name DIFFERENT manifests here.
ORDER_DIRS = ("a", "a-x", "b_healthy")
ORDER_FAILING = ("a", "a-x")

COLLECTOR_PARAMS = [
    pytest.param(DependencyCollector, DEPENDENCIES_LOGGER, "dependencies", id="dependencies"),
    pytest.param(
        LockfileDriftCollector, LOCKFILE_DRIFT_LOGGER, "lockfile_drift", id="lockfile_drift"
    ),
]


# ---------------------------------------------------------------------------
# Helpers -- black-box: plant a tmp tree, drive the public collector API, read
# back observable log records.
# ---------------------------------------------------------------------------


def _rel(directory: str) -> str:
    """The forward-slashed relative path a collector reports for *directory*."""
    return f"{directory}/{MANIFEST}"


def _plant_tree(root: Path, directories: tuple[str, ...] = ALL_DIRS) -> None:
    """Plant one recognized manifest (and NO lockfile) inside each directory."""
    for name in directories:
        manifest = root / name / MANIFEST
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(_PYPROJECT, encoding="utf-8")


def _patch_failures(
    monkeypatch: pytest.MonkeyPatch,
    collector_cls: type,
    failing_dirs: tuple[str, ...],
    *,
    known_dirs: tuple[str, ...] = ALL_DIRS,
    record_into: list[str] | None = None,
) -> None:
    """Make the per-manifest build raise for manifests under *failing_dirs*.

    Signature-agnostic on purpose: ``DependencyCollector._signal_for`` and
    ``LockfileDriftCollector._signal_for`` do NOT take the same arguments, and a
    wrong-arity patch would raise ``TypeError`` inside the collector's own
    ``except`` clause -- absorbed, and therefore indistinguishable from the
    feature not working at all. So the wrapper accepts anything, scans the
    STRINGIFIED arguments for a planted manifest path, and delegates otherwise.

    When *record_into* is given, every recognized manifest is appended to it in
    CALL order, which is how the ordering tests prove their own fixture.
    """
    original: Callable[..., Any] = collector_cls._signal_for  # must already exist
    failing_rels = tuple(_rel(name) for name in failing_dirs)
    known_rels = tuple(_rel(name) for name in known_dirs)

    def _wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        blob = "|".join(str(value).replace("\\", "/") for value in (*args, *kwargs.values()))
        if record_into is not None:
            for rel in known_rels:
                if rel in blob:
                    record_into.append(rel)
        for rel in failing_rels:
            if rel in blob:
                raise RuntimeError(f"planted per-manifest failure: {rel}")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(collector_cls, "_signal_for", _wrapper)


def _records_on(caplog: pytest.LogCaptureFixture, logger_name: str) -> list[logging.LogRecord]:
    """WARNING-or-above records emitted by exactly *logger_name*."""
    return [r for r in caplog.records if r.levelno >= logging.WARNING and r.name == logger_name]


def _package_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """WARNING-or-above records from ANY logger inside the product package."""
    return [
        r
        for r in caplog.records
        if r.levelno >= logging.WARNING
        and (r.name == PACKAGE or r.name.startswith(f"{PACKAGE}."))
    ]


def _collect_with_failures(
    collector_cls: type,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    *,
    failing_dirs: tuple[str, ...] = TWO_FAILING,
    planted: tuple[str, ...] = ALL_DIRS,
) -> list[ContextSignal]:
    """Plant a tree, arm the failures, collect once inside the capture window."""
    _plant_tree(root, planted)
    _patch_failures(monkeypatch, collector_cls, failing_dirs, known_dirs=planted)
    with caplog.at_level(logging.WARNING):
        signals = collector_cls().collect(root)
    assert isinstance(signals, list), "collect() must always return a list"
    return signals


def _sole_message(caplog: pytest.LogCaptureFixture, logger_name: str) -> str:
    """Assert exactly one record on *logger_name* and return its formatted text."""
    records = _records_on(caplog, logger_name)
    assert len(records) == 1, (
        f"expected exactly ONE aggregated record on {logger_name!r}; "
        f"got {[(r.name, r.levelname, r.getMessage()) for r in caplog.records]!r}"
    )
    return records[0].getMessage()


def _paths_of(signals: list[ContextSignal]) -> list[str]:
    return [str(getattr(s, "path", "")).replace("\\", "/") for s in signals]


def _tail_rels(signals: list[ContextSignal]) -> list[str]:
    """``<dir>/<manifest>`` for each returned signal, derived from its own path.

    Taken from the tail of the reported path rather than via ``relative_to`` so no
    assumption is made about whether the collector echoes the root it was handed
    or a resolved form of it.
    """
    tails: list[str] = []
    for path in _paths_of(signals):
        parts = path.split("/")
        tails.append("/".join(parts[-2:]) if len(parts) >= 2 else path)
    return tails


# ===========================================================================
# Preconditions -- the seams this oracle drives must exist and the fixture must
# be non-vacuous. A failure HERE means the TEST is wrong, not the product.
# ===========================================================================


class TestSeamPreconditions:
    def test_logger_names_are_the_collectors_own_modules(self) -> None:
        assert DEPENDENCIES_LOGGER.endswith(".dependencies")
        assert LOCKFILE_DRIFT_LOGGER.endswith(".lockfile_drift")
        assert DEPENDENCIES_LOGGER != LOCKFILE_DRIFT_LOGGER

    def test_behavior5_fixture_separates_sort_order_from_walk_order(self) -> None:
        # Pure collation fact, asserted so the fixture's premise is visible: the
        # SMALLEST failing rel is not the one an ascending directory walk meets
        # first. If this ever flips, behavior 5 below silently stops discriminating.
        failing = [_rel(name) for name in ORDER_FAILING]
        assert min(failing) == _rel("a-x")
        assert sorted(ORDER_FAILING) == ["a", "a-x"]

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_per_manifest_build_seam_exists(
        self, collector_cls: type, logger_name: str, label: str
    ) -> None:
        # ``monkeypatch.setattr`` below relies on this attribute already existing;
        # asserting it turns a silent no-op patch into a clear failure.
        assert callable(getattr(collector_cls, "_signal_for", None))

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_fixture_yields_one_signal_per_planted_manifest(
        self, collector_cls: type, logger_name: str, label: str, tmp_path: Path
    ) -> None:
        # Non-vacuity for every count assertion in this module: the planted tree
        # really does hold three RECOGNIZED manifests for both collectors.
        _plant_tree(tmp_path)
        signals = collector_cls().collect(tmp_path)
        assert len(signals) == len(ALL_DIRS), f"{label}: {signals!r}"


# ===========================================================================
# Behaviors 1 + 3 -- exactly ONE aggregated WARNING per scan, healthy signal
#   still returned. (Behavior 1 = the ``dependencies`` param, Behavior 3 = the
#   ``lockfile_drift`` param.)
# ===========================================================================


class TestB1AndB3AggregatedRecord:
    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_healthy_manifest_still_reported(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        signals = _collect_with_failures(collector_cls, tmp_path, monkeypatch, caplog)
        assert len(signals) == 1, f"{label}: expected only the healthy signal; got {signals!r}"
        assert _tail_rels(signals) == [_rel(HEALTHY_DIR)]

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_exactly_one_warning_record_on_own_module_logger(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _collect_with_failures(collector_cls, tmp_path, monkeypatch, caplog)
        records = _records_on(caplog, logger_name)
        assert len(records) == 1, f"{label}: {[r.getMessage() for r in caplog.records]!r}"
        assert records[0].levelno == logging.WARNING

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_aggregated_not_per_item(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Two absorbed failures must still be ONE record anywhere in the package:
        # the spec rejects a per-item record because ``watch`` re-scans on a timer.
        _collect_with_failures(collector_cls, tmp_path, monkeypatch, caplog)
        assert len(_package_records(caplog)) == 1

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_each_scan_reports_again_no_process_wide_dedupe(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # "One record per scan", not "one record per process": ``watch`` would
        # otherwise report a persistently broken manifest exactly once, ever.
        _plant_tree(tmp_path)
        _patch_failures(monkeypatch, collector_cls, TWO_FAILING)
        collector = collector_cls()
        with caplog.at_level(logging.WARNING):
            collector.collect(tmp_path)
            collector.collect(tmp_path)
        assert len(_records_on(caplog, logger_name)) == 2


# ===========================================================================
# Behaviors 2 + 3 -- the record carries the count, a relative path, and the
#   collector's name.
# ===========================================================================


class TestB2AndB3MessageContent:
    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_message_carries_absorbed_count(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _collect_with_failures(collector_cls, tmp_path, monkeypatch, caplog)
        message = _sole_message(caplog, logger_name)
        assert re.search(r"(?<!\d)2(?!\d)", message), f"{label}: no count 2 in {message!r}"

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_message_carries_a_failing_relative_path(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _collect_with_failures(collector_cls, tmp_path, monkeypatch, caplog)
        message = _sole_message(caplog, logger_name)
        failing_rels = [_rel(name) for name in TWO_FAILING]
        assert any(rel in message for rel in failing_rels), f"{label}: {message!r}"
        # It must name a FAILING manifest, never the healthy one.
        assert _rel(HEALTHY_DIR) not in message, f"{label}: {message!r}"

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_message_is_relative_not_absolute(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _collect_with_failures(collector_cls, tmp_path, monkeypatch, caplog)
        message = _sole_message(caplog, logger_name)
        assert str(tmp_path) not in message, f"{label}: absolute path leaked: {message!r}"

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_message_names_the_collector(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _collect_with_failures(collector_cls, tmp_path, monkeypatch, caplog)
        message = _sole_message(caplog, logger_name)
        assert label in message, f"expected the collector name {label!r} in {message!r}"


# ===========================================================================
# Behavior 4 -- silence stays silent (the anti-vacuity guard).
# ===========================================================================


class TestB4SilenceStaysSilent:
    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_healthy_scan_emits_nothing_and_still_returns_signals(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _plant_tree(tmp_path)
        with caplog.at_level(logging.WARNING):
            signals = collector_cls().collect(tmp_path)
        assert len(signals) == len(ALL_DIRS), f"{label}: {signals!r}"
        assert _records_on(caplog, logger_name) == []
        assert _package_records(caplog) == [], (
            f"{label}: a healthy scan must be silent across the whole package; got "
            f"{[(r.name, r.getMessage()) for r in _package_records(caplog)]!r}"
        )

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_empty_tree_emits_nothing(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING):
            signals = collector_cls().collect(tmp_path)
        assert signals == []
        assert _package_records(caplog) == []


# ===========================================================================
# Behavior 5 -- the named path is the lexicographic minimum, not the first one
#   the traversal happened to meet.
# ===========================================================================


class TestB5DeterministicPath:
    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_names_lexicographically_smallest_failing_path(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        order: list[str] = []
        _plant_tree(tmp_path, ORDER_DIRS)
        _patch_failures(
            monkeypatch,
            collector_cls,
            ORDER_FAILING,
            known_dirs=ORDER_DIRS,
            record_into=order,
        )
        with caplog.at_level(logging.WARNING):
            signals = collector_cls().collect(tmp_path)

        failing_rels = {_rel(name) for name in ORDER_FAILING}
        encountered = [rel for rel in order if rel in failing_rels]
        smallest = min(failing_rels)
        # The fixture proves ITSELF: the two failing manifests really are met in
        # the opposite order to how they sort, so "smallest" and "first seen" are
        # different strings and the assertion below cannot pass by coincidence.
        assert len(encountered) == len(failing_rels), f"{label}: {order!r}"
        assert encountered[0] != smallest, (
            f"{label}: fixture no longer discriminates -- the smallest failing rel "
            f"{smallest!r} was also the first encountered ({encountered!r})"
        )

        message = _sole_message(caplog, logger_name)
        assert smallest in message, f"{label}: expected {smallest!r} in {message!r}"
        assert encountered[0] not in message, (
            f"{label}: the record named {encountered[0]!r}, the ENCOUNTER-order pick, "
            f"not the deterministic minimum {smallest!r}: {message!r}"
        )
        # Fail-open is unchanged here too: the one healthy manifest still reports.
        assert _tail_rels(signals) == [_rel("b_healthy")]

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_return_value_is_sorted_not_encounter_ordered(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The pre-existing ``found.sort(...)`` contract must be untouched by this
        # iteration. On the same fixture, sort order and encounter order differ, so
        # this is a real assertion rather than a restatement of the walk.
        order: list[str] = []
        _plant_tree(tmp_path, ORDER_DIRS)
        _patch_failures(monkeypatch, collector_cls, (), known_dirs=ORDER_DIRS, record_into=order)
        signals = collector_cls().collect(tmp_path)
        returned = _tail_rels(signals)
        assert len(returned) == len(ORDER_DIRS), f"{label}: {returned!r}"
        assert returned == sorted(returned), f"{label}: {returned!r}"
        assert returned != order, (
            f"{label}: fixture no longer discriminates -- encounter order {order!r} "
            f"already equals sorted order"
        )


# ===========================================================================
# Behavior 6 -- the no-raise contract survives the worst case.
# ===========================================================================


class TestB6WorstCaseEveryManifestFails:
    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_returns_empty_list_and_does_not_propagate(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        signals = _collect_with_failures(
            collector_cls, tmp_path, monkeypatch, caplog, failing_dirs=ALL_DIRS
        )
        assert signals == [], f"{label}: expected [] when every manifest fails; got {signals!r}"

    @pytest.mark.parametrize(("collector_cls", "logger_name", "label"), COLLECTOR_PARAMS)
    def test_single_record_counts_every_failure(
        self,
        collector_cls: type,
        logger_name: str,
        label: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        _collect_with_failures(
            collector_cls, tmp_path, monkeypatch, caplog, failing_dirs=ALL_DIRS
        )
        message = _sole_message(caplog, logger_name)
        expected = str(len(ALL_DIRS))
        assert re.search(rf"(?<!\d){expected}(?!\d)", message), f"{label}: {message!r}"
        assert not re.search(r"(?<!\d)2(?!\d)", message), (
            f"{label}: count must be the TOTAL {expected}, not a partial: {message!r}"
        )
