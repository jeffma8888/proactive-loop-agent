"""Domain models for the proactive loop agent.

These are the shared contract between the L2 scout (goal discovery), the
policy gate (autonomy contract), and the L1 goal loop (execution). Keeping
them in one dependency-free module lets every layer evolve independently.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, computed_field

# Public surface of this module, in DECLARATION order so the list doubles as a
# table of contents for the data contract. WHY it is kept ast-complete (every
# public top-level class/def, nothing more): the root package re-exports a
# curated SUBSET of this list, so a public model added here without an entry is
# a name that silently escapes the promised API -- the suite fails instead.
__all__ = [
    "GoalCategory",
    "AutonomyDecision",
    "RunStatus",
    "StepKind",
    "ContextSignal",
    "WorkspaceSnapshot",
    "CandidateGoal",
    "GoalSlate",
    "DispatchDecision",
    "LoopStep",
    "RunState",
    "ensure_dir",
    "atomic_write_text",
    "sanitize_validation_error",
]


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
        """Rank goals by (appropriate_now desc, score desc, id asc).

        Appropriate-now goals always rank above deferred ones, then by score.
        """
        # WHY: `id` (ascending) is a total tie-break so goals sharing the same
        # (appropriate_now, score) pair order deterministically by identity rather
        # than by the synthesizer's arbitrary emission order -- this makes the top
        # auto-dispatched goal a function of slate CONTENT, not slate LIST ORDER.
        return sorted(self.goals, key=lambda g: (not g.appropriate_now, -g.score, g.id))

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
    # L0 self-healing counter: incremented once per backoff-retry the executor
    # recovers from (via with_retry's on_retry hook). WHY it lives on the run:
    # "resilient by design" is the product's headline, but retries are silently
    # absorbed -- persisting the count makes that self-healing observable/auditable
    # instead of invisible. Defaulted to 0 so pre-iter-08 checkpoints (which lack
    # the key) still deserialize cleanly as a no-op; ge=0 since it only ever grows.
    retries: int = Field(default=0, ge=0)
    # L1 self-healing counter: incremented once per malformed PLAN/CHECK the
    # executor's fail-safe ABSORBS (keyed on the parse-failure flag, never on a
    # well-formed `done: false`). WHY it lives on the run: it is the persisted,
    # after-the-fact twin of the iter-68 live `L1 degraded ` WARNING -- a finished
    # BUDGET_EXHAUSTED checkpoint records `retries` (throttle pressure) but, without
    # this, says nothing about how many iterations the model burned emitting garbage,
    # so a post-mortem cannot tell "provider throttled me" from "model returned junk"
    # without re-reading a WARNING stream. Defaulted to 0 so pre-iter-69 checkpoints
    # (which lack the key) still deserialize cleanly as a no-op; ge=0 since it only
    # ever grows.
    parse_errors: int = Field(default=0, ge=0)
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


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* via a temp sibling and one ``os.replace``.

    WHY it lives here as ONE primitive: this is the L0 crash-safety invariant the
    product's vision promises ("atomic JSON checkpoints -> resumable runs"), and it
    used to be written out four times -- the checkpoint writer plus the CLI's slate,
    snapshot-document and meta writers. One guarantee with four copies has four
    places to drift and needs four oracles to prove one property, so the copies were
    unevenly proven; a reader asking "how does this project keep a crash from
    corrupting state?" should find one answer.

    Mechanism: write a SIBLING temp file in the destination's OWN directory, then one
    ``os.replace`` onto the target. Sibling placement is what holds the rename inside
    a single filesystem, where ``os.replace`` is atomic, so a reader sees either the
    previous bytes or the complete new ones -- never a half-written prefix. The parent
    chain is created on demand, so a fully-absent parent is legal.

    WHY the ``finally``: a raising swap must not leave a stray ``<name>.tmp`` behind in
    a directory the user chose or the product documents as a layout. Cleanup is
    best-effort and swallows its own ``OSError`` so the caller keeps seeing the PRIMARY
    failure, never a secondary error raised while tidying up. After a successful
    replace the temp name is already gone, so one ``finally`` covers both paths.
    """
    ensure_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def sanitize_validation_error(kind: str, path: Path, exc: ValidationError) -> str:
    """Reduce a pydantic ``ValidationError`` to one dependency-opaque line.

    WHY: ``model_validate_json`` on a corrupt slate/checkpoint otherwise leaks the
    vendor's multi-line dump onto the CLI's ``error:`` boundary -- the model class
    name, pydantic's ``[type=...]`` error taxonomy, a live ``errors.pydantic.dev/<ver>``
    URL that pins (and rots with) the dependency version, and a raw echo of the
    user's file bytes via ``input_value=``. On a PUBLIC repo that both fingerprints
    the dependency and prints file contents back to stderr, while every OTHER CLI
    fault already presents as ONE clean line. This names only the file, the pydantic
    error *count*, and the first error's *location* -- all safe scalars, none of the
    leaked fields.

    ``<loc>`` (the first error's ``loc`` tuple joined by ``.``, e.g. ``goals.0.impact``
    or ``status``) is appended only when non-empty; a malformed-JSON failure
    (``json_invalid``) carries an empty ``loc``, so its clause is omitted. Callers
    wrap the returned message in a plain ``ValueError`` so ``main()`` maps it to
    ``error: <msg>`` at exit 1 -- exit code and prefix unchanged (bug fix, not a
    versioned contract change).
    """
    count = exc.error_count()
    plural = "" if count == 1 else "s"
    msg = f"invalid {kind} file '{path}': {count} validation error{plural}"
    errors = exc.errors()
    if errors:
        loc = errors[0].get("loc") or ()
        if loc:
            msg += "; first at " + ".".join(str(part) for part in loc)
    return msg
