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
