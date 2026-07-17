"""L1 goal-loop package: sandboxed tools, resilience, and the plan/act/check executor.

Re-exports the public surface so callers can ``from proactive_loop.loop import
GoalLoop, ToolRegistry, Checkpoint, with_retry`` without reaching into modules.
"""

from __future__ import annotations

from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.resilience import Checkpoint, with_retry
from proactive_loop.loop.tools import ToolRegistry

__all__ = [
    "GoalLoop",
    "ToolRegistry",
    "Checkpoint",
    "with_retry",
]
