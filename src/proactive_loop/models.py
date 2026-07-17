"""Domain models for the proactive loop agent.

These are the shared contract between the L2 scout (goal discovery), the
policy gate (autonomy contract), and the L1 goal loop (execution). Keeping
them in one dependency-free module lets every layer evolve independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, computed_field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class GoalCategory(str, Enum):
    """What kind of goal this is. Sensitive categories are gated by policy."""

    LEARNING = "learning"
    PROJECT = "project"
    CAREER = "career"
    MAINTENANCE = "maintenance"
    HEALTH_ADMIN = "health_admin"      # sensitive by default
    FINANCE_LEGAL = "finance_legal"    # sensitive by default


class AutonomyDecision(str, Enum):
    AUTO_DISPATCH = "auto_dispatch"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class StepKind(str, Enum):
    PLAN = "plan"
    ACT = "act"
    CHECK = "check"


class ContextSignal(BaseModel):
    """One observation about the user's working context, emitted by a collector."""

    source: str                      # collector name, e.g. "recent_files"
    kind: str                        # e.g. "recent_file" | "git_commit" | "todo" | "note"
    summary: str                     # one-line human-readable summary
    detail: str = ""                 # optional longer excerpt
    path: str | None = None          # file the signal came from, if any
    weight: float = 1.0              # collector-assigned relevance weight
    timestamp: datetime | None = None


class WorkspaceSnapshot(BaseModel):
    """Everything the scout knows about the workspace at scan time."""

    root: str
    collected_at: datetime = Field(default_factory=_now)
    signals: list[ContextSignal] = Field(default_factory=list)

    def by_kind(self) -> dict[str, list[ContextSignal]]:
        grouped: dict[str, list[ContextSignal]] = {}
        for signal in self.signals:
            grouped.setdefault(signal.kind, []).append(signal)
        return grouped


class CandidateGoal(BaseModel):
    """A recommended goal synthesized from context signals.

    Score is intentionally a *computed* field so ranking can never drift from
    its inputs: score = impact * urgency * confidence / effort_weight.
    """

    id: str = Field(default_factory=_new_id)
    title: str
    rationale: str = ""
    sources: list[str] = Field(default_factory=list)   # signal summaries / refs
    category: GoalCategory = GoalCategory.PROJECT
    impact: float = Field(default=1.0, ge=0.0, le=5.0)
    urgency: float = Field(default=1.0, ge=0.0, le=5.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    effort_weight: float = Field(default=1.0, ge=0.5)
    appropriate_now: bool = True
    suggested_first_steps: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score(self) -> float:
        return round(self.impact * self.urgency * self.confidence / self.effort_weight, 4)


class GoalSlate(BaseModel):
    """A ranked set of candidate goals for one scan of one workspace."""

    created_at: datetime = Field(default_factory=_now)
    workspace_root: str = ""
    goals: list[CandidateGoal] = Field(default_factory=list)

    def ranked(self) -> list[CandidateGoal]:
        """Appropriate-now goals always rank above deferred ones; then by score."""
        return sorted(self.goals, key=lambda g: (g.appropriate_now, g.score), reverse=True)

    def get(self, goal_id: str) -> CandidateGoal | None:
        return next((g for g in self.goals if g.id == goal_id), None)


class DispatchDecision(BaseModel):
    """Outcome of the autonomy-contract gate for one goal."""

    goal_id: str
    decision: AutonomyDecision
    reason: str = ""


class LoopStep(BaseModel):
    """One step (plan, act, or check) inside a goal-loop iteration."""

    index: int
    kind: StepKind
    output: str = ""                 # model text or tool observation
    done: bool = False               # only meaningful for CHECK steps
    artifacts: list[str] = Field(default_factory=list)


class RunState(BaseModel):
    """Checkpointable state of one goal-loop run. Atomic-saved after every step."""

    run_id: str = Field(default_factory=_new_id)
    goal: CandidateGoal
    status: RunStatus = RunStatus.PENDING
    steps: list[LoopStep] = Field(default_factory=list)
    iterations_used: int = 0
    llm_calls_used: int = 0
    artifacts_dir: str = ""
    created_at: datetime = Field(default_factory=_now)

    def next_step_index(self) -> int:
        return len(self.steps)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "RunState":
        return cls.model_validate_json(raw)


def ensure_dir(path: Path) -> Path:
    """Small shared helper: mkdir -p and return the path."""
    path.mkdir(parents=True, exist_ok=True)
    return path
