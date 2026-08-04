"""Drift guards for the README's public claims and the CI contract.

Why this file exists
--------------------
The README's portfolio intro sits ABOVE the ``PORTFOLIO INTRO -- human-owned``
marker, which automated contributors may not rewrite. That makes it the one
place in the repo whose numbers the dev loop cannot fix while it is busy
changing them -- exactly where a stale public claim rots unnoticed on a PUBLIC
repo. (It had already rotted once: the intro advertised a hardcoded
``tests-NNNN-passing`` shields badge that went stale on literally every commit.)

So every quoted claim is bound here to a live source of truth:

* ``"N context collectors"`` -> ``len(all_collectors())``
* ``"N CLI verbs"``          -> the live argparse subparser choices
* the suite-size claim       -> must be a **floor** (``1,800+ tests``), never an
  exact count. An exact count is self-invalidating: adding this very file
  changes it. A floor stays true as the suite grows.
* the test signal            -> must be the live CI badge, not a hardcoded one.
* the CI workflow            -> must still run the three commands the README and
  Makefile promise (``uv sync --locked`` / ``uv run pytest`` / ``make demo``).

The README marker carries a narrow carve-out permitting automated contributors
to correct these NUMBERS (and only the numbers), so this guard forces a fix
instead of deadlocking the loop.

Fully offline: reads two files and imports the package. No network, no
subprocess, no YAML dependency (the workflow is checked as text on purpose --
``pyyaml`` is deliberately not a dependency of this project).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from proactive_loop.cli import build_parser
from proactive_loop.collectors import all_collectors

REPO = Path(__file__).resolve().parents[1]
README = REPO / "README.md"
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
MARKER = "PORTFOLIO INTRO"


def _intro() -> str:
    """Return the human-owned block: everything above the portfolio marker."""
    text = README.read_text(encoding="utf-8")
    assert MARKER in text, (
        f"{README.name} lost its {MARKER!r} marker -- automated contributors no "
        "longer have a boundary telling them which prose is human-owned"
    )
    return text.split(MARKER, 1)[0]


def _verb_count() -> int:
    """The number of live ``pla`` subcommands, straight off the parser."""
    parser = build_parser()
    subs = [
        a
        for a in parser._subparsers._group_actions
        if isinstance(a, argparse._SubParsersAction)
    ]
    assert len(subs) == 1, f"expected exactly one subparser action, got {len(subs)}"
    return len(subs[0].choices)


def test_readme_collector_count_matches_the_live_registry() -> None:
    intro = _intro()
    m = re.search(r"([\d,]+) context collectors", intro)
    assert m, "README intro must state 'N context collectors'"
    claimed = int(m.group(1).replace(",", ""))
    live = len(all_collectors())
    assert claimed == live, (
        f"README intro claims {claimed} context collectors but the registry has "
        f"{live}; update the number in the intro (the marker's carve-out allows it)"
    )


def test_readme_cli_verb_count_matches_the_live_parser() -> None:
    intro = _intro()
    m = re.search(r"([\d,]+) CLI verbs", intro)
    assert m, "README intro must state 'N CLI verbs'"
    claimed = int(m.group(1).replace(",", ""))
    live = _verb_count()
    assert claimed == live, (
        f"README intro claims {claimed} CLI verbs but the parser exposes {live}; "
        "update the number in the intro (the marker's carve-out allows it)"
    )


def test_readme_states_the_suite_size_as_a_floor_not_an_exact_count() -> None:
    intro = _intro()
    claims = list(re.finditer(r"\*\*([\d,]+)(\+?)[^*]*tests\*\*", intro))
    assert claims, (
        "README intro must make at least one bolded claim about the suite size"
    )
    for m in claims:
        assert m.group(2) == "+", (
            f"README claims an exact test count ({m.group(0)!r}). State a floor "
            "like '**1,800+ tests**' instead: an exact count is stale the moment "
            "the next test lands, and this block is human-owned so the loop that "
            "breaks it cannot fix it."
        )
        floor = int(m.group(1).replace(",", ""))
        assert floor > 0, f"nonsensical test-count floor in {m.group(0)!r}"


def test_readme_test_signal_is_the_live_ci_badge() -> None:
    intro = _intro()
    assert "actions/workflows/ci.yml/badge.svg" in intro, (
        "README must carry the live GitHub Actions CI badge -- it is the only "
        "test signal that cannot go stale"
    )
    assert "img.shields.io/badge/tests-" not in intro, (
        "a hardcoded 'tests-NNNN-passing' shields badge is back in the README; "
        "it misreports the suite size on every commit -- use the CI badge"
    )


def test_ci_workflow_runs_the_commands_the_project_documents() -> None:
    assert WORKFLOW.is_file(), (
        f"missing {WORKFLOW.relative_to(REPO)} -- the CI badge in the README "
        "would render as 'no status' and the repo would advertise a check it "
        "does not run"
    )
    text = WORKFLOW.read_text(encoding="utf-8")
    for command in ("uv sync --locked", "uv run pytest", "make demo"):
        assert command in text, (
            f"CI no longer runs {command!r}; the workflow must keep asserting "
            "both halves of the offline claim (suite green AND demo completes)"
        )
    # The floor of requires-python must actually be exercised, or "3.12+" is
    # an untested claim.
    assert '"3.12"' in text, "CI must test the requires-python floor (3.12)"


def test_ci_checks_out_full_git_history() -> None:
    """CI must NOT use the default depth-1 checkout.

    This repo tests its own git history: ``GitActivityCollector`` shells out to
    ``git log -n15`` and the fixture behavior tests assert the exact header
    ``## git_commit (15)``. Under a shallow clone only one commit is reachable,
    so those tests fail in CI while passing on every developer machine -- which
    is exactly what happened on 2026-08-04 (three failures across four
    consecutive red builds). Pin the requirement so it cannot silently regress.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "fetch-depth: 0" in text, (
        "CI must check out FULL git history (fetch-depth: 0). The default "
        "depth-1 checkout makes GitActivityCollector see 1 commit instead of "
        "15, breaking the fixture tests in CI only."
    )
