"""Behavior tests for commit-seq factory iter 83 (state-dir iter-73).

Feature under test: ``TodoCollector`` must recognize ALL THREE GitHub-Flavored
Markdown unordered-list bullets -- ``-``, ``*``, and ``+`` -- for unchecked
task-list items (``[ ]``), not just the dash. GFM treats ``-``/``*``/``+`` as
interchangeable bullets, but the collector's checkbox matcher previously keyed
only on ``-``, so task lists authored ``* [ ]`` or ``+ [ ]`` were silently
dropped and never reached the L2 goal synthesizer. Post-fix, star- and
plus-bulleted unchecked tasks surface as ``kind="todo"`` signals (weight 0.8)
exactly like dash tasks, while checked items (``[x]``) with any bullet stay
ignored and the broadened class introduces no new false positives.

ISOLATION: black-box. These tests drive ONLY the public interface
(``TodoCollector(...).collect(root)`` + the public ``all_collectors()`` /
``ToolRegistry`` / ``VALID_PROVIDERS`` / ``build_parser()`` / ``__version__``
registries). No file under ``src/`` was read, nor the engineer's/reviewer's
notes, nor ``git diff``; the assertions encode the pm.md Expected Behaviors, not
the implementation.

File naming: the prompt's state-dir iteration is 73, but ``tests/test_iter73_
behavior.py`` already exists (an earlier commit-seq iteration). The repo names
behavior files after the COMMIT SEQUENCE, which for this iteration is factory
iter 83 (pm.md header + ROADMAP row #83 + Acceptance Criteria); ``test_iter83_
behavior.py`` was confirmed unused before creation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from proactive_loop import __version__
from proactive_loop.cli import build_parser
from proactive_loop.collectors import TodoCollector, all_collectors
from proactive_loop.llm.providers import VALID_PROVIDERS
from proactive_loop.loop.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Black-box helpers -- write a real scanned file under a pytest tmp_path (a
# Path; the collector's collect() requires a pathlib.Path root) and collect the
# emitted todo signals. All assertions are on observable ContextSignal fields.
# ---------------------------------------------------------------------------


def _todo_sigs(root: Path, content: str, name: str = "tasks.md", **kwargs) -> list:
    (root / name).write_text(content, encoding="utf-8")
    sigs = TodoCollector(**kwargs).collect(root)
    return [s for s in sigs if s.kind == "todo"]


def _summaries(sigs) -> list:
    return [s.summary for s in sigs]


# ---------------------------------------------------------------------------
# Behavior 1 -- A DASH unchecked task is surfaced (UNCHANGED behavior).
# ---------------------------------------------------------------------------


def test_b1_dash_unchecked_task_surfaced(tmp_path: Path) -> None:
    sigs = _todo_sigs(tmp_path, "- [ ] dash task\n")
    assert len(sigs) == 1, f"expected exactly one todo signal; got {_summaries(sigs)}"
    s = sigs[0]
    assert s.summary == "TODO: dash task", f"summary; got {s.summary!r}"
    assert s.weight == 0.8, f"checkbox weight must be 0.8; got {s.weight}"
    assert s.kind == "todo", f"kind; got {s.kind!r}"
    assert s.source == "todos", f"source; got {s.source!r}"
    assert (s.path or "").endswith(":1"), f"path must end in ':<lineno>'; got {s.path!r}"


# ---------------------------------------------------------------------------
# Behavior 2 -- A STAR unchecked task is NOW surfaced (the fix).
# ---------------------------------------------------------------------------


def test_b2_star_unchecked_task_surfaced(tmp_path: Path) -> None:
    sigs = _todo_sigs(tmp_path, "* [ ] star task\n")
    assert len(sigs) == 1, (
        f"a star-bulleted unchecked task must now surface (was dropped pre-fix); "
        f"got {_summaries(sigs)}"
    )
    s = sigs[0]
    assert s.summary == "TODO: star task", f"summary; got {s.summary!r}"
    assert s.weight == 0.8, f"checkbox weight must be 0.8; got {s.weight}"


# ---------------------------------------------------------------------------
# Behavior 3 -- A PLUS unchecked task is NOW surfaced (the fix).
# ---------------------------------------------------------------------------


def test_b3_plus_unchecked_task_surfaced(tmp_path: Path) -> None:
    sigs = _todo_sigs(tmp_path, "+ [ ] plus task\n")
    assert len(sigs) == 1, (
        f"a plus-bulleted unchecked task must now surface (was dropped pre-fix); "
        f"got {_summaries(sigs)}"
    )
    s = sigs[0]
    assert s.summary == "TODO: plus task", f"summary; got {s.summary!r}"
    assert s.weight == 0.8, f"checkbox weight must be 0.8; got {s.weight}"


def test_b1_b2_b3_all_three_bullets_surface_together(tmp_path: Path) -> None:
    """The core regression: a file mixing -, *, + unchecked tasks emits all three
    (pre-fix it emitted only the dash)."""
    sigs = _todo_sigs(
        tmp_path,
        "- [ ] dash task\n* [ ] star task\n+ [ ] plus task\n",
    )
    summaries = set(_summaries(sigs))
    assert summaries == {"TODO: dash task", "TODO: star task", "TODO: plus task"}, (
        f"all three bullet styles must surface; got {sorted(summaries)}"
    )
    assert all(s.weight == 0.8 for s in sigs), "all checkbox signals must weigh 0.8"


# ---------------------------------------------------------------------------
# Behavior 4 -- A CHECKED task with ANY of the three bullets is still IGNORED.
# ---------------------------------------------------------------------------


def test_b4_checked_tasks_ignored_for_all_bullets(tmp_path: Path) -> None:
    sigs = _todo_sigs(
        tmp_path,
        "- [x] done dash\n* [x] done star\n+ [x] done plus\n",
    )
    joined = " | ".join(_summaries(sigs))
    for phrase in ("done dash", "done star", "done plus"):
        assert phrase not in joined, (
            f"a checked ([x]) task must NOT surface; found {phrase!r} in {joined!r}"
        )


# ---------------------------------------------------------------------------
# Behavior 5 -- No new false positives on non-checkbox lines.
# ---------------------------------------------------------------------------


def test_b5_no_false_positives_from_broadened_bullet_class(tmp_path: Path) -> None:
    content = (
        "*emphasis*\n"
        "**bold text**\n"
        "+1 looks good to me\n"
        "* not a checkbox\n"
        "- - -\n"
        "* * *\n"
    )
    sigs = _todo_sigs(tmp_path, content)
    assert sigs == [], (
        f"emphasis/bold/+1/thematic-breaks must produce NO checkbox todo; "
        f"got {_summaries(sigs)}"
    )


# ---------------------------------------------------------------------------
# Behavior 6 -- Leading indentation is still honored for all three bullets.
# ---------------------------------------------------------------------------


def test_b6_indented_star_task_surfaced(tmp_path: Path) -> None:
    sigs = _todo_sigs(tmp_path, "  * [ ] indented star\n")
    assert len(sigs) == 1, f"a two-space-indented star task must surface; got {_summaries(sigs)}"
    s = sigs[0]
    assert s.summary == "TODO: indented star", f"summary; got {s.summary!r}"
    assert s.weight == 0.8, f"checkbox weight must be 0.8; got {s.weight}"


# ---------------------------------------------------------------------------
# Behavior 7 -- Inline TODO/FIXME/XXX tag takes precedence; no double-count.
# ---------------------------------------------------------------------------


def test_b7_inline_tag_precedence_no_double_count(tmp_path: Path) -> None:
    sigs = _todo_sigs(tmp_path, "* [ ] TODO: mixed item\n")
    assert len(sigs) == 1, (
        f"a star-bulleted line with an inline TODO must emit EXACTLY ONE signal "
        f"(inline-tag branch wins; no second checkbox signal); got {_summaries(sigs)}"
    )
    s = sigs[0]
    assert s.summary == "TODO: mixed item", f"summary; got {s.summary!r}"
    assert s.weight == 1.0, (
        f"the inline-tag signal weighs 1.0 (not the 0.8 checkbox weight); got {s.weight}"
    )
    assert not any(x.weight == 0.8 for x in sigs), "no second 0.8 checkbox signal may appear"


# ---------------------------------------------------------------------------
# Behavior 8 -- Registry counts UNCHANGED (drift guard): a behavior-only
# widening adds no verb/tool/collector/provider/env-var and no version bump.
# ---------------------------------------------------------------------------


def test_b8_collector_registry_count_unchanged() -> None:
    assert len(all_collectors()) == 17, (
        "a checkbox-bullet widening on TodoCollector must add NO collector; "
        f"expected 17, got {len(all_collectors())}"
    )


def test_b8_tool_registry_count_unchanged() -> None:
    assert len(ToolRegistry.tool_names()) == 14, (
        f"tool registry count must stay 14; got {len(ToolRegistry.tool_names())}"
    )


def test_b8_provider_count_unchanged() -> None:
    assert len(VALID_PROVIDERS) == 7, f"provider count must stay 7; got {len(VALID_PROVIDERS)}"


def test_b8_cli_subcommand_count_unchanged() -> None:
    parser = build_parser()
    subactions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert len(subactions) == 1, "expected exactly one subparsers action"
    assert len(subactions[0].choices) == 15, (
        f"CLI subcommand count must stay 15; got {len(subactions[0].choices)}"
    )


def test_b8_version_frozen() -> None:
    assert __version__ == "0.1.1", (
        f"a behavior-only collector widening must NOT bump the version; got {__version__!r}"
    )
