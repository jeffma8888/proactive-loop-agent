"""Black-box behavior tests for iteration 21 --- the read-only ``find_files``
loop tool (recursive basename-glob file discovery).

Iteration 21 adds ``find_files(pattern, path=".")`` to the L1 ACT sandbox
(``ToolRegistry``): the *find-by-name* third of the discovery triad
(list one dir / grep content / find by name). It walks ``workspace_root`` first
(then ``artifacts_dir``), matching each file's **basename** against a stdlib
``fnmatch`` shell glob (``*`` / ``?`` / ``[seq]``) case-folded on BOTH sides for
cross-platform determinism, returns POSIX-``/`` relpaths sorted ascending, is
strictly read-only (matches on name only, never reads content), and is bounded
to 50 hits. It is additive: existing tool contracts and ``__version__`` are
unchanged.

ISOLATION: these tests are written from the SPEC (§4.4) + the iteration's PM
spec ONLY. They drive the PUBLIC surface (``ToolRegistry.execute(...)``,
``ToolRegistry.artifacts()``, and ``GoalLoop._plan_prompt(...)`` for the
prompt-advertisement check) and assert observable output / exit behavior /
on-disk artifacts. They deliberately do NOT read ``src/``. Conventions
(``tmp_path`` fixtures, scripted offline provider, no network / no API keys)
mirror ``tests/test_iter13_behavior.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.config import Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunState


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_iter13_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _find(tools: ToolRegistry, pattern: str | None = None, **extra) -> str:
    """Invoke the public execute() for find_files with the given args.

    ``pattern=None`` omits the key entirely (to exercise the missing-key path)."""
    args: dict = dict(extra)
    if pattern is not None:
        args["pattern"] = pattern
    return tools.execute("find_files", args)


def _lines(observation: str) -> list[str]:
    """Split an observation into its (newline-joined) lines."""
    return observation.split("\n")


def _goal(title: str = "Locate the Makefile") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="find a file by name before reading it",
        suggested_first_steps=["find the file in the workspace"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


# ===========================================================================
# EB1 --- Exact-name hit (no-wildcard pattern matches the basename literally)
# ===========================================================================


def test_behavior_01_exact_name_hit(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "Makefile").write_text("all:\n\techo hi\n")
    (ws / "src").mkdir()
    (ws / "src" / "app.py").write_text("print('x')\n")

    obs = _find(tools, "Makefile")

    assert _lines(obs) == ["Makefile"], obs


# ===========================================================================
# EB2 --- Recursive glob, default path (recursion + asc sort + POSIX '/')
# ===========================================================================


def test_behavior_02_recursive_glob_default_path(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "a.py").write_text("a\n")
    (ws / "sub").mkdir()
    (ws / "sub" / "b.py").write_text("b\n")
    (ws / "sub" / "deep").mkdir()
    (ws / "sub" / "deep" / "c.py").write_text("c\n")
    (ws / "notes.md").write_text("notes\n")

    obs = _find(tools, "*.py")  # default path="."

    assert _lines(obs) == ["a.py", "sub/b.py", "sub/deep/c.py"], obs
    # POSIX separators only -- no backslashes even on os.sep != '/' platforms.
    assert "\\" not in obs, obs
    # notes.md never surfaces (basename does not match *.py).
    assert "notes.md" not in obs, obs
    # Deterministic on repeat.
    assert _find(tools, "*.py") == obs


# ===========================================================================
# EB3 --- Basename-only match (a '/' in the pattern can never match a basename)
# ===========================================================================


def test_behavior_03_basename_only_match(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "sub").mkdir()
    (ws / "sub" / "b.py").write_text("b\n")

    slash_pattern = _find(tools, "sub/*.py")
    basename = _find(tools, "b.py")

    # A pattern containing '/' matches no bare filename -> degrade string.
    assert slash_pattern == "(no files matching 'sub/*.py')", slash_pattern
    assert slash_pattern.startswith("(no files matching"), slash_pattern
    # The bare basename matches, returning the full relpath.
    assert _lines(basename) == ["sub/b.py"], basename


# ===========================================================================
# EB4 --- Directories are not matched (files only)
# ===========================================================================


def test_behavior_04_directories_not_matched(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    # A directory whose name matches the glob, plus a like-named file.
    (ws / "build_scripts").mkdir()
    (ws / "build_scripts" / "run.py").write_text("run\n")
    (ws / "build_scripts.txt").write_text("txt\n")

    obs = _find(tools, "build_scripts*")

    # Only the regular file matches; the directory itself is never a result.
    assert _lines(obs) == ["build_scripts.txt"], obs


# ===========================================================================
# EB5 --- Case-insensitive on BOTH sides (deterministic cross-platform)
# ===========================================================================


def test_behavior_05_case_insensitive_both_sides(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "App.PY").write_text("x\n")

    lower_pat = _find(tools, "*.py")
    upper_pat = _find(tools, "*.PY")

    # Both the filename and the pattern are case-folded before matching; the
    # returned relpath preserves the original filename case.
    assert _lines(lower_pat) == ["App.PY"], lower_pat
    assert _lines(upper_pat) == ["App.PY"], upper_pat
    assert lower_pat == upper_pat


# ===========================================================================
# EB6 --- Skip-set dirs and hidden dirs/files are pruned
# ===========================================================================


def test_behavior_06_skip_set_and_hidden_pruned(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "keep.py").write_text("keep\n")
    for d in ["node_modules", ".venv", "__pycache__", ".git", ".tox", "dist", "build"]:
        (ws / d).mkdir()
        (ws / d / "x.py").write_text("skip\n")
    (ws / ".secret.py").write_text("hidden\n")

    obs = _find(tools, "*.py")

    assert _lines(obs) == ["keep.py"], obs
    for banned in ["node_modules", ".venv", "__pycache__", ".git", ".tox", "dist", "build", ".secret"]:
        assert banned not in obs, f"{banned!r} leaked into results:\n{obs}"


# ===========================================================================
# EB7 --- Empty/missing pattern -> exact error
# ===========================================================================


def test_behavior_07_empty_pattern_error(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "a.py").write_text("a\n")

    missing = _find(tools)          # {} -- no pattern key
    empty = _find(tools, "")        # {"pattern": ""}

    expected = "error: find_files requires a non-empty 'pattern'"
    assert missing == expected, missing
    assert empty == expected, empty
    assert missing.startswith("error:") and "pattern" in missing


# ===========================================================================
# EB8 --- Missing directory -> exact error (verbatim list/search string)
# ===========================================================================


def test_behavior_08_missing_directory_error(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = _find(tools, "*.py", path="does_not_exist")

    assert obs == "error: directory not found: 'does_not_exist'", obs
    assert obs.startswith("error:") and "directory not found" in obs


# ===========================================================================
# EB9 --- Path sandbox rejection (traversal / absolute) + nothing touched
# ===========================================================================


def test_behavior_09_path_sandbox_rejection(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    traversal = _find(tools, "*", path="../..")
    absolute = _find(tools, "*", path="/etc")

    assert traversal.startswith("error:") and "traversal" in traversal, traversal
    assert absolute.startswith("error:") and "absolute" in absolute, absolute
    # Nothing outside the sandbox is touched on either rejection.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# EB10 --- Root precedence (workspace first) + artifacts fallback
# ===========================================================================


def test_behavior_10a_workspace_root_precedence(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "shared").mkdir()
    (ws / "shared" / "ws.py").write_text("ws\n")
    (art / "shared").mkdir()
    (art / "shared" / "art.py").write_text("art\n")

    obs = _find(tools, "*.py", path="shared")

    # The workspace 'shared/' is the one walked; the artifacts copy is unreachable.
    assert _lines(obs) == ["ws.py"], obs


def test_behavior_10b_artifacts_dir_fallback(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    (art / "only_art").mkdir()
    (art / "only_art" / "f.py").write_text("f\n")

    obs = _find(tools, "*.py", path="only_art")

    # No such dir in workspace -> falls back to the artifacts root for the walk.
    assert _lines(obs) == ["f.py"], obs


# ===========================================================================
# EB11 --- No match -> degrade string (never empty, never a raise)
# ===========================================================================


def test_behavior_11_no_match_degrade_string(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "a.py").write_text("a\n")
    (ws / "b.md").write_text("b\n")

    obs = _find(tools, "*.nonexistent")

    assert obs == "(no files matching '*.nonexistent')", obs
    assert obs.startswith("(no files matching")
    assert obs != ""


# ===========================================================================
# EB12 --- Cap at 50 hits + truncation marker
# ===========================================================================


def test_behavior_12a_over_50_truncated(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    for i in range(60):
        (ws / f"f{i:02d}.txt").write_text("x\n")

    obs = _find(tools, "f*.txt")
    lines = _lines(obs)

    assert len(lines) == 51, f"expected 50 hits + marker (51 lines); got {len(lines)}"
    hit_lines, marker = lines[:50], lines[50]
    assert marker == "... (truncated at 50 matches)", repr(marker)
    # The kept 50 are the deterministic smallest-50 by ascending relpath.
    assert hit_lines[0] == "f00.txt", hit_lines[0]
    assert hit_lines[-1] == "f49.txt", hit_lines[-1]
    # f50..f59 must NOT appear.
    for i in range(50, 60):
        assert f"f{i:02d}.txt" not in obs, obs


def test_behavior_12b_exactly_50_no_marker(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    for i in range(50):
        (ws / f"f{i:02d}.txt").write_text("x\n")

    obs = _find(tools, "f*.txt")
    lines = _lines(obs)

    assert len(lines) == 50, f"expected exactly 50 lines; got {len(lines)}"
    assert "truncated" not in obs, obs


# ===========================================================================
# EB13 --- Read-only: artifacts stay empty after any call (incl. a match)
# ===========================================================================


def test_behavior_13_read_only(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "hit.py").write_text("x\n")

    obs = _find(tools, "*.py")  # a real match, exercising the walk/list path
    assert _lines(obs) == ["hit.py"], obs

    assert tools.artifacts() == []
    assert list(art.rglob("*")) == []  # artifacts dir still empty


# ===========================================================================
# EB14 --- Symlink escape not returned (file escape excluded; dir escape not descended)
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_14_symlink_escape_not_returned(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "keep.py").write_text("keep\n")

    # A file OUTSIDE the sandbox root, symlinked into the workspace as link.py.
    outside_file = tmp_path / "outside_target.py"
    outside_file.write_text("escaped file\n")
    # A dir OUTSIDE the sandbox root (with a .py inside), symlinked in as linkdir.
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir()
    (outside_dir / "inner_escaped.py").write_text("escaped dir content\n")

    try:
        os.symlink(outside_file, ws / "link.py")
        os.symlink(outside_dir, ws / "linkdir", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = _find(tools, "*.py")

    assert isinstance(obs, str)
    # The escaping file symlink (its own name) is filtered out by the _within guard.
    assert "link.py" not in _lines(obs), obs
    # The escaping dir symlink is not descended (followlinks=False).
    assert "inner_escaped.py" not in obs, obs
    assert "linkdir" not in obs, obs
    # The in-sandbox file is still found.
    assert "keep.py" in _lines(obs), obs


# ===========================================================================
# EB15 --- Unknown-tool hint lists ALL SIX tools
# ===========================================================================


def test_behavior_15_unknown_tool_lists_all_six_tools(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = tools.execute("no_such_tool", {})

    assert obs.startswith("error:"), obs
    for tool in ("write_file", "read_file", "list_files", "search_files", "append_file", "find_files"):
        assert tool in obs, f"{tool!r} missing from available-tools list:\n{obs}"


# ===========================================================================
# EB16 --- PLAN prompt advertises find_files
# ===========================================================================


def test_behavior_16_plan_prompt_advertises_find_files(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "find_files" in prompt, prompt


# ===========================================================================
# EB17 --- Backward compatibility: version unchanged + prior tools intact
# ===========================================================================


def test_behavior_17_version_unchanged(tmp_path: Path) -> None:
    # Additive tool -> no version bump (mirrors iter-13 search_files / iter-17 append_file).
    assert proactive_loop.__version__ == "0.1.1"


def test_behavior_17_prior_tools_unchanged_smoke(tmp_path: Path) -> None:
    """Light smoke over the other five tools' public contracts to confirm the
    additive find_files handler did not perturb them."""
    tools, ws, _ = _registry(tmp_path)

    # write_file -> artifacts_dir, then artifacts() reports it.
    w = tools.execute("write_file", {"path": "out.txt", "content": "hello\n"})
    assert not w.startswith("error:"), w
    assert "out.txt" in tools.artifacts(), tools.artifacts()

    # append_file -> extends the same artifact.
    a = tools.execute("append_file", {"path": "out.txt", "content": "world\n"})
    assert not a.startswith("error:"), a

    # read_file -> reads it back with both writes present.
    r = tools.execute("read_file", {"path": "out.txt"})
    assert "hello" in r and "world" in r, r

    # list_files -> lists the artifact.
    (ws / "src.txt").write_text("needle here\n")
    lst = tools.execute("list_files", {"path": "."})
    assert "src.txt" in lst, lst

    # search_files -> greps content (name/line/text form).
    s = tools.execute("search_files", {"query": "needle"})
    assert "src.txt:1: needle here" in _lines(s), s
