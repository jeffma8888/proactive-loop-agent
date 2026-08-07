"""proactive-loop-agent: a proactivity layer on top of goal-mode loop execution.

The root package IS the library surface. It re-exports the data contract -- the
pydantic models, the enums, and the two settings objects -- so an embedding host
can ``from proactive_loop import CandidateGoal, Settings`` and get full type
information from the shipped PEP 561 ``py.typed`` marker without reaching into
private module paths.

WHY the promise is data-only: every re-exported type defines part of the JSON
this system persists under the state dir, so it is already frozen by the
artifacts on disk -- promising it costs no future design freedom. Behavior entry
points (``GoalLoop``, ``GoalSynthesizer``, ``all_collectors``, ``gate`` /
``gate_slate``, ``main``) are deliberately NOT re-exported here; they stay
reachable at their sub-package paths, where a later iteration is still free to
move them.

WHY only ``.models`` and ``.config`` are imported, never ``.cli``: importing the
library must not drag in argparse or the console-script machinery, so
``import proactive_loop`` leaves ``proactive_loop.cli`` absent from
``sys.modules``.
"""

from __future__ import annotations

from .config import RetryPolicy, Settings
from .models import (
    AutonomyDecision,
    CandidateGoal,
    ContextSignal,
    DispatchDecision,
    GoalCategory,
    GoalSlate,
    LoopStep,
    RunState,
    RunStatus,
    StepKind,
    WorkspaceSnapshot,
)

__version__ = "0.1.1"

# Sorted, so the promised surface reads as a stable, diffable SET rather than an
# artifact of import order. ``__version__`` is intentionally absent: it is
# release metadata, not part of the typed data contract (and stays importable
# either way, since ``__all__`` only governs ``import *``).
__all__ = [
    "AutonomyDecision",
    "CandidateGoal",
    "ContextSignal",
    "DispatchDecision",
    "GoalCategory",
    "GoalSlate",
    "LoopStep",
    "RetryPolicy",
    "RunState",
    "RunStatus",
    "Settings",
    "StepKind",
    "WorkspaceSnapshot",
]
