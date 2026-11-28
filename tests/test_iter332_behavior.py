"""Black-box oracle for foundry iter 596 (factory iter 332): all five ``scan`` renderers
(``_render_table``, ``_render_markdown``, ``_scan_json_payload``, ``_render_csv``,
``_render_html``) take their ranked, ``--top``-truncated ``(goal, decision)`` pairs from
ONE helper, ``proactive_loop.cli._ranked_pairs(slate, decisions, top=None)``, so the
SPEC's cross-format promise (same order, same score, same gate outcome) has a single
seam that cannot drift.

ISOLATION CONTRACT (honored): written from the iteration spec (``pm.md``), ``README.md``
and the conventions under ``tests/``. It drives the helper and the five renderers through
their imported callables on a hand-built ``GoalSlate`` (no workspace, no mtimes, no
network). The ONLY source text it reads is the structural census the spec itself
mandates (behaviour 3: ``inspect.getsource`` on each renderer and a text count over
``cli.py``); no engineer/reviewer note or git diff was read.

The module collects ONE item, ``test_scan_renderers_share_ranked_pairs``, which clears
every ``PLA_*`` env var and asserts ``iter596_ranked_pairs``'s returned check count
(until factory iter 602 it was hosted, uncollected, in test_iter317 under the 6-item
binding wall).
"""

from __future__ import annotations

import csv
import inspect
import io
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from proactive_loop import cli
from proactive_loop.config import Settings
from proactive_loop.models import CandidateGoal, GoalSlate
from proactive_loop.scout import gate_slate

CLI_SRC = Path(cli.__file__)
ZIP_TEXT = "list(zip(slate.ranked(), decisions))"
TRUNC_TEXT = "pairs = pairs[:top]"
RENDERER_NAMES = (
    "_render_table",
    "_render_markdown",
    "_scan_json_payload",
    "_render_csv",
    "_render_html",
)
EMPTY_MARKER = "(no candidate goals)"


def _goal(title: str, impact: float) -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="iter596 ranked-pairs probe",
        category="learning",
        impact=impact,
        urgency=4.0,
        confidence=0.9,
        effort_weight=1.0,
        appropriate_now=True,
        sources=["f.py"],
        suggested_first_steps=["do a thing"],
    )


def _fixed_slate() -> GoalSlate:
    # Insertion order deliberately differs from rank order, with distinct scores.
    return GoalSlate(
        workspace_root="/iter596/ws",
        goals=[
            _goal("Gamma low", 1.0),
            _goal("Alpha high", 5.0),
            _goal("Delta lowest", 0.5),
            _goal("Beta mid", 3.0),
        ],
    )


# --- per-renderer data-row extractors (rows as strings, titles as strings) -------------


def _table_rows(out: str) -> list[str]:
    lines = out.splitlines()
    dash = next(i for i, ln in enumerate(lines) if ln and set(ln) == {"-"})
    return [ln for ln in lines[dash + 1 :] if ln.strip() and ln.strip() != EMPTY_MARKER]


def _md_rows(out: str) -> list[str]:
    lines = [ln for ln in out.splitlines() if ln.startswith("|")]
    return lines[2:]


def _csv_rows(out: str) -> list[str]:
    rows = [r for r in csv.reader(io.StringIO(out)) if r]
    assert rows[0][0] == "rank", rows[0]
    return [",".join(r) for r in rows[1:]]


def _html_rows(out: str) -> list[str]:
    return re.findall(r"<tr><td>.*?</tr>", out)


def _json_rows(payload: Any) -> list[str]:
    assert isinstance(payload, dict), type(payload)
    return [repr(sorted(g.items())) for g in payload["goals"]]


def _render_rows(name: str, slate: GoalSlate, decisions: list[Any], top: int | None) -> list[str]:
    fn: Callable[..., Any] = getattr(cli, name)
    out = fn(slate, decisions, top=top)
    if name == "_scan_json_payload":
        return _json_rows(out)
    assert isinstance(out, str), (name, type(out))
    return {
        "_render_table": _table_rows,
        "_render_markdown": _md_rows,
        "_render_csv": _csv_rows,
        "_render_html": _html_rows,
    }[name](out)


def _titles_in(name: str, rows: list[str], titles: list[str]) -> list[str]:
    """Titles each data row carries, in row order (each row must carry exactly one)."""
    found: list[str] = []
    for row in rows:
        hits = [t for t in titles if t in row]
        assert len(hits) == 1, (name, row, hits)
        found.append(hits[0])
    return found


# --- behaviour groups ----------------------------------------------------------------


def _b1_contract(slate: GoalSlate, decisions: list[Any]) -> None:
    full = list(zip(slate.ranked(), decisions))
    ranked = slate.ranked()
    got = cli._ranked_pairs(slate, decisions)
    assert isinstance(got, list), type(got)
    assert got == full
    assert cli._ranked_pairs(slate, decisions, top=None) == full
    for i, (goal, dec) in enumerate(got):
        assert goal is ranked[i] or goal == ranked[i], i
        assert dec is decisions[i], i
    n = len(full)
    for top in range(0, n + 6):
        res = cli._ranked_pairs(slate, decisions, top=top)
        assert isinstance(res, list)
        assert res == full[:top], top
    assert cli._ranked_pairs(slate, decisions, top=0) == []
    assert cli._ranked_pairs(slate, decisions, top=1) == full[:1]
    assert cli._ranked_pairs(slate, decisions, top=n + 5) == full


def _b2_purity(slate: GoalSlate, decisions: list[Any]) -> None:
    goals_before = list(slate.goals)
    decs_before = list(decisions)
    first = cli._ranked_pairs(slate, decisions, top=2)
    second = cli._ranked_pairs(slate, decisions, top=2)
    assert first == second
    assert first is not second
    assert len(slate.goals) == len(goals_before)
    assert all(a is b for a, b in zip(slate.goals, goals_before, strict=True))
    assert len(decisions) == len(decs_before)
    assert all(a is b for a, b in zip(decisions, decs_before, strict=True))
    # Mutating the returned list must not touch the inputs.
    first.clear()
    assert cli._ranked_pairs(slate, decisions, top=2) == second


def _b3_census() -> None:
    text = CLI_SRC.read_text(encoding="utf-8")
    assert text.count(ZIP_TEXT) == 1, text.count(ZIP_TEXT)
    helper_src = inspect.getsource(cli._ranked_pairs)
    assert ZIP_TEXT in helper_src
    assert text.count(TRUNC_TEXT) == 0
    for name in RENDERER_NAMES:
        body = inspect.getsource(getattr(cli, name))
        assert body.count("_ranked_pairs(") == 1, (name, body.count("_ranked_pairs("))
        assert ZIP_TEXT not in body, name
    # 5 renderer calls + the helper's own ``def`` -- nowhere else.
    assert text.count("def _ranked_pairs(") == 1
    assert text.count("_ranked_pairs(") == 1 + len(RENDERER_NAMES), text.count("_ranked_pairs(")


def _b5_renderer_agreement(slate: GoalSlate, decisions: list[Any]) -> None:
    ranked_titles = [g.title for g in slate.ranked()]
    assert ranked_titles == ["Alpha high", "Beta mid", "Gamma low", "Delta lowest"]
    m = len(ranked_titles)
    for name in RENDERER_NAMES:
        full_rows = _render_rows(name, slate, decisions, None)
        assert _titles_in(name, full_rows, ranked_titles) == ranked_titles, name
        for top in (1, 2, m + 5):
            rows = _render_rows(name, slate, decisions, top)
            k = min(top, m)
            assert rows == full_rows[:k], (name, top)
            assert _titles_in(name, rows, ranked_titles) == ranked_titles[:k], (name, top)


def _b5_empty_slate(slate: GoalSlate) -> None:
    empty = slate.model_copy(update={"goals": []})
    for name in ("_render_table", "_render_markdown", "_render_html"):
        out = getattr(cli, name)(empty, [], top=None)
        assert EMPTY_MARKER in out, name
    assert _csv_rows(cli._render_csv(empty, [], top=None)) == []
    assert cli._scan_json_payload(empty, [], top=None)["goals"] == []
    assert cli._ranked_pairs(empty, [], top=None) == []
    assert cli._ranked_pairs(empty, [], top=3) == []


def iter596_ranked_pairs() -> int:
    """Run every iter-596 check group; return how many ran (host asserts the count)."""
    slate = _fixed_slate()
    decisions = list(gate_slate(slate, Settings()))
    assert len(decisions) == len(slate.goals) == 4
    groups = (
        lambda: _b1_contract(slate, decisions),
        lambda: _b2_purity(slate, decisions),
        _b3_census,
        lambda: _b5_renderer_agreement(slate, decisions),
        lambda: _b5_empty_slate(slate),
    )
    ran = 0
    for group in groups:
        group()
        ran += 1
    return ran


def test_scan_renderers_share_ranked_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Own collected item (no longer hosted in test_iter317), so a regression is reported
    under THIS behavior's name and cannot hide the other harnesses."""
    for key in list(os.environ):
        if key.startswith("PLA_"):
            monkeypatch.delenv(key, raising=False)
    assert iter596_ranked_pairs() == 5
