"""Collector protocol: the shared contract every collector must satisfy.

All collectors are pure-stdlib and deterministic. They MUST NOT raise
exceptions on missing directories or unavailable tools — degrade to [].
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable

from proactive_loop.models import ContextSignal

# WHY a module logger and not the CLI's: this module owns BOTH absorbing points in
# the perception layer -- the fail-open `collect` wrapper every SHIPPED collector
# inherits, and the aggregated per-manifest record in `_log_absorbed` -- and it lives
# in the library half of the package, so each record must be attributable to
# `proactive_loop.collectors.base` and governed by the package-logger plumbing in
# `cli._configure_logging` -- never emitted on the root logger, which would leak into
# an embedding application's own handlers. ONE logger for both is load-bearing, not
# incidental: `_log_absorbed`'s own argument turns on an operator who filters this
# logger also silencing the boundary WARNING, which is literal only while they share
# it.
_LOG = logging.getLogger(__name__)

# The opt-in record of ABSORBED failures: a STACK of sinks, each one a list of the
# class names `collect` degraded during the scope that owns it. Empty by default, so
# a library embedder, `scan`, `run` and `watch` all keep the exact fail-open path
# they had -- recording happens only inside `record_degradations()`.
#
# WHY a module-level stack and not an attribute on `BaseCollector`: this class's own
# docstring forbids adding any ANNOTATED class attribute (it would contribute a field
# to all 17 generated dataclass `__init__` signatures and reorder them), and the
# alternative -- threading an out-parameter through the CLI's `_collect` loop -- would
# widen a seam shared by four verbs for a diagnostic that one verb consumes.
_DEGRADED_SINKS: list[list[str]] = []


@contextmanager
def record_degradations() -> Iterator[list[str]]:
    """Record the class name of every collector failure ABSORBED inside this scope.

    Fail-open is the right contract for a SCAN -- one unreadable tree must never abort
    perception -- and the wrong answer for a GATE. A caller that asks "is kind K absent
    from this workspace?" cannot be told "absent" by a collector that crashed before it
    looked; the two readings are only distinguishable if the absorbed failure is
    recoverable by the caller. ``collect`` already LOGS it, but a log record is not a
    value: at default verbosity -- the verbosity every CI step and pre-commit hook
    actually runs -- ``cli._configure_logging`` attaches no handler and sets no level, so
    a consumer that rode logging config would work under ``-v`` and be blind by default.
    This scope is level-independent for exactly that reason.

    Yields the sink list itself, which is APPENDED to (never replaced) as failures are
    absorbed, so the caller reads it after the scan: one entry per absorbed failure, in
    the order they happened, with repeats preserved (a collector that fails twice is
    recorded twice -- de-duplication is the consumer's policy, not this scope's).

    Nests: an inner scope does not hide a failure from an outer one, because every armed
    sink receives every record. Deliberately NOT thread-safe and not async-aware; the
    product is a single-threaded, deterministic CLI, and a lock here would buy nothing
    that the suite could observe.
    """
    sink: list[str] = []
    _DEGRADED_SINKS.append(sink)
    try:
        yield sink
    finally:
        # `pop()`, never `remove(sink)`: `list.remove` matches by EQUALITY, and two
        # empty sinks compare equal, so a nested scope would pop the OUTER one and leak
        # the inner. `finally` guarantees LIFO unwinding, which makes the stack
        # discipline exact.
        _DEGRADED_SINKS.pop()


@runtime_checkable
class Collector(Protocol):
    """Protocol that every context collector must implement.

    WHY a Protocol instead of an ABC: collectors can be simple dataclasses or
    plain objects; they just need a name attribute and a collect method.
    """

    name: str

    def collect(self, root: Path) -> list[ContextSignal]:
        """Scan *root* and return zero or more context signals.

        Implementations must never raise — any error should be swallowed
        and an empty list returned so the scout scan continues uninterrupted.
        """
        ...


class BaseCollector:
    """Concrete base that IMPLEMENTS the never-raise half of the Collector contract.

    WHY this exists next to the Protocol above: a ``Protocol`` can state a rule but
    cannot supply behavior, so before this class the fail-open invariant was asserted
    once and guaranteed zero times -- every collector hand-copied the identical
    ``try/except Exception -> []`` wrapper, and the 17th collector was one forgotten
    ``try`` away from aborting an entire ``pla scan`` sweep. Hosting the wrapper here
    makes the invariant hold for every present and future collector by construction.

    WHY a plain class and NOT a dataclass, an ABC, or a decorator:

    * Every collector is a ``@dataclass`` declaring ``name: str = "<literal>"`` -- a
      DEFAULTED field -- while the Protocol above declares ``name: str`` UNDEFAULTED.
      A base that carried ANY annotated class attribute would contribute a field to
      all 17 generated ``__init__`` signatures and reorder them, which surfaces as a
      constructor error rather than as a refactor. Declaring only methods means this
      class has no ``__dataclass_fields__`` at all, so ``dataclasses.fields()`` order
      and no-argument construction are provably untouched.
    * Not an ABC: ``_collect`` raising ``NotImplementedError`` is swallowed by
      ``collect`` like any other exception, so a subclass that forgets ``_collect``
      degrades to ``[]`` instead of crashing a scan. That is the fail-open behavior
      this layer wants; the drift guard in the test suite, not a runtime crash, is
      what catches the omission.
    * Not a decorator: ``mypy strict`` runs with ``disallow_untyped_decorators``, and
      a base class is simpler to read than a correctly-typed generic decorator.

    It also hosts ``_relative`` and ``_log_absorbed`` for the same reason and by the
    same precedent: a path-shape rule every path-emitting collector must satisfy had
    been hand-copied into six of them, and the aggregated absorbed-failure record into
    two -- where the two copies' ~31-line docstrings had already DRIFTED apart while
    describing one contract, each naming its own item-cap field. Anything added here
    must stay a plain method or a ``staticmethod`` -- never an annotated attribute --
    for the dataclass reason above.

    Subclasses stay structurally compatible with ``Collector``: a ``runtime_checkable``
    Protocol is satisfied by an INHERITED ``collect``, so ``isinstance(c, Collector)``
    remains True.
    """

    def collect(self, root: Path) -> list[ContextSignal]:
        """Scan *root* and return zero or more context signals, never raising.

        This is the single implementation of the SPEC 4.1 fail-open rule: any error
        raised by the subclass's ``_collect`` degrades to ``[]`` so one unreadable
        tree, absent tool, or hostile file can never abort the scout scan. Collectors
        override ``_collect`` and are free to let errors escape it.

        WHY it also LOGS: fail-open is the right contract, but SILENT fail-open made a
        crashed collector indistinguishable from an empty scan on every surface the
        user has -- ``--timings`` prints the same ``0`` row either way, and the only
        collector-failure WARNING the product had (the containment branch in the
        CLI's ``_collect`` orchestration loop) is unreachable for every SHIPPED
        collector,
        because a ``BaseCollector`` subclass never lets ``collect`` raise. So the
        diagnostic belongs at the place that actually absorbs the failure. One record
        per absorbed failure, at WARNING so the operator who did not know to pass
        ``-v`` still sees it; the return value and the breadth of the ``except`` are
        deliberately unchanged.
        """
        try:
            return self._collect(root)
        except Exception as exc:  # noqa: BLE001 - deliberate: the SPEC 4.1 fail-open point
            # Not `_LOG.exception`: a traceback on stderr would read as a crash the
            # scan did not suffer, and at default verbosity this record rides Python's
            # `lastResort` handler, which prints the message alone. Class name over
            # `self.name` because a subclass that failed BEFORE setting up may not have
            # a meaningful name, and the class is what a bug report needs.
            _LOG.warning(
                "collector %s failed, degrading to no signals: %s",
                type(self).__name__,
                exc,
            )
            # The same fact as the WARNING above, handed back as a VALUE to any caller
            # that armed `record_degradations()` -- see that scope for why a log record
            # cannot serve a gate. Appended AFTER the log so the diagnostic ordering is
            # unchanged, and the class name is the same one the record names, so a
            # consumer can join the two. No-op when no sink is armed.
            for sink in _DEGRADED_SINKS:
                sink.append(type(self).__name__)
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Do the real collection for *root*; subclasses must override this.

        Deliberately raises instead of returning ``[]``: a silent empty result would
        make a subclass that forgot to override indistinguishable from one that found
        nothing. The raise is still swallowed by ``collect`` above, so the failure mode
        is a quiet empty scan rather than a crash.
        """
        raise NotImplementedError(f"{type(self).__name__} must override _collect()")

    def _log_absorbed(self: Collector, absorbed: list[str]) -> None:
        """Report the per-manifest failures this scan ABSORBED, or stay silent.

        WHY this exists at all: ``collect`` above logs the failure it absorbs, on the
        stated ground that a silent fail-open leaves a crashed collector
        indistinguishable from an empty scan on every surface the user has. A collector
        that guards each manifest INSIDE its own walk absorbs at a SECOND point, one
        scope IN from that boundary, and that point had no channel of any kind -- so a
        manifest that raises on parse or on ``stat`` read as "this collector found
        nothing" on every tick, forever.

        WHY the wording here is deliberately GENERIC, by ``_relative``'s precedent
        below: this is ONE shared contract, so it gets ONE implementation. It had been
        hand-copied into two collectors, and the two ~31-line docstrings describing it
        had already DRIFTED -- each naming its own item-cap field and its own reading of
        the silence -- so this text serves each subclass's own absorbed-failure
        behavior rather than any single one of them.

        WHY ONE AGGREGATED record per scan and never one per manifest: ``watch``
        re-scans on a timer, so a per-item record turns a tree with 50 unreadable
        manifests into 50 lines per tick, and the operator's first move is to filter
        this logger out -- which also suppresses the boundary WARNING in ``collect``
        above, leaving the product strictly worse off than the silence it replaced.
        Both absorbing points ride THIS module's logger, which is what makes that
        argument literally true rather than approximately true.

        WHY ``warning`` and not ``exception``, by ``collect``'s precedent: a traceback
        on stderr would read as a crash the scan did not suffer, and at default
        verbosity a WARNING rides Python's ``lastResort`` handler, so an operator who
        did not know to pass ``-v`` still sees it.

        WHY ``min()`` and not the encounter order: ``dir_source.walk`` order is not
        guaranteed across platforms -- the same reason callers sort their own results
        before returning -- so the named path is the lexicographically smallest
        affected manifest and the message is reproducible rather than walk-dependent.

        WHY callers emit this BEFORE applying their own item cap: the count is a count
        of ABSORBED FAILURES, not of returned signals, so a cap that truncates the
        result must never truncate the diagnostic.

        WHY ``self`` is annotated as the ``Collector`` Protocol above and NOT as
        ``BaseCollector``: the record names ``self.name``, while this class
        deliberately declares no attributes at all -- an annotated one would inject a
        dataclass field into all 17 generated ``__init__`` signatures, a defect the
        class docstring warns about and the suite keeps a drift guard for. So the
        precondition is stated where it belongs, in the signature: this helper is
        meaningful on anything satisfying ``Collector``, which is exactly what supplies
        ``name``. Under ``mypy strict`` a bare ``self`` here is an error, so the
        alternatives were the class attribute this class forbids or a ``getattr``
        fallback inventing a second, untested name for the record.
        """
        if not absorbed:
            return
        _LOG.warning(
            "collector %s absorbed %d manifest failure(s) this scan; "
            "lowest-sorting affected manifest: %s",
            self.name,
            len(absorbed),
            min(absorbed),
        )

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        """Render *path* as a workspace-relative, forward-slashed string.

        Every path-emitting collector must publish ``ContextSignal.path`` in exactly
        this shape -- relative to the scanned root and POSIX-separated -- so a slate
        reads and diffs identically whichever platform produced it. That is ONE
        invariant, so it gets ONE implementation: it was previously hand-copied into
        six collectors whose docstrings cited FOUR different SPEC behavior numbers for
        the same three lines, which is why the wording here is deliberately generic --
        it serves each subclass's own path-shape behavior, not any single one of them.

        WHY the fallback instead of letting ``ValueError`` escape: callers pass the
        absolute results of a directory walk, so a path that lands outside *root*
        (a symlink target, a caller-supplied absolute path) must still be reported.
        Raising here would be swallowed by ``collect`` above and would silently empty
        the whole collector rather than degrade one signal.
        """
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.as_posix()
