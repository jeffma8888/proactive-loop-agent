"""Collector protocol: the shared contract every collector must satisfy.

All collectors are pure-stdlib and deterministic. They MUST NOT raise
exceptions on missing directories or unavailable tools — degrade to [].
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from proactive_loop.models import ContextSignal


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
        """
        try:
            return self._collect(root)
        except Exception:
            return []

    def _collect(self, root: Path) -> list[ContextSignal]:
        """Do the real collection for *root*; subclasses must override this.

        Deliberately raises instead of returning ``[]``: a silent empty result would
        make a subclass that forgot to override indistinguishable from one that found
        nothing. The raise is still swallowed by ``collect`` above, so the failure mode
        is a quiet empty scan rather than a crash.
        """
        raise NotImplementedError(f"{type(self).__name__} must override _collect()")
