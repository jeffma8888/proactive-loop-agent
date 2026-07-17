"""Tests for the scout package: goal synthesis + the autonomy-contract gate.

Coverage:
- Synthesizer happy path with a ScriptedLLMClient (tag "synthesize"): valid
  goals are parsed, typed, and scored via the computed field.
- A malformed entry (bad category / out-of-range number / non-dict) is skipped
  without aborting the scan.
- Duplicate titles (case/whitespace-insensitive) collapse to one goal.
- Slate ranking: appropriate-now goals rank above deferred ones, then by score.
- Policy: a sensitive-category goal NEVER auto-dispatches, even at a maximal
  score; the auto-dispatch threshold boundary is inclusive; a not-appropriate
  goal is BLOCKED.

Everything runs fully offline — the only LLM is the scripted double.
"""

from __future__ import annotations

import json

from proactive_loop.config import Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.models import (
    AutonomyDecision,
    CandidateGoal,
    ContextSignal,
    GoalCategory,
    GoalSlate,
    WorkspaceSnapshot,
)
from proactive_loop.scout import (
    SYNTHESIZE_TAG,
    GoalSynthesizer,
    gate,
    gate_slate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot() -> WorkspaceSnapshot:
    """A small, representative snapshot spanning multiple signal kinds."""
    return WorkspaceSnapshot(
        root="/tmp/example-workspace",
        signals=[
            ContextSignal(
                source="recent_files",
                kind="recent_file",
                summary="edited agent.py 10 minutes ago",
            ),
            ContextSignal(
                source="todos",
                kind="todo",
                summary="TODO: add retry/backoff to the LLM client",
            ),
            ContextSignal(
                source="notes",
                kind="note",
                summary="journal: want to learn more about agentic loops",
            ),
        ],
    )


def _scripted(goals: list[dict]) -> ScriptedLLMClient:
    """A scripted client that replies to the synthesize call with `goals`."""
    payload = json.dumps(goals)
    return ScriptedLLMClient([{"tag": SYNTHESIZE_TAG, "text": payload}])


def _synthesizer(client: ScriptedLLMClient) -> GoalSynthesizer:
    return GoalSynthesizer(client=client, settings=Settings())


# ---------------------------------------------------------------------------
# Synthesizer: happy path
# ---------------------------------------------------------------------------


def test_synthesize_happy_path_parses_and_scores() -> None:
    """Valid entries become typed CandidateGoals with computed scores."""
    goals = [
        {
            "title": "Add retry/backoff to the LLM client",
            "rationale": "A TODO calls it out and it de-risks throttling.",
            "category": "project",
            "impact": 5.0,
            "urgency": 4.0,
            "confidence": 0.9,
            "effort_weight": 2.0,
            "appropriate_now": True,
            "sources": ["TODO: add retry/backoff to the LLM client"],
            "suggested_first_steps": ["Write with_retry() with exp backoff"],
        },
        {
            "title": "Study agentic loop patterns",
            "rationale": "Journal note shows active interest.",
            "category": "learning",
            "impact": 3.0,
            "urgency": 2.0,
            "confidence": 0.5,
            "effort_weight": 1.0,
            "appropriate_now": True,
            "sources": ["journal: want to learn more about agentic loops"],
            "suggested_first_steps": ["Read one paper on plan-act-check loops"],
        },
    ]
    client = _scripted(goals)
    slate = _synthesizer(client).synthesize(_snapshot())

    assert isinstance(slate, GoalSlate)
    assert slate.workspace_root == "/tmp/example-workspace"
    assert [g.title for g in slate.goals] == [
        "Add retry/backoff to the LLM client",
        "Study agentic loop patterns",
    ]
    # Score is a computed field: impact * urgency * confidence / effort_weight.
    assert slate.goals[0].score == 5.0 * 4.0 * 0.9 / 2.0  # 9.0
    assert slate.goals[1].score == 3.0 * 2.0 * 0.5 / 1.0  # 3.0
    assert slate.goals[0].category is GoalCategory.PROJECT
    assert slate.goals[1].category is GoalCategory.LEARNING

    # The synthesize call was routed under the expected tag.
    assert client.calls == [SYNTHESIZE_TAG]


def test_synthesize_tolerates_fences_and_prose() -> None:
    """parse_json_block strips ```json fences and surrounding prose."""
    payload = json.dumps(
        [
            {
                "title": "Ship the demo",
                "category": "project",
                "impact": 2.0,
                "urgency": 2.0,
                "confidence": 0.5,
                "effort_weight": 1.0,
                "appropriate_now": True,
            }
        ]
    )
    fenced = f"Here is your slate:\n```json\n{payload}\n```\nHope it helps!"
    client = ScriptedLLMClient([{"tag": SYNTHESIZE_TAG, "text": fenced}])
    slate = _synthesizer(client).synthesize(_snapshot())
    assert [g.title for g in slate.goals] == ["Ship the demo"]


# ---------------------------------------------------------------------------
# Synthesizer: robustness
# ---------------------------------------------------------------------------


def test_synthesize_skips_malformed_entries() -> None:
    """Bad entries are dropped; valid siblings still surface."""
    goals = [
        {  # valid
            "title": "Keep me",
            "category": "project",
            "impact": 2.0,
            "urgency": 2.0,
            "confidence": 0.5,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
        {  # invalid: category is not a GoalCategory value
            "title": "Bad category",
            "category": "not_a_real_category",
            "impact": 2.0,
            "urgency": 2.0,
            "confidence": 0.5,
            "effort_weight": 1.0,
        },
        {  # invalid: impact out of range (le=5.0)
            "title": "Impact too high",
            "category": "project",
            "impact": 99.0,
        },
        {  # invalid: missing required title
            "category": "project",
            "impact": 1.0,
        },
        "not even a dict",  # invalid: not an object
    ]
    client = _scripted(goals)  # type: ignore[arg-type]
    slate = _synthesizer(client).synthesize(_snapshot())
    assert [g.title for g in slate.goals] == ["Keep me"]


def test_synthesize_dedupes_by_normalized_title() -> None:
    """Titles differing only by case/whitespace collapse to the first seen."""
    goals = [
        {
            "title": "Build the scout",
            "category": "project",
            "impact": 5.0,
            "urgency": 5.0,
            "confidence": 1.0,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
        {
            "title": "  build THE scout  ",  # same normalized title
            "category": "project",
            "impact": 1.0,
            "urgency": 1.0,
            "confidence": 0.5,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
    ]
    client = _scripted(goals)
    slate = _synthesizer(client).synthesize(_snapshot())
    assert len(slate.goals) == 1
    # The first occurrence wins (its higher score is retained).
    assert slate.goals[0].title == "Build the scout"
    assert slate.goals[0].score == 25.0


def test_synthesize_unparseable_output_yields_empty_slate() -> None:
    """Non-JSON output is a valid (empty) outcome, not a crash."""
    client = ScriptedLLMClient([{"tag": SYNTHESIZE_TAG, "text": "sorry, no idea"}])
    slate = _synthesizer(client).synthesize(_snapshot())
    assert slate.goals == []
    assert slate.workspace_root == "/tmp/example-workspace"


# ---------------------------------------------------------------------------
# Slate ranking
# ---------------------------------------------------------------------------


def test_slate_ranking_appropriate_now_then_score() -> None:
    """ranked(): appropriate-now goals first, then by score descending."""
    goals = [
        {  # appropriate, low score
            "title": "Low but now",
            "category": "project",
            "impact": 1.0,
            "urgency": 1.0,
            "confidence": 0.5,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
        {  # deferred, very high score
            "title": "High but later",
            "category": "project",
            "impact": 5.0,
            "urgency": 5.0,
            "confidence": 1.0,
            "effort_weight": 1.0,
            "appropriate_now": False,
        },
        {  # appropriate, high score
            "title": "High and now",
            "category": "project",
            "impact": 5.0,
            "urgency": 4.0,
            "confidence": 1.0,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
    ]
    client = _scripted(goals)
    slate = _synthesizer(client).synthesize(_snapshot())
    ranked = slate.ranked()
    assert [g.title for g in ranked] == [
        "High and now",   # appropriate_now, score 20.0
        "Low but now",    # appropriate_now, score 0.5
        "High but later",  # deferred, score 25.0 but ranks last
    ]


# ---------------------------------------------------------------------------
# Policy gate
# ---------------------------------------------------------------------------


def test_gate_sensitive_never_auto_dispatches_even_at_max_score() -> None:
    """Rule 1 wins over score: sensitive category => NEEDS_APPROVAL."""
    settings = Settings()  # health_admin & finance_legal are sensitive by default
    goal = CandidateGoal(
        title="Sort out a medical claim",
        category=GoalCategory.HEALTH_ADMIN,
        impact=5.0,
        urgency=5.0,
        confidence=1.0,
        effort_weight=0.5,  # maximal score: 25 / 0.5 = 50.0
        appropriate_now=True,
    )
    assert goal.score == 50.0
    assert goal.score > settings.auto_dispatch_min_score
    decision = gate(goal, settings)
    assert decision.decision is AutonomyDecision.NEEDS_APPROVAL
    assert decision.reason == "sensitive category"
    assert decision.goal_id == goal.id


def test_gate_sensitivity_precedes_appropriateness() -> None:
    """A sensitive goal that is also deferred still reads as sensitive."""
    settings = Settings()
    goal = CandidateGoal(
        title="Review a legal document",
        category=GoalCategory.FINANCE_LEGAL,
        impact=3.0,
        urgency=3.0,
        confidence=0.8,
        effort_weight=1.0,
        appropriate_now=False,
    )
    decision = gate(goal, settings)
    assert decision.decision is AutonomyDecision.NEEDS_APPROVAL
    assert decision.reason == "sensitive category"


def test_gate_threshold_boundary_is_inclusive() -> None:
    """score >= auto_dispatch_min_score dispatches; strictly below does not."""
    settings = Settings()  # auto_dispatch_min_score default == 4.0

    at_threshold = CandidateGoal(
        title="Exactly at threshold",
        category=GoalCategory.PROJECT,
        impact=4.0,
        urgency=2.0,
        confidence=1.0,
        effort_weight=2.0,  # 4 * 2 * 1 / 2 == 4.0
        appropriate_now=True,
    )
    assert at_threshold.score == 4.0
    assert gate(at_threshold, settings).decision is AutonomyDecision.AUTO_DISPATCH

    just_below = CandidateGoal(
        title="Just below threshold",
        category=GoalCategory.PROJECT,
        impact=4.0,
        urgency=2.0,
        confidence=0.99,
        effort_weight=2.0,  # 4 * 2 * 0.99 / 2 == 3.96
        appropriate_now=True,
    )
    assert just_below.score < settings.auto_dispatch_min_score
    below = gate(just_below, settings)
    assert below.decision is AutonomyDecision.NEEDS_APPROVAL
    assert below.reason == "below auto-dispatch threshold"


def test_gate_blocked_when_not_appropriate_now() -> None:
    """A non-sensitive, deferred goal is BLOCKED regardless of score."""
    settings = Settings()
    goal = CandidateGoal(
        title="Big refactor, but not now",
        category=GoalCategory.PROJECT,
        impact=5.0,
        urgency=5.0,
        confidence=1.0,
        effort_weight=1.0,  # score 25.0 — would auto-dispatch if appropriate
        appropriate_now=False,
    )
    decision = gate(goal, settings)
    assert decision.decision is AutonomyDecision.BLOCKED


def test_gate_slate_returns_one_decision_per_goal_in_ranked_order() -> None:
    """gate_slate mirrors ranked() order and covers every goal once."""
    goals = [
        {
            "title": "Auto one",
            "category": "project",
            "impact": 5.0,
            "urgency": 5.0,
            "confidence": 1.0,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
        {
            "title": "Needs approval one",
            "category": "career",
            "impact": 1.0,
            "urgency": 1.0,
            "confidence": 0.5,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
        {
            "title": "Sensitive one",
            "category": "finance_legal",
            "impact": 5.0,
            "urgency": 5.0,
            "confidence": 1.0,
            "effort_weight": 1.0,
            "appropriate_now": True,
        },
        {
            "title": "Blocked one",
            "category": "maintenance",
            "impact": 5.0,
            "urgency": 5.0,
            "confidence": 1.0,
            "effort_weight": 1.0,
            "appropriate_now": False,
        },
    ]
    settings = Settings()
    slate = _synthesizer(_scripted(goals)).synthesize(_snapshot())
    decisions = gate_slate(slate, settings)

    # One decision per goal, aligned to ranked order.
    ranked_ids = [g.id for g in slate.ranked()]
    assert [d.goal_id for d in decisions] == ranked_ids
    assert len(decisions) == 4

    by_id = {d.goal_id: d.decision for d in decisions}
    titles = {g.id: g.title for g in slate.goals}
    outcomes = {titles[gid]: dec for gid, dec in by_id.items()}
    assert outcomes["Auto one"] is AutonomyDecision.AUTO_DISPATCH
    assert outcomes["Needs approval one"] is AutonomyDecision.NEEDS_APPROVAL
    assert outcomes["Sensitive one"] is AutonomyDecision.NEEDS_APPROVAL
    assert outcomes["Blocked one"] is AutonomyDecision.BLOCKED
