"""Black-box behavior tests for state-dir iteration 165 (ships as ``factory iter 170``):
``pla signals --fail-on-kind K`` FAILS CLOSED when the collector that owns armed
kind ``K`` degraded during the scan.

SPEC 4.1 fail-open is right for a SCAN and wrong for a GATE.  A collector whose
``_collect`` hook raised cannot distinguish "kind K is absent from this
workspace" from "I never looked", yet until this iteration the gate answered
"absent": exit 0, the kind missing from stdout, and one WARNING nobody reads.
This iteration converts exactly that false green into exit ``1`` plus ONE
``error: `` line on stderr naming the degraded collector's REGISTRY name and the
armed kind it owns.  Every outcome that is already non-zero stays byte-identical.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. Anti-vacuity control -- the existing gate still trips: healthy owner + a live
   finding -> exit 5, the existing ``gate: fail-on-kind tripped -- K=<count>``
   line, no ``error:`` line.  Without this, behavior 2 could pass on a fixture
   that never armed a live gate.
2. The hole is closed: same workspace and command with the owner DEGRADED ->
   exit 1 and exactly ONE ``error: `` line naming the REGISTRY name (``todos``)
   -- never the class name (``TodoCollector``) -- together with the armed kind
   it owns, and no ``gate: fail-on-kind tripped`` line.  Two degraded owners of
   two armed kinds are reported on that SAME single line, ascending by registry
   name.
3. An unarmed degradation cannot red a build: armed on a kind whose healthy
   owner finds nothing while the owner of an UNARMED kind is degraded -> exit 0,
   no ``error:`` line.
4. No gate armed means no new behavior: a degraded collector and no
   ``--fail-on-kind`` -> exit 0, no ``error:`` line, and the pre-existing
   ``collector ... failed, degrading to no signals:`` WARNING still present.
5. A real finding still owns the report: kind A healthy with a finding + kind B's
   owner degraded -> exit 5, only the existing gate line for A, no degradation
   line.
6. Verbosity-invariant: the behavior-2 invocation exits 1 and prints a BYTE-
   IDENTICAL ``error: `` line at default verbosity, under ``-v`` and under
   ``-vv``.  Default verbosity is the trap -- it is what every CI step and hook
   uses, and it is where ``_configure_logging`` is a strict no-op.
7. Isolation: this module drives ``main([... '-v'])`` in-process, and the CLI's
   logging setup attaches a ``StreamHandler`` to the CURRENT ``sys.stderr``, so
   without restoration it would leave a handler bound to a torn-down stream on
   the process-global ``proactive_loop`` logger and poison later modules.  The
   autouse ``_restore_package_logger`` fixture below (copied from
   ``tests/test_iter25_behavior.py``) snapshots and restores handlers + level;
   ``test_b07_*`` MEASURES that the hazard is real and that the snapshot round
   trips, rather than asserting the fixture exists.

ISOLATION CONTRACT honored: every expectation below is taken from this
iteration's ``pm.md`` "Expected Behaviors", the shipped ``pla signals --help``
text, output obtained by RUNNING the product, and the conventions of existing
modules under ``tests/`` (``test_iter169_behavior.py`` for the raising-hook
shape, ``test_iter25_behavior.py`` for the logger fixture, ``test_iter145/147``
for the gate-line regex).  **No file under ``src/`` was read, no engineer or
reviewer note was opened, and no ``git diff`` was consulted.**  Collector classes
are reached through the public ``all_collectors()`` registry and ``type()``, not
by importing private module paths, so no assertion hardcodes the private
kind -> collector map.

Fully offline and deterministic: ``tmp_path`` trees only (never the in-repo tree,
so no collector can leak repo state), no network, no API key, no ``git``
subprocess, and no duration is asserted anywhere.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from proactive_loop.cli import main
from proactive_loop.collectors import all_collectors

_PACKAGE = "proactive_loop"

# Distinctive detonation text, so nothing matches by accident.
_BOOM = "iter170 probe detonated"

# The gate line this feature must NOT emit when it fails closed, and MUST leave
# untouched everywhere else (shape pinned by test_iter145_behavior.py).
_GATE_RE = re.compile(r"^gate: fail-on-kind tripped -- (.+)$")
_ERROR_PREFIX = "error: "

# Kinds used as fixtures, derived below against the live registry so a rename
# fails loudly instead of silently skipping.
_TODO_KIND = "todo"
_SECRET_KIND = "secret_file"
_LICENSE_KIND = "license"
_NOTE_KIND = "note"


# ---------------------------------------------------------------------------
# Isolation fixture (copied from tests/test_iter25_behavior.py) + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_package_logger() -> Iterator[logging.Logger]:
    """Snapshot + restore the package logger so no test leaks logging state
    (a stderr handler bound to a torn-down capsys stream is the hazard)."""
    logger = logging.getLogger(_PACKAGE)
    saved_handlers = list(logger.handlers)
    saved_level = logger.level
    try:
        yield logger
    finally:
        for h in list(logger.handlers):
            if h not in saved_handlers:
                logger.removeHandler(h)
        logger.handlers[:] = saved_handlers
        logger.setLevel(saved_level)


_TIMINGS_ROW_PREFIX = "  "
_TIMINGS_TOTAL = "TOTAL"

# Cache: the kind -> owning-registry-name map is a property of the shipped
# registry, not of any workspace, so it is derived at most once per kind.
_OWNER_CACHE: dict[str, str] = {}


def _registry_name(kind: str, ws: Path) -> str:
    """The registry name of the collector that owns ``kind``, derived BLACK-BOX.

    ``--kind K`` is documented as an UPSTREAM filter -- "only the collector that
    emits this kind is run, so --timings shows one row" -- so the one non-TOTAL
    row of the ``--timings`` table on stderr IS the owner.  Deriving it this way
    rather than importing the private kind -> collector map keeps the module on
    the public surface and lets a future re-homing of a kind move these tests
    with it instead of breaking them.
    """
    if kind not in _OWNER_CACHE:
        code, err = _run(_signals(ws, "--kind", kind, "--timings"))
        assert code in (0, 5), (code, err)
        rows = [
            line.split()[0]
            for line in err.splitlines()
            if line.startswith(_TIMINGS_ROW_PREFIX) and line.split()
        ]
        owners = [name for name in rows if name != _TIMINGS_TOTAL]
        assert len(owners) == 1, f"expected one owner row for {kind!r}, got {rows}"
        _OWNER_CACHE[kind] = owners[0]
    return _OWNER_CACHE[kind]


def _owner_class(kind: str, ws: Path) -> type:
    """The CLASS of the collector that owns ``kind``.

    The class, not an instance: ``all_collectors()`` hands back FRESH instances
    per call, so swapping a hook on an instance this module happens to hold would
    never reach the list the CLI builds for itself.
    """
    name = _registry_name(kind, ws)
    owners = [type(c) for c in all_collectors() if c.name == name]
    assert len(owners) == 1, f"expected one registry entry named {name!r}"
    return owners[0]


def _raiser(self: object, root: Path) -> list[object]:
    """Stand in for a collector's ``_collect`` hook and blow up.

    Bound on the CLASS (see ``_owner_class``), so it DOES receive ``self``.
    """
    raise RuntimeError(_BOOM)


def _degrade(monkeypatch: pytest.MonkeyPatch, ws: Path, *kinds: str) -> None:
    """Make the owner of each ``kind`` degrade, exactly as the spec defines it."""
    for kind in kinds:
        monkeypatch.setattr(_owner_class(kind, ws), "_collect", _raiser)


def _workspace(tmp_path: Path, *, todo: bool = True) -> Path:
    """A synthetic workspace: one file, optionally carrying one TODO.

    Deterministic by construction -- it is not a git repo, holds no secret-shaped
    file, and has no LICENSE, so ``license`` always reports exactly one signal.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    body = "# TODO: wire the gate\n" if todo else "value = 1\n"
    (ws / "app.py").write_text(body, encoding="utf-8")
    return ws


def _run(argv: list[str]) -> tuple[int, str]:
    """Drive the CLI in-process, returning ``(exit_code, stderr)``.

    stderr is captured with ``redirect_stderr`` rather than ``capsys`` so the
    verbosity comparison in behavior 6 gets three independent buffers inside one
    test without a fixture boundary in between.
    """
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        code = main(argv)
    return code, buf.getvalue()


def _signals(ws: Path, *extra: str) -> list[str]:
    return ["signals", "--workspace", str(ws), *extra]


def _error_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith(_ERROR_PREFIX)]


def _gate_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if _GATE_RE.match(line)]


def _degradation_records(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The pre-existing fail-open WARNINGs, read off the RECORDS not off stderr.

    Deliberate, and the repo's own convention (``test_iter169_behavior.py``): at
    default verbosity the CLI attaches NO handler, so whether that warning reaches
    stderr at all depends on ``logging.lastResort`` and on whatever handler the
    test runner happens to have installed.  The record is the product's output;
    the stderr rendering is the runner's.
    """
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and (record.name == _PACKAGE or record.name.startswith(_PACKAGE + "."))
        and "degrading to no signals" in record.getMessage()
    ]


# ---------------------------------------------------------------------------
# Behavior 1 -- anti-vacuity control: the existing gate still trips
# ---------------------------------------------------------------------------


def test_b01_healthy_owner_with_a_finding_still_trips_the_gate(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(tmp_path)
    caplog.set_level(logging.WARNING, logger=_PACKAGE)
    code, err = _run(_signals(ws, "--fail-on-kind", _TODO_KIND))

    assert code == 5, err
    assert _gate_lines(err) == [f"gate: fail-on-kind tripped -- {_TODO_KIND}=1"], err
    assert _error_lines(err) == [], err
    assert _degradation_records(caplog) == [], err


# ---------------------------------------------------------------------------
# Behavior 2 -- the hole is closed
# ---------------------------------------------------------------------------


def test_b02_degraded_owner_of_armed_kind_exits_one_with_one_error_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(tmp_path)
    caplog.set_level(logging.WARNING, logger=_PACKAGE)
    owner_class = _owner_class(_TODO_KIND, ws)
    registry_name = _registry_name(_TODO_KIND, ws)
    _degrade(monkeypatch, ws, _TODO_KIND)

    code, err = _run(_signals(ws, "--fail-on-kind", _TODO_KIND))

    assert code == 1, err
    errors = _error_lines(err)
    assert len(errors) == 1, err
    line = errors[0]
    # The REGISTRY name, as a whole token -- 'todos' must not be satisfied by a
    # bare substring of some other word, and the armed kind must be named too.
    assert re.search(rf"(?<![a-z_]){re.escape(registry_name)}(?![a-z_])", line), line
    assert re.search(rf"(?<![a-z_]){re.escape(_TODO_KIND)}(?![a-z_])", line), line
    # ... and NOT the class name (todos, not TodoCollector).
    assert owner_class.__name__ not in line, line
    # A gate that fails closed must not also claim it tripped on a count.
    assert _gate_lines(err) == [], err
    # The pre-existing fail-open WARNING is untouched.
    assert len(_degradation_records(caplog)) == 1, caplog.text


def test_b02_two_degraded_owners_share_one_line_ascending_by_registry_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path)
    first, second = sorted(
        (_registry_name(_TODO_KIND, ws), _registry_name(_SECRET_KIND, ws))
    )
    _degrade(monkeypatch, ws, _TODO_KIND, _SECRET_KIND)

    code, err = _run(
        _signals(ws, "--fail-on-kind", _TODO_KIND, "--fail-on-kind", _SECRET_KIND)
    )

    assert code == 1, err
    errors = _error_lines(err)
    assert len(errors) == 1, err
    line = errors[0]
    assert first in line and second in line, line
    assert line.index(first) < line.index(second), line
    assert _gate_lines(err) == [], err


# ---------------------------------------------------------------------------
# Behavior 3 -- an unarmed degradation cannot red a build
# ---------------------------------------------------------------------------


def test_b03_degraded_owner_of_an_unarmed_kind_stays_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(tmp_path, todo=False)
    caplog.set_level(logging.WARNING, logger=_PACKAGE)
    _degrade(monkeypatch, ws, _NOTE_KIND)

    # Armed on a kind whose owner is HEALTHY and finds nothing here.
    code, err = _run(_signals(ws, "--fail-on-kind", _SECRET_KIND))

    assert code == 0, err
    assert _error_lines(err) == [], err
    assert _gate_lines(err) == [], err
    # Still visible as a warning -- iter-169's behavior is not being undone.
    assert len(_degradation_records(caplog)) == 1, caplog.text


# ---------------------------------------------------------------------------
# Behavior 4 -- no gate armed means no new behavior
# ---------------------------------------------------------------------------


def test_b04_no_gate_armed_leaves_a_degraded_scan_at_exit_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ws = _workspace(tmp_path)
    caplog.set_level(logging.WARNING, logger=_PACKAGE)
    _degrade(monkeypatch, ws, _TODO_KIND)

    code, err = _run(_signals(ws))

    assert code == 0, err
    assert _error_lines(err) == [], err
    assert len(_degradation_records(caplog)) == 1, caplog.text


# ---------------------------------------------------------------------------
# Behavior 5 -- a real finding still owns the report
# ---------------------------------------------------------------------------


def test_b05_a_live_finding_outranks_a_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ws = _workspace(tmp_path, todo=False)
    _degrade(monkeypatch, ws, _SECRET_KIND)

    code, err = _run(
        _signals(ws, "--fail-on-kind", _LICENSE_KIND, "--fail-on-kind", _SECRET_KIND)
    )

    assert code == 5, err
    assert _gate_lines(err) == [f"gate: fail-on-kind tripped -- {_LICENSE_KIND}=1"], err
    assert _error_lines(err) == [], err


# ---------------------------------------------------------------------------
# Behavior 6 -- verbosity-invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flags", [[], ["-v"], ["-vv"]], ids=["default", "-v", "-vv"])
def test_b06_error_line_is_verbosity_invariant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str]
) -> None:
    ws = _workspace(tmp_path)
    _degrade(monkeypatch, ws, _TODO_KIND)

    code, err = _run(_signals(ws, "--fail-on-kind", _TODO_KIND, *flags))

    assert code == 1, err
    assert len(_error_lines(err)) == 1, err


def test_b06_error_line_is_byte_identical_across_verbosities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same assertion as above, but comparing the three lines to each other.

    Parametrized cases cannot compare across themselves, and "identical" is the
    load-bearing half: a detector riding CLI logging config would emit under
    ``-v`` and go blind at the default verbosity every hook actually uses.
    """
    ws = _workspace(tmp_path)
    _degrade(monkeypatch, ws, _TODO_KIND)

    seen = []
    for flags in ([], ["-v"], ["-vv"]):
        code, err = _run(_signals(ws, "--fail-on-kind", _TODO_KIND, *flags))
        assert code == 1, err
        lines = _error_lines(err)
        assert len(lines) == 1, err
        seen.append(lines[0])

    assert seen[0] == seen[1] == seen[2], seen


# ---------------------------------------------------------------------------
# Behavior 7 -- isolation: the logging hazard is real and the fixture neutralizes it
# ---------------------------------------------------------------------------


def test_b07_a_dash_v_run_leaks_a_handler_that_the_snapshot_reverses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _restore_package_logger: logging.Logger,
) -> None:
    """The reason the autouse fixture is not optional, measured rather than quoted.

    A ``-v`` invocation attaches a handler to the process-global package logger
    that outlives the call; the buffer it points at dies with this test.  The
    snapshot-and-restore is what stops that dead handler reaching later modules,
    so the two-module ``-n 0`` run in the acceptance criteria stays green.
    """
    logger = _restore_package_logger
    before = list(logger.handlers)
    ws = _workspace(tmp_path)
    _degrade(monkeypatch, ws, _TODO_KIND)

    code, _ = _run(_signals(ws, "--fail-on-kind", _TODO_KIND, "-v"))
    assert code == 1

    after = list(logger.handlers)
    assert len(after) > len(before), (
        "expected the -v run to attach a handler to the package logger; if it no "
        "longer does, this module's autouse fixture has become dead weight and "
        "the spec's isolation note is stale"
    )
    # What the fixture does in its finally block, asserted to round-trip here.
    for handler in after:
        if handler not in before:
            logger.removeHandler(handler)
    assert logger.handlers == before


def test_b07_registry_class_names_are_unique(tmp_path: Path) -> None:
    """Pins the assumption the error line's naming rests on.

    Every collector is reported by its registry ``name``; the code that maps a
    degraded collector back to an armed kind can only be unambiguous if distinct
    collectors are distinct objects with distinct names.  Nothing else in the
    suite pins ``type(c).__name__`` uniqueness, so a future copy-paste of a
    collector class could silently make two rows indistinguishable.
    """
    collectors = all_collectors()
    class_names = [type(c).__name__ for c in collectors]
    registry_names = [c.name for c in collectors]

    assert len(set(class_names)) == len(class_names), sorted(class_names)
    assert len(set(registry_names)) == len(registry_names), sorted(registry_names)
