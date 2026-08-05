"""Black-box behavior tests for iteration 76 (ships as commit-seq **factory iter
86**) --- ``GoalSlate.ranked()`` now applies a deterministic ascending-``id``
FINAL tie-break, so two goals that share the same ``(appropriate_now, score)``
pair are ordered by a total, input-order-INDEPENDENT rule instead of by the
synthesizer's arbitrary LLM emission order (ROADMAP row #86). This mirrors the
explicit-tie-break convention ``LargeFileCollector`` already documents
("descending byte size, ties broken by ascending relpath").

ISOLATION CONTRACT (honored): these tests were written strictly from this
iteration's public contract --- the spec's "Expected Behaviors" (``pm.md``),
``README.md``, ``ROADMAP.md`` --- and the model/gate conventions already public
in ``tests/test_scout.py`` (``test_slate_ranking_appropriate_now_then_score``,
``gate_slate``). They drive ONLY the public surface:
``GoalSlate.ranked()``, ``CandidateGoal(...)``, and ``scout.gate_slate(...)``.
**No file under ``src/`` was read, no engineer/reviewer note was read, and no
``git diff`` was consulted.** Every test is fully offline/deterministic: models
are constructed in memory (no LLM, no network, no filesystem). The score formula
(``round(impact*urgency*confidence/effort_weight, 4)``) and the fact that ``id``
is a settable field were confirmed by running the public constructor, never from
the implementation.
"""

from __future__ import annotations

import argparse

from proactive_loop.config import Settings
from proactive_loop.models import CandidateGoal, GoalCategory, GoalSlate
from proactive_loop.scout import gate_slate


# ---------------------------------------------------------------------------
# Helpers (public constructor only)
# ---------------------------------------------------------------------------


def _goal(
    gid: str,
    score: float,
    appropriate_now: bool,
    *,
    title: str | None = None,
    category: GoalCategory = GoalCategory.PROJECT,
) -> CandidateGoal:
    """Build a CandidateGoal with an explicit id and a target ``score``.

    ``score = round(impact*urgency*confidence/effort_weight, 4)`` where the
    model bounds each input (impact/urgency in [0, 5], confidence in [0, 1],
    effort_weight >= 0.5). We split the requested ``score`` into in-bounds
    ``impact*urgency`` (confidence=effort_weight=1.0), so any target in [0, 25]
    is reproduced exactly and two goals asking for the same target get an
    identical (byte-equal) score -> a genuine tie.
    """
    assert 0.0 <= score <= 25.0, "helper covers scores in [0, 25]"
    if score <= 5.0:
        impact, urgency = score, 1.0
    else:
        impact, urgency = 5.0, score / 5.0
    g = CandidateGoal(
        id=gid,
        title=title or f"goal-{gid}",
        category=category,
        impact=impact,
        urgency=urgency,
        confidence=1.0,
        effort_weight=1.0,
        appropriate_now=appropriate_now,
    )
    # Guard: our helper really does produce the score we asked for.
    assert g.score == round(score, 4)
    return g


# ---------------------------------------------------------------------------
# Behavior 1 --- backward-compatible primary/secondary order (distinct keys)
# ---------------------------------------------------------------------------


def test_b1_distinct_keys_primary_secondary_order_unchanged() -> None:
    """Mirrors the canonical test_slate_ranking shape: appropriate goals first
    (score-descending among them), deferred goal last regardless of its score."""
    hi_now = _goal("id_hi_now", 20.0, True, title="High and now")
    lo_now = _goal("id_lo_now", 0.5, True, title="Low but now")
    deferred = _goal("id_deferred", 25.0, False, title="High but later")

    ranked = GoalSlate(goals=[hi_now, lo_now, deferred]).ranked()

    assert [g.title for g in ranked] == [
        "High and now",   # appropriate_now, score 20.0
        "Low but now",    # appropriate_now, score 0.5
        "High but later",  # deferred, score 25.0 but ranks last
    ]


def test_b1_scores_are_as_expected() -> None:
    """Sanity-lock the score formula the ordering relies on."""
    assert _goal("x", 20.0, True).score == 20.0
    assert _goal("x", 0.5, True).score == 0.5
    assert _goal("x", 25.0, False).score == 25.0


# ---------------------------------------------------------------------------
# Behavior 2 --- deterministic ascending-id tie-break within a tie group
# ---------------------------------------------------------------------------


def test_b2_tie_group_orders_by_ascending_id() -> None:
    """Three appropriate goals, equal score, ids c/a/b (in a scrambled slate
    order) rank with ids strictly ascending a < b < c."""
    c = _goal("ccc", 1.0, True)
    a = _goal("aaa", 1.0, True)
    b = _goal("bbb", 1.0, True)
    # slate order deliberately NOT sorted:
    ranked = GoalSlate(goals=[c, a, b]).ranked()
    assert [g.id for g in ranked] == ["aaa", "bbb", "ccc"]


def test_b2_tie_break_is_ascending_not_descending() -> None:
    """DISCRIMINATING against a 'keep reverse=True, append id' bug, which would
    yield DESCENDING ids. Emit ids out of order; must come out ASCENDING."""
    ranked = GoalSlate(
        goals=[_goal("ccc", 2.0, True), _goal("aaa", 2.0, True), _goal("bbb", 2.0, True)]
    ).ranked()
    ids = [g.id for g in ranked]
    assert ids == ["aaa", "bbb", "ccc"]
    assert ids != ["ccc", "bbb", "aaa"]  # would be the descending-id bug


def test_b2_tie_break_applies_within_deferred_group_too() -> None:
    """The tie-break is not appropriate-only: deferred ties also order by id."""
    ranked = GoalSlate(
        goals=[_goal("y_def", 3.0, False), _goal("x_def", 3.0, False)]
    ).ranked()
    assert [g.id for g in ranked] == ["x_def", "y_def"]


# ---------------------------------------------------------------------------
# Behavior 3 --- input-order independence (the fix's core guarantee)
# ---------------------------------------------------------------------------


def test_b3_input_order_independence_two_orders_identical() -> None:
    """Same SET of tied goals in two different slate LIST orders -> identical
    ranked id list (both ascending id). This is the defect the iter removes."""
    a = _goal("zzz1", 1.0, True)
    b = _goal("aaa1", 1.0, True)
    assert a.score == b.score  # genuine tie

    r_ab = [g.id for g in GoalSlate(goals=[a, b]).ranked()]
    r_ba = [g.id for g in GoalSlate(goals=[b, a]).ranked()]

    assert r_ab == r_ba == ["aaa1", "zzz1"]


def test_b3_input_order_independence_larger_mixed_slate() -> None:
    """A mix of tie groups + distinct scores: two arbitrary permutations of the
    same goal set produce the identical ranked id sequence."""
    goals = [
        _goal("g_ap_hi_z", 10.0, True),
        _goal("g_ap_hi_a", 10.0, True),   # ties with g_ap_hi_z
        _goal("g_ap_lo", 2.0, True),
        _goal("g_def_z", 9.0, False),
        _goal("g_def_a", 9.0, False),     # ties with g_def_z
    ]
    order1 = [g.id for g in GoalSlate(goals=list(goals)).ranked()]
    order2 = [g.id for g in GoalSlate(goals=list(reversed(goals))).ranked()]
    assert order1 == order2
    # And it is the expected total order:
    assert order1 == [
        "g_ap_hi_a",  # appropriate, score 10.0, id asc
        "g_ap_hi_z",
        "g_ap_lo",    # appropriate, score 2.0
        "g_def_a",    # deferred, score 9.0, id asc
        "g_def_z",
    ]


# ---------------------------------------------------------------------------
# Behavior 4 --- id is the LAST / lowest-priority key
# ---------------------------------------------------------------------------


def test_b4_appropriate_beats_id_even_when_id_sorts_after() -> None:
    """An appropriate goal whose id sorts AFTER a deferred goal's id still
    ranks first: appropriate_now dominates the id tie-break."""
    appropriate = _goal("zzz", 1.0, True)   # id sorts last...
    deferred = _goal("aaa", 1.0, False)     # ...but this one is deferred
    ranked = GoalSlate(goals=[deferred, appropriate]).ranked()
    assert [g.id for g in ranked] == ["zzz", "aaa"]


def test_b4_higher_score_beats_id_within_same_appropriate_value() -> None:
    """Within one appropriate_now value, a higher score ranks first even when
    its id sorts AFTER the lower-score goal's id: score dominates the id key."""
    high_score = _goal("zzz", 5.0, True)    # id sorts last...
    low_score = _goal("aaa", 1.0, True)     # ...but lower score
    ranked = GoalSlate(goals=[low_score, high_score]).ranked()
    assert [g.id for g in ranked] == ["zzz", "aaa"]


# ---------------------------------------------------------------------------
# Behavior 5 --- gate_slate stays aligned to ranked() order
# ---------------------------------------------------------------------------


def test_b5_gate_slate_one_decision_per_goal_aligned_to_ranked() -> None:
    """gate_slate: exactly one DispatchDecision per goal (none dropped/dup'd),
    and its goal_id sequence equals ranked()'s id sequence -- including a tie
    group now ordered by ascending id."""
    goals = [
        _goal("t_c", 1.0, True),
        _goal("t_a", 1.0, True),   # ties with t_c and t_b
        _goal("t_b", 1.0, True),
        _goal("d_hi", 3.0, False),
    ]
    slate = GoalSlate(goals=goals)
    settings = Settings()

    decisions = gate_slate(slate, settings)
    ranked_ids = [g.id for g in slate.ranked()]

    # one decision per goal, none dropped or duplicated
    assert len(decisions) == len(goals)
    assert sorted(d.goal_id for d in decisions) == sorted(g.id for g in goals)

    # alignment, in order
    assert [d.goal_id for d in decisions] == ranked_ids
    # and that order reflects the new ascending-id tie-break for the tie group
    assert ranked_ids[:3] == ["t_a", "t_b", "t_c"]


# ---------------------------------------------------------------------------
# Behavior 6 --- no collateral drift (registry sizes + version frozen)
# ---------------------------------------------------------------------------


def test_b6_no_registry_or_version_drift() -> None:
    import proactive_loop
    from proactive_loop.cli import build_parser
    from proactive_loop.collectors import all_collectors
    from proactive_loop.llm.providers import VALID_PROVIDERS
    from proactive_loop.loop.tools import ToolRegistry

    assert proactive_loop.__version__ == "0.1.1"
    assert len(all_collectors()) == 16
    assert len(ToolRegistry.tool_names()) == 14
    assert len(VALID_PROVIDERS) == 7

    parser = build_parser()
    sub_actions = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(sub_actions) == 1
    assert len(sub_actions[0].choices) == 14


# ---------------------------------------------------------------------------
# Edge cases (guarding the total-order function on trivial slates)
# ---------------------------------------------------------------------------


def test_edge_empty_slate_ranks_to_empty_list() -> None:
    assert GoalSlate(goals=[]).ranked() == []


def test_edge_single_goal_slate() -> None:
    only = _goal("solo", 4.0, True)
    ranked = GoalSlate(goals=[only]).ranked()
    assert [g.id for g in ranked] == ["solo"]
