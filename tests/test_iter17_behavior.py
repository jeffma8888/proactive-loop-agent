"""Black-box behavior tests for iteration 17 --- the ``append_file`` sandbox tool.

Iteration 17 adds a first-class *incremental-authoring* primitive to the L1 ACT
sandbox (``ToolRegistry``): ``append_file(path, content)`` extends (or creates)
an artifact under ``artifacts_dir`` in append mode --- no read-then-rewrite ---
and is advertised to the loop's PLAN prompt exactly as ``search_files`` was in
iter-13. It reuses the same safety seams as ``write_file`` (reject ``..``,
absolute paths, empty path; create missing parents) and is additive: the
existing ``write_file`` / ``read_file`` / ``list_files`` / ``search_files``
contracts are unchanged and there is **no version bump**.

These tests are written from ``SPEC.md`` §4.4 + this iteration's PM spec ONLY;
they drive the PUBLIC surface (``ToolRegistry.execute(...)``,
``ToolRegistry.artifacts()``, ``execute("read_file", ...)`` for read-back, and
``GoalLoop._plan_prompt(...)`` for the prompt-advertisement check) and assert
observable output / on-disk artifacts. They deliberately do NOT read ``src/``.
Conventions (tmp_path fixtures, scripted offline provider, no network / no API
keys, a fresh temp workspace + temp artifacts dir --- never the in-repo fixture)
mirror ``tests/test_loop.py`` and ``tests/test_iter13_behavior.py``.
"""

from __future__ import annotations

from pathlib import Path

import proactive_loop
from proactive_loop.config import Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunState


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_loop.py + tests/test_iter13_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _goal(title: str = "Grow a multi-step document") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="append section 2 after section 1 without a rewrite",
        suggested_first_steps=["draft section 1", "append section 2"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


def _read(tools: ToolRegistry, path: str) -> str:
    """Read an artifact back through the public read_file tool."""
    return tools.execute("read_file", {"path": path})


# ===========================================================================
# Behavior 1 --- Append creates a new file
# ===========================================================================


def test_behavior_01_append_creates_new_file(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = tools.execute("append_file", {"path": "notes.md", "content": "hello"})

    assert obs == "appended 5 chars to artifacts/notes.md", obs
    target = art / "notes.md"
    assert target.exists(), "artifact file was not created"
    assert target.read_text() == "hello", target.read_text()
    assert "notes.md" in tools.artifacts(), tools.artifacts()


# ===========================================================================
# Behavior 2 --- Append extends an existing file (no clobber), deduped registry
# ===========================================================================


def test_behavior_02_append_extends_no_clobber(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    tools.execute("append_file", {"path": "log.txt", "content": "A"})
    tools.execute("append_file", {"path": "log.txt", "content": "B"})

    # Concatenated in call order, NOT overwritten.
    assert _read(tools, "log.txt") == "AB", _read(tools, "log.txt")
    # Registered exactly once (deduped, like write_file).
    assert tools.artifacts().count("log.txt") == 1, tools.artifacts()


# ===========================================================================
# Behavior 3 --- write_file then append_file extends the written file
# ===========================================================================


def test_behavior_03_write_then_append_extends(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    tools.execute("write_file", {"path": "doc.md", "content": "sec1\n"})
    tools.execute("append_file", {"path": "doc.md", "content": "sec2\n"})

    assert _read(tools, "doc.md") == "sec1\nsec2\n", _read(tools, "doc.md")
    # A path written by BOTH tools is registered once, not twice.
    assert tools.artifacts().count("doc.md") == 1, tools.artifacts()


# ===========================================================================
# Behavior 4 --- Append creates missing parent directories
# ===========================================================================


def test_behavior_04_append_creates_parent_dirs(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = tools.execute("append_file", {"path": "sub/dir/a.md", "content": "x"})

    assert obs == "appended 1 chars to artifacts/sub/dir/a.md", obs
    nested = art / "sub" / "dir" / "a.md"
    assert nested.exists(), "nested artifact was not created"
    assert nested.read_text() == "x", nested.read_text()
    # artifacts() records the posix relpath.
    assert "sub/dir/a.md" in tools.artifacts(), tools.artifacts()


# ===========================================================================
# Behavior 5 --- Append rejects path traversal (writes nothing)
# ===========================================================================


def test_behavior_05_append_rejects_traversal(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = tools.execute("append_file", {"path": "../evil.txt", "content": "pwn"})

    assert obs.startswith("error:"), obs
    assert "path traversal" in obs, obs
    # Exact message reused verbatim from _reject_unsafe (per spec).
    assert obs == "error: path traversal ('..') is not allowed: '../evil.txt'", obs
    # Nothing escaped the sandbox: no evil.txt beside/above artifacts_dir.
    assert not (art.parent / "evil.txt").exists()
    assert not (tmp_path / "evil.txt").exists()
    # No traversal path was registered.
    assert "../evil.txt" not in tools.artifacts(), tools.artifacts()
    assert all(".." not in a for a in tools.artifacts()), tools.artifacts()


# ===========================================================================
# Behavior 6 --- Append rejects absolute paths (writes nothing)
# ===========================================================================


def test_behavior_06_append_rejects_absolute(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    # A tmp-derived absolute path (guaranteed absolute + clean) exercises the
    # absolute-path rejection without polluting the real /tmp filesystem.
    abs_target = tmp_path / "pla_escape_test.txt"
    assert abs_target.is_absolute()

    obs = tools.execute("append_file", {"path": str(abs_target), "content": "x"})

    assert obs.startswith("error:"), obs
    assert "absolute paths are not allowed" in obs, obs
    # The absolute target is NOT created/modified by this call.
    assert not abs_target.exists(), "absolute target must not be created"
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 7 --- Append rejects an empty path
# ===========================================================================


def test_behavior_07_append_rejects_empty_path(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = tools.execute("append_file", {"path": "", "content": "x"})

    assert obs == "error: empty path is not allowed", obs
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 8 --- Append with no `content` key appends zero chars
# ===========================================================================


def test_behavior_08_append_missing_content_zero_chars(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = tools.execute("append_file", {"path": "empty.md"})  # no content key

    assert obs == "appended 0 chars to artifacts/empty.md", obs
    target = art / "empty.md"
    assert target.exists(), "empty artifact should still be created"
    assert target.read_text() == "", repr(target.read_text())
    assert "empty.md" in tools.artifacts(), tools.artifacts()


# ===========================================================================
# Behavior 9 --- Never raises; unknown-tool observation now lists append_file
# ===========================================================================


def test_behavior_09a_unknown_tool_lists_append_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = tools.execute("no_such_tool", {})

    assert obs.startswith("error:"), obs
    for tool in ("write_file", "read_file", "list_files", "search_files", "append_file"):
        assert tool in obs, f"{tool!r} missing from available-tools list:\n{obs}"


def test_behavior_09b_append_non_dict_args_never_raises(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    # execute() never-raises contract holds for the new tool with non-dict args.
    for bad_args in (None, "notadict", ["not", "a", "dict"], 42):
        obs = tools.execute("append_file", bad_args)
        assert isinstance(obs, str), (bad_args, obs)
        assert obs.startswith("appended 0 chars to artifacts/") or obs.startswith(
            "error:"
        ), (bad_args, obs)


# ===========================================================================
# Behavior 10 --- The PLAN prompt advertises append_file (and still search_files)
# ===========================================================================


def test_behavior_10_plan_prompt_advertises_append_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "append_file" in prompt, prompt
    # The iter-13 advert is preserved, not replaced.
    assert "search_files" in prompt, prompt


# ===========================================================================
# Behavior 11 --- Regression: write_file still overwrites (does NOT append)
# ===========================================================================


def test_behavior_11_write_file_still_overwrites(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    first = tools.execute("write_file", {"path": "x.md", "content": "first"})
    second = tools.execute("write_file", {"path": "x.md", "content": "second"})

    # write_file message shape is unchanged: "wrote N chars to artifacts/<rel>".
    assert first == "wrote 5 chars to artifacts/x.md", first
    assert second == "wrote 6 chars to artifacts/x.md", second
    # Overwrite semantics preserved --- NOT appended.
    assert (art / "x.md").read_text() == "second", (art / "x.md").read_text()
    assert _read(tools, "x.md") == "second", _read(tools, "x.md")
    assert tools.artifacts().count("x.md") == 1, tools.artifacts()


def test_behavior_11_no_version_bump(tmp_path: Path) -> None:
    # Additive tool: the package version stays pinned at 0.1.1.
    assert proactive_loop.__version__ == "0.1.1", proactive_loop.__version__
