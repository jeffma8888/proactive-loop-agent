"""Autonomy-contract gate: decide how each candidate goal may be dispatched.

WHY a standalone, pure function: the gate is the safety boundary between goal
discovery (L2) and execution (L1). Keeping it a small, side-effect-free
function of (goal, settings) makes the autonomy rules auditable and trivially
testable — the whole contract is four ordered rules with no hidden state.
"""

from __future__ import annotations

from proactive_loop.config import Settings
from proactive_loop.models import AutonomyDecision, CandidateGoal, DispatchDecision, GoalSlate


def gate(goal: CandidateGoal, settings: Settings) -> DispatchDecision:
    """Apply the autonomy contract to one goal.

    Rules are evaluated IN ORDER; the first match wins. Order matters: a
    sensitive category ALWAYS needs approval, even at a maximal score and even
    when otherwise appropriate — the sensitivity check must precede both the
    appropriateness and the score checks.
    """
    if goal.category in settings.sensitive_categories:
        return DispatchDecision(
            goal_id=goal.id,
            decision=AutonomyDecision.NEEDS_APPROVAL,
            reason="sensitive category",
        )
    if not goal.appropriate_now:
        return DispatchDecision(
            goal_id=goal.id,
            decision=AutonomyDecision.BLOCKED,
            reason="not appropriate right now",
        )
    if goal.score >= settings.auto_dispatch_min_score:
        return DispatchDecision(
            goal_id=goal.id,
            decision=AutonomyDecision.AUTO_DISPATCH,
            reason="score meets auto-dispatch threshold",
        )
    return DispatchDecision(
        goal_id=goal.id,
        decision=AutonomyDecision.NEEDS_APPROVAL,
        reason="below auto-dispatch threshold",
    )


def gate_slate(slate: GoalSlate, settings: Settings) -> list[DispatchDecision]:
    """Gate every goal in a slate, in ranked (display) order.

    WHY ranked order: decisions line up with how the slate is presented to the
    user, so the top AUTO_DISPATCH candidate is the first actionable row.
    """
    return [gate(goal, settings) for goal in slate.ranked()]
