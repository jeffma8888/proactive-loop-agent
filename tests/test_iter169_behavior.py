"""Black-box behavior tests for state-dir iteration 163 (ships as ``factory iter 169``):
L2 fail-open degradation becomes VISIBLE.

The perception layer's shared ``collect()`` wrapper already swallows any
exception a subclass's ``_collect`` hook raises and degrades to ``[]`` (the
SPEC 4.1 fail-open contract, pinned by ``tests/test_iter129_behavior.py``).
Until this iteration it did so in TOTAL SILENCE, so "this collector crashed"
was indistinguishable from "this collector found nothing" on every surface a
user has. This iteration adds exactly one default-level ``logging.WARNING``
inside that ``except`` branch, naming the failing subclass and the exception.

Coverage (numbered to match the iteration spec's Expected Behaviors):

1. Fail-open is UNCHANGED: a raising ``_collect`` still yields ``[]`` and no
   exception escapes ``collect(root)``.
2. That call emits EXACTLY ONE ``logging.WARNING`` whose message contains the
   raising subclass's class name and the ``str()`` of the exception. Asserted
   on the ``caplog`` RECORD, never on stderr text -- at default verbosity no
   handler is attached, so stderr would pin ``logging.lastResort``'s format
   rather than the product's.
3. The record rides a MODULE logger inside the ``proactive_loop`` package
   namespace (never the root logger), so the existing ``_configure_logging``
   package-logger plumbing governs it. The expected logger name is DERIVED at
   runtime from ``BaseCollector.__module__``, not hardcoded.
4. Anti-vacuity / two-sided: a HEALTHY subclass that returns a signal emits
   ZERO records at WARNING or above from the same call. Without this the
   behavior-2 assertions would also pass for a wrapper that warns
   unconditionally.
5. Derived over the LIVE registry, parametrized: for EVERY collector in
   ``all_collectors()``, forcing its ``_collect`` to raise yields ``[]`` PLUS
   exactly one WARNING naming that collector's OWN class. Not duplicate
   coverage of iter129, which asserts the return value and the no-raise
   property and never looks at a record.
6. Default verbosity on a HEALTHY scan is byte-unchanged: ``pla signals
   --workspace <tmp tree>`` as a SUBPROCESS with no ``-v`` exits 0 and writes
   ZERO lines to stderr, exactly as before this change.
7. Repeated failures are reported once EACH, not once per process: two
   ``collect()`` calls on a raising collector leave two records (no dedupe, no
   ``warnings``-module one-shot behavior).
8. ``_configure_logging``'s own docstring no longer claims the CLI seam is the
   only default emit site -- read via the shipped ``__doc__`` at runtime.

ISOLATION CONTRACT honored: every expectation below comes from this
iteration's ``pm.md`` "Expected Behaviors" plus the conventions of existing
modules under ``tests/`` (chiefly ``test_iter129_behavior.py`` for the
registry-parametrized ``_raiser`` shape, ``test_iter112_behavior.py`` for the
``caplog`` record filter, and ``test_iter138_behavior.py`` for the console-script
subprocess helper). No file under ``src/`` was read, no upstream stage note
(engineer/reviewer) was opened, and no ``git diff`` was consulted. Where the
shape of shipped output was needed it was obtained by RUNNING the installed
``pla`` console script and by runtime introspection of public attributes.

Fully offline and deterministic: ``tmp_path`` fixture trees only (never the
in-repo tree, so no collector can leak repo state), no network, no API key, no
``git`` subprocess, and no duration is asserted anywhere.
"""

from __future__ import annotations

import dataclasses
import logging
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from proactive_loop.collectors import all_collectors
from proactive_loop.collectors.base import BaseCollector, Collector
from proactive_loop.models import ContextSignal

# ---------------------------------------------------------------------------
# Registry-driven parameters (no hardcoded collector list) -- iter129's shape.
# ---------------------------------------------------------------------------

_INSTANCES = all_collectors()
_INSTANCE_PARAMS = [pytest.param(c, id=c.name) for c in _INSTANCES]

# Behavior 3: the logger the record must ride, DERIVED from the shipped module
# rather than spelled out, so the assertion survives a module rename.
_BASE_LOGGER = BaseCollector.__module__

_PACKAGE = "proactive_loop"

# Distinctive exception text, so behavior 2's containment check cannot pass by
# accident against some other diagnostic the scan happens to emit.
_BOOM = "iter169 probe detonated"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _raiser(root: Path) -> list[ContextSignal]:
    """Stand in for a collector's ``_collect`` hook and blow up.

    Bound as an INSTANCE attribute (iter129's established shape), so it shadows
    the class method WITHOUT descriptor binding: it takes ``root`` only and
    never receives ``self``.
    """
    raise RuntimeError(_BOOM)


def _package_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Records at WARNING or above emitted from inside the product's namespace.

    Filtered on the package prefix rather than one exact logger name so a
    warning from ANY product module is counted -- that is what makes behavior 4
    (zero records on a healthy call) a real anti-vacuity check instead of a
    check scoped to the one logger under test.
    """
    return [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and (record.name == _PACKAGE or record.name.startswith(_PACKAGE + "."))
    ]


def _messages(records: list[logging.LogRecord]) -> list[str]:
    return [record.getMessage() for record in records]


@dataclasses.dataclass
class _HealthyCollector(BaseCollector):
    """A well-behaved subclass: returns one real signal, raises nothing."""

    name: str = "iter169_healthy"

    def _collect(self, root: Path) -> list[ContextSignal]:
        return [
            ContextSignal(
                source=self.name,
                kind="note",
                summary="iter169 healthy probe signal",
            )
        ]


@dataclasses.dataclass
class _ExplodingCollector(BaseCollector):
    """A subclass whose hook raises, to exercise the fail-open ``except``."""

    name: str = "iter169_exploding"

    def _collect(self, root: Path) -> list[ContextSignal]:
        raise RuntimeError(_BOOM)


def _console_script() -> Path:
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, "the `pla` console script must be installed"
    return script


def _workspace(tmp_path: Path) -> Path:
    """A small, healthy, synthetic workspace -- never the in-repo tree."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "README.md").write_text("# probe\n\nA fixture workspace.\n", encoding="utf-8")
    (ws / "app.py").write_text("# TODO: wire retry\n\n\ndef main() -> None:\n    pass\n", encoding="utf-8")
    return ws


# ===========================================================================
# Behavior 1 -- the fail-open contract is unchanged.
# ===========================================================================


class TestFailOpenContractIsUnchanged:
    def test_b01_raising_hook_still_returns_empty_list(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        with caplog.at_level(logging.WARNING):
            result = collector.collect(tmp_path)
        assert result == [], f"fail-open must still yield []; got {result!r}"

    def test_b01_raising_hook_lets_nothing_escape_to_the_caller(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        try:
            with caplog.at_level(logging.WARNING):
                collector.collect(tmp_path)
        except Exception as exc:  # pragma: no cover -- the invariant's failure mode
            pytest.fail(f"collect() must never raise; it raised {exc!r}")


# ===========================================================================
# Behavior 2 -- exactly one WARNING, naming the class and the exception.
# ===========================================================================


class TestTheDegradationIsAnnounced:
    def test_b02_exactly_one_warning_is_emitted(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        with caplog.at_level(logging.WARNING):
            collector.collect(tmp_path)
        records = _package_warnings(caplog)
        assert len(records) == 1, (
            "a swallowed collector failure must announce itself exactly once; "
            f"got {len(records)} record(s): {_messages(records)!r}"
        )

    def test_b02_the_warning_names_the_failing_subclass(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        with caplog.at_level(logging.WARNING):
            collector.collect(tmp_path)
        message = _messages(_package_warnings(caplog))[0]
        assert type(collector).__name__ in message, (
            "the record must identify WHICH collector failed by class name; "
            f"{type(collector).__name__!r} absent from {message!r}"
        )

    def test_b02_the_warning_carries_the_exception_text(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        with caplog.at_level(logging.WARNING):
            collector.collect(tmp_path)
        message = _messages(_package_warnings(caplog))[0]
        assert _BOOM in message, (
            "the record must carry str(exception) so the failure is diagnosable; "
            f"{_BOOM!r} absent from {message!r}"
        )

    # Behavior 2, graded on the WORST input rather than the fixture's tidy one.
    # `str()` of a bare `OSError()` / `RecursionError()` / `RuntimeError()` /
    # `ValueError("")` is the EMPTY STRING -- and `os.walk` failures and recursion
    # guards are exactly the shapes this wrapper absorbs in production. The spec
    # only requires `str(exception)`, which the empty string satisfies trivially,
    # so this is deliberately NOT asserted as a defect. What IS asserted is the
    # half that must survive regardless: the record still exists, there is still
    # exactly one, and it still names WHICH collector degraded. See tester.md's
    # PM-feedback section for the measured renderings and the follow-up.
    @pytest.mark.parametrize(
        "exc",
        [
            pytest.param(RuntimeError(), id="RuntimeError-no-args"),
            pytest.param(OSError(), id="OSError-no-args"),
            pytest.param(ValueError(""), id="ValueError-empty-string"),
            pytest.param(RecursionError(), id="RecursionError-no-args"),
        ],
    )
    def test_b02_the_class_name_survives_an_empty_exception_message(
        self, exc: Exception, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        @dataclasses.dataclass
        class _SilentlyExplodingCollector(BaseCollector):
            name: str = "iter169_silent_boom"

            def _collect(self, root: Path) -> list[ContextSignal]:
                raise exc

        collector = _SilentlyExplodingCollector()
        with caplog.at_level(logging.WARNING):
            result = collector.collect(tmp_path)

        assert result == [], f"fail-open must hold for {type(exc).__name__}; got {result!r}"
        records = _package_warnings(caplog)
        assert len(records) == 1, (
            f"a {type(exc).__name__} with no message must still be announced exactly "
            f"once; got {len(records)}: {_messages(records)!r}"
        )
        message = records[0].getMessage()
        assert "_SilentlyExplodingCollector" in message, (
            "an exception whose str() is empty must not erase the collector's "
            f"identity from the record; got {message!r}"
        )

    def test_b02_the_record_is_a_warning_not_an_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Fail-open is a DEGRADATION, not a failure: the scan still succeeds, so
        # the level must be WARNING exactly -- ERROR would misreport a contained
        # condition, INFO/DEBUG would hide it at default verbosity.
        collector = _ExplodingCollector()
        with caplog.at_level(logging.DEBUG):
            collector.collect(tmp_path)
        levels = {
            record.levelno
            for record in caplog.records
            if record.name.startswith(_PACKAGE) and record.levelno >= logging.WARNING
        }
        assert levels == {logging.WARNING}, (
            f"expected exactly one WARNING-level record; levels seen: {sorted(levels)}"
        )


# ===========================================================================
# Behavior 3 -- a module logger inside the package namespace, never root.
# ===========================================================================


class TestTheRecordRidesThePackageLogger:
    def test_b03_logger_is_the_collectors_base_module_logger(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        with caplog.at_level(logging.WARNING):
            collector.collect(tmp_path)
        record = _package_warnings(caplog)[0]
        assert record.name == _BASE_LOGGER, (
            "the record must come from the wrapper's own module logger "
            f"({_BASE_LOGGER!r}), so `_configure_logging`'s package-logger "
            f"plumbing governs it; got {record.name!r}"
        )

    def test_b03_logger_is_never_the_root_logger(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        with caplog.at_level(logging.WARNING):
            collector.collect(tmp_path)
        names = {record.name for record in caplog.records}
        assert "root" not in names, (
            f"nothing may be logged on the root logger; names seen: {sorted(names)}"
        )
        assert names, "the degraded call must leave at least one record"
        assert all(name.startswith(_PACKAGE) for name in names), (
            f"every record must be inside the {_PACKAGE!r} namespace; got {sorted(names)}"
        )


# ===========================================================================
# Behavior 4 -- anti-vacuity: a healthy collector says NOTHING.
# ===========================================================================


class TestAHealthyCollectorIsSilent:
    def test_b04_healthy_subclass_emits_zero_warnings(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _HealthyCollector()
        with caplog.at_level(logging.WARNING):
            signals = collector.collect(tmp_path)
        assert len(signals) == 1, (
            "fixture defect, not a product failure: the healthy probe must "
            f"actually return a signal; got {signals!r}"
        )
        records = _package_warnings(caplog)
        assert records == [], (
            "a successful collect() must be silent, otherwise the new record "
            f"carries no information; got {_messages(records)!r}"
        )

    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_b04_every_shipped_collector_is_silent_on_a_clean_tree(
        self, collector: Collector, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The two-sided half of behavior 5: the shipped collectors must not warn
        # when they are working, on the same fixture tree behavior 5 blows up.
        ws = _workspace(tmp_path)
        with caplog.at_level(logging.WARNING):
            type(collector)().collect(ws)
        records = _package_warnings(caplog)
        assert records == [], (
            f"{type(collector).__name__} warned on a healthy scan: {_messages(records)!r}"
        )


# ===========================================================================
# Behavior 5 -- derived over the LIVE registry, one WARNING per collector.
# ===========================================================================


class TestEveryRegisteredCollectorAnnouncesItsOwnFailure:
    """Parametrized over ``all_collectors()`` at runtime -- never a hardcoded list."""

    def test_b05_the_registry_is_non_empty(self) -> None:
        # Guards the parametrization itself: an empty registry would make every
        # test in this class vacuously pass by generating zero cases.
        assert len(_INSTANCES) >= 2, (
            f"the live registry must supply real parameters; got {len(_INSTANCES)}"
        )

    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_b05_raising_collector_degrades_to_empty_and_warns_once(
        self,
        collector: Collector,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        instance = type(collector)()
        monkeypatch.setattr(instance, "_collect", _raiser)
        with caplog.at_level(logging.WARNING):
            result = instance.collect(tmp_path)

        assert result == [], (
            f"{type(collector).__name__} must still degrade to []; got {result!r}"
        )
        records = _package_warnings(caplog)
        assert len(records) == 1, (
            f"{type(collector).__name__} must announce its failure exactly once; "
            f"got {len(records)}: {_messages(records)!r}"
        )
        message = records[0].getMessage()
        assert type(collector).__name__ in message, (
            "the record must name the collector's OWN class, so the operator knows "
            f"which of {len(_INSTANCES)} collectors degraded; got {message!r}"
        )
        assert _BOOM in message, f"the exception text must survive; got {message!r}"
        assert records[0].name == _BASE_LOGGER, (
            f"expected logger {_BASE_LOGGER!r}; got {records[0].name!r}"
        )

    @pytest.mark.parametrize("collector", _INSTANCE_PARAMS)
    def test_b05_the_typing_contract_survives_the_forced_failure(
        self, collector: Collector, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instance = type(collector)()
        monkeypatch.setattr(instance, "_collect", _raiser)
        assert isinstance(instance, Collector), (
            f"{type(collector).__name__} must still satisfy the Collector protocol"
        )


# ===========================================================================
# Behavior 6 -- default verbosity on a HEALTHY scan is byte-unchanged.
# ===========================================================================


class TestDefaultVerbosityIsUnchanged:
    def test_b06_healthy_subprocess_scan_writes_nothing_to_stderr(
        self, tmp_path: Path
    ) -> None:
        ws = _workspace(tmp_path)
        proc = subprocess.run(
            [str(_console_script()), "signals", "--workspace", "."],
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, (
            f"a healthy scan must exit 0; got {proc.returncode}, stderr={proc.stderr!r}"
        )
        assert proc.stderr == "", (
            "adding a default-level WARNING must not make the HEALTHY path noisy; "
            f"stderr={proc.stderr!r}"
        )
        assert proc.stdout != "", "the healthy scan must still produce its report"

    def test_b06_the_same_scan_is_still_quiet_with_json(self, tmp_path: Path) -> None:
        ws = _workspace(tmp_path)
        proc = subprocess.run(
            [str(_console_script()), "signals", "--workspace", ".", "--json"],
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
        assert proc.stderr == "", f"stderr must stay empty; got {proc.stderr!r}"


# ===========================================================================
# Behavior 7 -- reported once EACH, not once per process.
# ===========================================================================


class TestRepeatedFailuresAreEachReported:
    def test_b07_two_calls_leave_two_records(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        collector = _ExplodingCollector()
        with caplog.at_level(logging.WARNING):
            first = collector.collect(tmp_path)
            second = collector.collect(tmp_path)
        assert first == [] and second == [], "both calls must degrade to []"
        records = _package_warnings(caplog)
        assert len(records) == 2, (
            "each swallowed failure must be reported -- a `warnings`-module-style "
            "once-per-process dedupe would hide a collector that fails on every "
            f"iteration of a long-running loop; got {len(records)}: {_messages(records)!r}"
        )

    def test_b07_two_distinct_collectors_are_each_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        first = _ExplodingCollector()
        second = type(_INSTANCES[0])()
        monkeypatch.setattr(second, "_collect", _raiser)
        with caplog.at_level(logging.WARNING):
            first.collect(tmp_path)
            second.collect(tmp_path)
        messages = _messages(_package_warnings(caplog))
        assert len(messages) == 2, f"expected one record each; got {messages!r}"
        assert type(first).__name__ in messages[0], f"got {messages[0]!r}"
        assert type(second).__name__ in messages[1], f"got {messages[1]!r}"


# ===========================================================================
# Behavior 8 -- the shipped prose no longer asserts the OLD topology.
# ===========================================================================


class TestTheShippedProseDescribesBothEmitSites:
    def test_b08_configure_logging_no_longer_claims_a_single_emit_site(self) -> None:
        import inspect

        from proactive_loop.cli import _configure_logging

        doc = inspect.cleandoc(_configure_logging.__doc__ or "")
        assert doc, "_configure_logging must keep its docstring"
        lowered = doc.lower()
        assert "the only default emit site" not in lowered, (
            "the docstring still claims the CLI seam is the ONLY default emit site, "
            "which this iteration made false"
        )
