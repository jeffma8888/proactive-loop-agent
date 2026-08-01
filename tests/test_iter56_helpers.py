"""Unit tests for the ``scan --format html`` INTERNAL renderer ``_render_html``.

Scope is deliberately narrow (mirroring ``test_iter12_helpers.py``'s ``_md_cell``
tests): only the one pure, disk-free helper that carries the correctness hazards
of the html format -- (1) every dynamic cell is HTML-escaped so a title can never
inject markup, (2) the fixed five-column shape and ranked-order/``top`` slice
match the other renderers, (3) an empty slate degrades to the
``(no candidate goals)`` marker row. The black-box ``scan --format html`` CLI
behaviors (full stdout through ``main(argv)``, trailer suppression, slate-file
write, invalid-format exit-2, workspace guard) belong to the feature's behavior
suite; this module builds models directly, touches no disk, and stays fast +
deterministic.
"""

from __future__ import annotations

from proactive_loop.cli import _render_html
from proactive_loop.models import (
    AutonomyDecision,
    CandidateGoal,
    DispatchDecision,
    GoalCategory,
    GoalSlate,
)


def _goal(title: str, category: GoalCategory, impact: float) -> CandidateGoal:
    # score = impact * urgency(1) * confidence(1) / effort(1) = impact, so callers
    # can pin a deterministic rank order by choosing impact values.
    return CandidateGoal(
        title=title,
        category=category,
        impact=impact,
        urgency=1.0,
        confidence=1.0,
        effort_weight=1.0,
    )


def _slate_with(goals: list[CandidateGoal]) -> tuple[GoalSlate, list[DispatchDecision]]:
    slate = GoalSlate(workspace_root="/tmp/ws", goals=goals)
    ranked = slate.ranked()
    decisions = [
        DispatchDecision(goal_id=g.id, decision=AutonomyDecision.NEEDS_APPROVAL, reason="")
        for g in ranked
    ]
    return slate, decisions


class TestDocumentShape:
    def test_self_contained_document_envelope(self) -> None:
        slate, decisions = _slate_with([_goal("A task", GoalCategory.PROJECT, 3.0)])
        out = _render_html(slate, decisions)
        assert out.startswith("<!DOCTYPE html>")
        assert out.rstrip().endswith("</html>")
        for tag in ("<html", "<head", "<style", "<body", "<table"):
            assert tag in out
        # No external resource of any kind (offline, no injection surface).
        assert "http://" not in out and "https://" not in out
        assert "<link " not in out
        assert "<script" not in out

    def test_no_trailing_newline_from_renderer(self) -> None:
        # The pure renderer returns the doc WITHOUT a trailing newline; the CLI
        # branch is the one that `print`s it (adding exactly one).
        slate, decisions = _slate_with([_goal("A task", GoalCategory.PROJECT, 3.0)])
        assert _render_html(slate, decisions).endswith("</html>")

    def test_header_is_five_labelled_cells(self) -> None:
        slate, decisions = _slate_with([_goal("A task", GoalCategory.PROJECT, 3.0)])
        out = _render_html(slate, decisions)
        assert out.count("<th>") == 5
        header = "<tr><th>#</th><th>decision</th><th>score</th><th>category</th><th>title</th></tr>"
        assert header in out


class TestRowsAndOrder:
    def test_one_row_per_goal_in_ranked_order(self) -> None:
        slate, decisions = _slate_with(
            [
                _goal("low goal", GoalCategory.PROJECT, 1.0),
                _goal("high goal", GoalCategory.MAINTENANCE, 5.0),
            ]
        )
        out = _render_html(slate, decisions)
        # Two data <tr> + one header <tr>.
        assert out.count("<tr>") == 3
        # 5 <td> per data row, 2 rows -> 10 <td>.
        assert out.count("<td>") == 10
        # Highest-ranked (impact 5) appears before the lower one.
        assert out.index("high goal") < out.index("low goal")

    def test_cells_show_rank_decision_score_category_title(self) -> None:
        slate, decisions = _slate_with([_goal("Ship it", GoalCategory.CAREER, 4.5)])
        decisions[0] = DispatchDecision(
            goal_id=slate.ranked()[0].id,
            decision=AutonomyDecision.AUTO_DISPATCH,
            reason="x",
        )
        out = _render_html(slate, decisions)
        assert (
            "<tr><td>1</td><td>auto_dispatch</td><td>4.50</td>"
            "<td>career</td><td>Ship it</td></tr>"
        ) in out

    def test_top_slices_data_rows_without_reordering(self) -> None:
        slate, decisions = _slate_with(
            [
                _goal("first", GoalCategory.PROJECT, 5.0),
                _goal("second", GoalCategory.PROJECT, 3.0),
                _goal("third", GoalCategory.PROJECT, 1.0),
            ]
        )
        out = _render_html(slate, decisions, top=2)
        # header + 2 data rows.
        assert out.count("<tr>") == 3
        assert "first" in out and "second" in out
        assert "third" not in out

    def test_top_none_shows_all(self) -> None:
        slate, decisions = _slate_with(
            [_goal("a", GoalCategory.PROJECT, 2.0), _goal("b", GoalCategory.PROJECT, 1.0)]
        )
        assert _render_html(slate, decisions, top=None).count("<td>") == 10


class TestEscaping:
    def test_title_markup_is_escaped(self) -> None:
        raw = 'Fix <script>alert("x")</script> & <b>bold</b>'
        slate, decisions = _slate_with([_goal(raw, GoalCategory.PROJECT, 3.0)])
        out = _render_html(slate, decisions)
        assert "&lt;script&gt;" in out
        assert "&quot;" in out
        assert "&amp;" in out
        # The raw markup must never survive into the document body.
        assert "<script>" not in out
        assert "<b>" not in out

    def test_decision_and_category_values_are_escaped_defensively(self) -> None:
        # Enum .value strings are safe today, but the renderer routes them through
        # html.escape anyway; assert the .value text appears (escaped identically
        # for a safe string).
        slate, decisions = _slate_with([_goal("t", GoalCategory.HEALTH_ADMIN, 3.0)])
        decisions[0] = DispatchDecision(
            goal_id=slate.ranked()[0].id,
            decision=AutonomyDecision.NEEDS_APPROVAL,
            reason="",
        )
        out = _render_html(slate, decisions)
        assert "<td>needs_approval</td>" in out
        assert "<td>health_admin</td>" in out


class TestEmptySlate:
    def test_empty_slate_is_wellformed_with_marker(self) -> None:
        slate, decisions = _slate_with([])
        out = _render_html(slate, decisions)
        assert out.startswith("<!DOCTYPE html>")
        assert out.rstrip().endswith("</html>")
        assert "<table" in out
        assert "(no candidate goals)" in out
        # Exactly one marker row (colspan) + the header row.
        assert out.count("<tr>") == 2

    def test_empty_marker_keys_off_full_slate_not_top(self) -> None:
        # An empty slate shows the marker regardless of --top.
        slate, decisions = _slate_with([])
        assert "(no candidate goals)" in _render_html(slate, decisions, top=5)
