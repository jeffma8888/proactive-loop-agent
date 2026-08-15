"""Collector protocol: the shared contract every collector must satisfy.

All collectors are pure-stdlib and deterministic. They MUST NOT raise
exceptions on missing directories or unavailable tools — degrade to [].
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from proactive_loop.models import ContextSignal

# WHY a module logger and not the CLI's: this wrapper is the fail-open point for
# every SHIPPED collector, and it lives in the library half of the package, so the
# record must be attributable to `proactive_loop.collectors.base` and governed by
# the package-logger plumbing in `cli._configure_logging` -- never emitted on the
# root logger, which would leak into an embedding application's own handlers.
_LOG = logging.getLogger(__name__)


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
      all 16 generated ``__init__`` signatures and reorder them, which surfaces as a
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

    It also hosts ``_relative`` for the same reason and by the same precedent: a
    path-shape rule every path-emitting collector must satisfy had been hand-copied
    into six of them. Anything added here must stay a plain method or a
    ``staticmethod`` -- never an annotated attribute -- for the dataclass reason above.

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
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Do the real collection for *root*; subclasses must override this.

        Deliberately raises instead of returning ``[]``: a silent empty result would
        make a subclass that forgot to override indistinguishable from one that found
        nothing. The raise is still swallowed by ``collect`` above, so the failure mode
        is a quiet empty scan rather than a crash.
        """
        raise NotImplementedError(f"{type(self).__name__} must override _collect()")

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
