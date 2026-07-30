"""Black-box behavior tests for iteration 19 --- resilient collector orchestration.

Feature under test: ``cli._collect(workspace) -> WorkspaceSnapshot`` --- the shared
collector-orchestration seam behind every front-door verb (``scan`` / ``run`` /
``signals`` / ``watch``) --- must ENFORCE the SPEC 4.1 "collectors never raise ->
``[]``" invariant at the one place the code previously only asserted it in a
docstring. A single collector whose ``collect()`` raises is isolated (logged at
WARNING naming its ``name``, contributing ``[]``) instead of aborting the whole
scan; the surviving collectors' signals are preserved.

ISOLATION CONTRACT (honored): these tests were written strictly against this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, and ``SPEC.md`` sections 4.1 / 4.5 --- and drive ONLY documented
public surfaces: the module-level ``proactive_loop.cli._collect`` (the
internal-but-importable seam the suite already treats as public, exactly like
``_md_cell`` in test_iter12 and ``_render_signals`` in test_iter15) and the CLI
entry ``proactive_loop.cli.main(argv) -> int`` (its observable exit code + written
artifacts). **No file under ``src/`` was read, no engineer/reviewer notes were
read, and no ``git diff`` was consulted.** Every test is fully offline: zero
network, zero API keys. The injection seam is ``proactive_loop.cli.all_collectors``
(the name ``_collect`` actually calls, per the spec), monkeypatched with tiny
local test doubles satisfying the ``Collector`` shape (a ``name`` attribute + a
``collect(self, root) -> list[ContextSignal]`` method). Synthetic ``tmp_path``
workspaces are used throughout (never the in-repo tree).
"""

from __future__ import annotations

import logging
from pathlib import Path

from proactive_loop import cli
from proactive_loop.cli import main
from proactive_loop.models import ContextSignal, WorkspaceSnapshot

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "scripted_responses.json"

_CLI_LOGGER = "proactive_loop.cli"


# ---------------------------------------------------------------------------
# Tiny local test doubles satisfying the Collector shape (name + collect()).
# Deterministic, no filesystem dependency --- exactly as the spec prescribes.
# ---------------------------------------------------------------------------


class _RaisingCollector:
    """A buggy collector that violates the 4.1 never-raise convention."""

    def __init__(self, name: str = "boom") -> None:
        self.name = name

    def collect(self, root: Path) -> list[ContextSignal]:
        raise RuntimeError(f"exploded inside {self.name}")


class _WellBehavedCollector:
    """A conformant collector returning one fixed, deterministic signal."""

    def __init__(self, name: str = "ok", *, summary: str = "alive") -> None:
        self.name = name
        self._summary = summary

    def collect(self, root: Path) -> list[ContextSignal]:
        return [ContextSignal(source="ok", kind="note", summary=self._summary)]


def _cli_warnings(caplog) -> list[logging.LogRecord]:
    """WARNING records emitted on the ``proactive_loop.cli`` logger only."""
    return [
        r
        for r in caplog.records
        if r.name == _CLI_LOGGER and r.levelno == logging.WARNING
    ]


# ===========================================================================
# Behavior 1 --- A raising collector does NOT abort _collect (no propagation).
# ===========================================================================


def test_b01_raising_collector_does_not_abort_collect(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_RaisingCollector("boom"), _WellBehavedCollector()],
    )

    # Must NOT propagate the RuntimeError; must return a snapshot.
    snapshot = cli._collect(tmp_path)

    assert isinstance(snapshot, WorkspaceSnapshot), (
        "a raising collector must be contained, not propagated: "
        f"_collect returned {snapshot!r}"
    )


# ===========================================================================
# Behavior 2 --- Surviving collectors' signals are preserved (per-collector
# guard). The raising double is FIRST, so an alive signal in the result proves
# the try/except wraps each collector, not the whole loop.
# ===========================================================================


def test_b02_surviving_signal_preserved_guard_is_per_collector(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_RaisingCollector("boom"), _WellBehavedCollector()],
    )

    snapshot = cli._collect(tmp_path)

    # The well-behaved (2nd) collector's signal survived the 1st one raising.
    alive = [s for s in snapshot.signals if s.summary == "alive" and s.kind == "note"]
    assert len(alive) == 1, (
        "the well-behaved collector's signal must survive a prior raise "
        f"(a whole-loop try/except would lose it); signals={snapshot.signals!r}"
    )
    # The raising double contributed [] --- it is the ONLY other collector, so
    # the surviving signal is the only signal present.
    assert len(snapshot.signals) == 1, (
        "the raising collector must contribute [] (not a partial/garbage signal); "
        f"signals={snapshot.signals!r}"
    )
    # The snapshot roots at the scanned workspace.
    assert snapshot.root == str(tmp_path)


# ===========================================================================
# Behavior 3 --- The failure is logged at WARNING (naming the collector), not
# silently swallowed. Exactly one WARNING record on the cli logger.
# ===========================================================================


def test_b03_raise_logged_once_at_warning_naming_collector(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_RaisingCollector("boom"), _WellBehavedCollector()],
    )
    caplog.set_level(logging.WARNING, logger=_CLI_LOGGER)

    cli._collect(tmp_path)

    warnings = _cli_warnings(caplog)
    assert len(warnings) == 1, (
        "a single raising collector must emit exactly one WARNING, not zero "
        f"(silently swallowed) nor many; got {[r.getMessage() for r in warnings]}"
    )
    assert "boom" in warnings[0].getMessage(), (
        "the WARNING must name the failing collector so the bug is surfaceable; "
        f"message={warnings[0].getMessage()!r}"
    )


# ===========================================================================
# Behavior 4 --- Each raising collector is isolated independently: N raises ->
# N warnings, and all well-behaved collectors between/after them survive.
# ===========================================================================


def test_b04_multiple_raises_are_each_isolated(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [
            _RaisingCollector("boom_a"),
            _WellBehavedCollector(),
            _RaisingCollector("boom_b"),
        ],
    )
    caplog.set_level(logging.WARNING, logger=_CLI_LOGGER)

    snapshot = cli._collect(tmp_path)

    # The middle well-behaved collector survived being sandwiched by two raisers.
    alive = [s for s in snapshot.signals if s.summary == "alive" and s.kind == "note"]
    assert len(alive) == 1, (
        "a well-behaved collector between two raising ones must still contribute; "
        f"signals={snapshot.signals!r}"
    )

    warnings = _cli_warnings(caplog)
    assert len(warnings) == 2, (
        "two distinct raising collectors must each be isolated -> two WARNINGs; "
        f"got {[r.getMessage() for r in warnings]}"
    )
    messages = " || ".join(r.getMessage() for r in warnings)
    assert "boom_a" in messages, f"first raiser not named in warnings: {messages!r}"
    assert "boom_b" in messages, f"second raiser not named in warnings: {messages!r}"


# ===========================================================================
# Behavior 5 --- End-to-end: a raising collector does NOT crash a front-door
# verb. `pla scan` (offline scripted provider) completes on the surviving
# signals -> exit 0 and the --out slate file is written.
# ===========================================================================


def test_b05_raising_collector_does_not_crash_scan(tmp_path, monkeypatch):
    # RecentFilesCollector() is allowed by the spec; the well-behaved double is
    # equally valid and fully deterministic (no filesystem dependency), so use it.
    monkeypatch.setattr(
        cli,
        "all_collectors",
        lambda: [_RaisingCollector("boom"), _WellBehavedCollector()],
    )

    ws = tmp_path / "ws"
    ws.mkdir()
    out_path = tmp_path / "slate.json"

    rc = main([
        "scan",
        "--workspace", str(ws),
        "--provider", "scripted",
        "--scripted-responses", str(SCRIPT),
        "--state-dir", str(tmp_path / "state"),
        "--out", str(out_path),
    ])

    assert rc == 0, (
        "a raising collector must not crash the scan verb; it should degrade to "
        f"the surviving signals and exit 0 (got rc={rc})"
    )
    assert out_path.is_file(), "scan must still write its --out slate file"


# ===========================================================================
# Behavior 6 --- No regression / invisible on the happy path: with the REAL
# registry (no monkeypatch) _collect returns a snapshot and emits NO WARNING on
# the cli logger (the guard is a no-op when nothing raises).
# ===========================================================================


def test_b06_no_warning_on_real_registry_happy_path(tmp_path, caplog):
    # A realistic, benign workspace: one source file, no .git.
    (tmp_path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    caplog.set_level(logging.WARNING, logger=_CLI_LOGGER)

    snapshot = cli._collect(tmp_path)

    assert isinstance(snapshot, WorkspaceSnapshot)
    assert snapshot.root == str(tmp_path)
    # No built-in collector raises today, so the guard stays silent.
    assert _cli_warnings(caplog) == [], (
        "the guard must be invisible on the happy path (no built-in collector "
        f"raises); got {[r.getMessage() for r in _cli_warnings(caplog)]}"
    )
