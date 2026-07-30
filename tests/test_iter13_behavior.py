"""Black-box behavior tests for iteration 13 --- the read-only ``search_files``
loop tool.

Iteration 13 adds a grep-like ``search_files(query, path=".")`` tool to the L1
ACT sandbox (``ToolRegistry``) so a dispatched goal loop can *discover* where
content lives in a real workspace before reading it. It is additive (existing
``write_file`` / ``read_file`` / ``list_files`` contracts unchanged) and strictly
read-only.

These tests are written from the SPEC + the iteration's PM spec only; they drive
the PUBLIC surface (``ToolRegistry.execute(...)``, ``ToolRegistry.artifacts()``,
and ``GoalLoop._plan_prompt(...)`` for the prompt-advertisement check) and assert
observable output / exit behavior / on-disk artifacts. They deliberately do not
read ``src/``. Conventions (tmp_path fixtures, scripted offline provider, no
network / no API keys) mirror ``tests/test_loop.py`` and ``tests/test_iter08_behavior.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from proactive_loop.config import Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunState


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_loop.py + tests/test_iter08_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _search(tools: ToolRegistry, query: str | None = None, **extra) -> str:
    """Invoke the public execute() for search_files with the given args."""
    args: dict = dict(extra)
    if query is not None:
        args["query"] = query
    return tools.execute("search_files", args)


def _lines(observation: str) -> list[str]:
    """Split an observation into its (newline-joined) lines."""
    return observation.split("\n")


def _goal(title: str = "Locate the TODOs") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="find where content lives before reading it",
        suggested_first_steps=["search the workspace"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


# ===========================================================================
# Behavior 1 --- Basic hit (correct 1-based line number + verbatim line)
# ===========================================================================


def test_behavior_01_basic_hit(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "a.txt").write_text("line one\nthis has a needle in it\n")

    obs = _search(tools, "needle")

    assert "a.txt:2: this has a needle in it" in _lines(obs), obs


# ===========================================================================
# Behavior 2 --- Case-insensitive substring match
# ===========================================================================


def test_behavior_02_case_insensitive(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "b.txt").write_text("Hello World\n")

    lower = _search(tools, "hello")
    upper = _search(tools, "WORLD")

    assert lower == "b.txt:1: Hello World"
    assert upper == "b.txt:1: Hello World"
    assert lower == upper


# ===========================================================================
# Behavior 3 --- Multiple hits in deterministic (relpath asc, lineno asc) order
# ===========================================================================


def test_behavior_03_deterministic_order(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    # a.txt has two matches (lines 1 and 3); a nested file and a top-level file
    # exercise relpath ordering -- the nested "sub/deep.txt" must sort BEFORE the
    # top-level "z.txt" (spec: relative-path ascending, not os.walk order).
    (ws / "a.txt").write_text("match a1\nno hit here\nmatch a3\n")
    (ws / "sub").mkdir()
    (ws / "sub" / "deep.txt").write_text("match deep\n")
    (ws / "z.txt").write_text("match z\n")

    obs = _search(tools, "match")
    expected = [
        "a.txt:1: match a1",
        "a.txt:3: match a3",
        os.path.join("sub", "deep.txt") + ":1: match deep",
        "z.txt:1: match z",
    ]
    assert _lines(obs) == expected, obs
    # Same call -> byte-identical output on repeat.
    assert _search(tools, "match") == obs


# ===========================================================================
# Behavior 4 --- No match returns the exact repr'd sentinel
# ===========================================================================


def test_behavior_04_no_match(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "a.txt").write_text("nothing relevant here\n")

    obs = _search(tools, "zzz")

    assert obs == "(no matches for 'zzz')"
    assert obs.startswith("(no matches for")


# ===========================================================================
# Behavior 5 --- Default path ("." ) recurses the workspace
# ===========================================================================


def test_behavior_05_default_path_recurses(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    nested = ws / "sub" / "dir"
    nested.mkdir(parents=True)
    (nested / "file.py").write_text("needle here\n")

    obs = _search(tools, "needle")  # no path -> default "."

    relp = os.path.join("sub", "dir", "file.py")
    assert f"{relp}:1: needle here" in _lines(obs), obs


# ===========================================================================
# Behavior 6 --- Skip dirs and hidden files/dirs are excluded
# ===========================================================================


def test_behavior_06_skip_and_hidden_excluded(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "visible.txt").write_text("needle visible\n")
    for name in [".venv", "node_modules", "__pycache__", ".git", "dist", "build", ".secret"]:
        (ws / name).mkdir()
        (ws / name / "x.txt").write_text(f"needle in {name}\n")
    (ws / ".hidden.txt").write_text("needle in hidden file\n")

    obs = _search(tools, "needle")

    # Only the single visible, non-hidden file is returned.
    assert _lines(obs) == ["visible.txt:1: needle visible"], obs
    for banned in [".venv", "node_modules", "__pycache__", ".git", "dist", "build", ".secret", ".hidden"]:
        assert banned not in obs, f"{banned!r} content leaked into results:\n{obs}"


# ===========================================================================
# Behavior 7 --- Binary/undecodable files are silently skipped, never raises
# ===========================================================================


def test_behavior_07_binary_skipped_never_raises(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "good.txt").write_text("needle text\n")
    # Invalid UTF-8 bytes (also contains the ASCII token, which must NOT surface).
    (ws / "bin.dat").write_bytes(b"\xff\xfe needle \x00\x80\xfd")

    obs = _search(tools, "needle")

    assert isinstance(obs, str)
    assert "good.txt:1: needle text" in _lines(obs), obs
    assert "bin.dat" not in obs, obs


# ===========================================================================
# Behavior 8 --- Cap at 50 hits + truncation marker
# ===========================================================================


def test_behavior_08_exactly_50_no_truncation(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "m.txt").write_text("".join(f"needle {i}\n" for i in range(50)))

    obs = _search(tools, "needle")
    lines = _lines(obs)

    assert len(lines) == 50, f"expected exactly 50 hit lines; got {len(lines)}"
    assert "truncated" not in obs, obs


def test_behavior_08_over_50_truncated(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "big.txt").write_text("".join(f"needle {i}\n" for i in range(60)))

    obs = _search(tools, "needle")
    lines = _lines(obs)

    # 50 hit lines + 1 truncation marker line.
    assert len(lines) == 51, f"expected 50 hits + marker (51 lines); got {len(lines)}"
    hit_lines, marker = lines[:50], lines[50]
    assert marker == "... (truncated at 50 matches)", repr(marker)
    # The kept 50 are the deterministic first 50 (lines 1..50 of big.txt).
    assert hit_lines[0] == "big.txt:1: needle 0", hit_lines[0]
    assert hit_lines[-1] == "big.txt:50: needle 49", hit_lines[-1]
    # The 51st match (line 51) must NOT appear.
    assert "big.txt:51:" not in obs, obs


# ===========================================================================
# Behavior 9 --- Sandbox rejection for path (traversal / absolute / empty)
# ===========================================================================


def test_behavior_09_path_sandbox_rejection(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    traversal = _search(tools, "x", path="../evil")
    absolute = _search(tools, "x", path="/etc")
    empty = _search(tools, "x", path="")

    assert traversal.startswith("error:") and "traversal" in traversal, traversal
    assert absolute.startswith("error:") and "absolute" in absolute, absolute
    assert empty.startswith("error:") and "empty path" in empty, empty
    # Nothing written on any rejection.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# Behavior 10 --- Empty / missing query returns the exact error
# ===========================================================================


def test_behavior_10_empty_or_missing_query(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "a.txt").write_text("some content\n")

    missing = tools.execute("search_files", {"path": "."})  # no query key
    empty = _search(tools, "")

    expected = "error: search_files requires a non-empty 'query'"
    assert missing == expected, missing
    assert empty == expected, empty


# ===========================================================================
# Behavior 11 --- Non-existent / non-directory path
# ===========================================================================


def test_behavior_11_directory_not_found(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = _search(tools, "x", path="nope_dir")

    assert obs == "error: directory not found: 'nope_dir'", obs
    assert obs.startswith("error:") and "directory not found" in obs


# ===========================================================================
# Behavior 12 --- Read-only: artifacts unchanged, nothing new written
# ===========================================================================


def test_behavior_12_read_only(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "a.txt").write_text("needle text\n")

    before_artifacts = list(tools.artifacts())
    before_files = sorted(p.name for p in art.rglob("*"))

    obs = _search(tools, "needle")  # a real match, exercising the read path
    assert "a.txt:1: needle text" in _lines(obs), obs

    assert tools.artifacts() == before_artifacts
    assert sorted(p.name for p in art.rglob("*")) == before_files
    assert list(art.rglob("*")) == []  # artifacts dir still empty


# ===========================================================================
# Behavior 13 --- Symlink escape: a file symlinked outside the root is not read
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_13_symlink_escape_not_read(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("needle SECRET_OUTSIDE_ROOT\n")
    try:
        os.symlink(outside, ws / "link.txt")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = _search(tools, "needle")

    assert isinstance(obs, str)
    assert "SECRET_OUTSIDE_ROOT" not in obs, obs
    # A no-match sentinel is fine; the only requirement is the outside content is unseen.


# ===========================================================================
# Behavior 14 --- Root precedence: workspace_root searched before artifacts_dir
# ===========================================================================


def test_behavior_14_root_precedence_workspace_first(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "shared").mkdir()
    (ws / "shared" / "f.txt").write_text("workspace_only_match\n")
    (art / "shared").mkdir()
    (art / "shared" / "f.txt").write_text("artifacts_only_match\n")

    ws_hit = _search(tools, "workspace_only", path="shared")
    art_hit = _search(tools, "artifacts_only", path="shared")

    # The workspace copy is the one walked.
    assert "f.txt:1: workspace_only_match" in _lines(ws_hit), ws_hit
    # The artifacts-only match at the same relpath is NOT reachable.
    assert art_hit == "(no matches for 'artifacts_only')", art_hit


# ===========================================================================
# Behavior 15 --- Unknown-tool error lists search_files among the tools
# ===========================================================================


def test_behavior_15_unknown_tool_lists_search_files(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = tools.execute("no_such_tool", {})

    assert obs.startswith("error:"), obs
    for tool in ("write_file", "read_file", "list_files", "search_files"):
        assert tool in obs, f"{tool!r} missing from available-tools list:\n{obs}"


# ===========================================================================
# Behavior 16 --- The PLAN prompt advertises search_files to the model
# ===========================================================================


def test_behavior_16_plan_prompt_advertises_search_files(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "search_files" in prompt, prompt
