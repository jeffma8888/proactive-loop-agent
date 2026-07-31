"""Black-box behavior tests for iteration 33 --- the ``remove_file`` loop tool,
the L1 sandbox's FIRST destructive-mutation verb.

Iteration 33 adds ``remove_file(path)`` to the L1 ACT sandbox (``ToolRegistry``),
completing the write-side CRUD story create (``write_file``) / update
(``append_file``) / read (``read_file`` & friends) / **delete** (``remove_file``).
It deletes a file the loop created under the artifacts sandbox and can NEVER touch
anything in the read-only ``workspace_root``. It mirrors ``write_file``'s
``_reject_unsafe`` refusals byte-for-byte (empty / ``..`` traversal / absolute
paths), refuses to remove directories, reports a missing target as an observable
error, and --- load-bearing for a destructive op --- refuses any target that a
symlink resolves OUTSIDE the artifacts sandbox BEFORE any ``unlink``. It is
additive: existing tool contracts and ``__version__`` are unchanged, and it never
raises --- every failure is an observation string starting ``"error:"``.

ISOLATION: these tests are written from ``SPEC.md`` (§4.4, the public contract) +
this iteration's PM spec (the 13 Expected Behaviors) ONLY. They drive the PUBLIC
surface --- ``ToolRegistry.execute(...)``, ``ToolRegistry.artifacts()`` and
``GoalLoop._plan_prompt(...)`` for the prompt-advertisement check --- and assert
observable output / on-disk artifacts / exit conditions. They deliberately do NOT
read ``src/`` or any engineer/reviewer note or ``git diff``. Conventions
(``tmp_path`` fixtures, scripted offline provider, symlink-skip idiom, no network /
no API keys) mirror ``tests/test_iter{13,21,26,29}_behavior.py``.
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
# Shared helpers (mirroring tests/test_iter29_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _write(tools: ToolRegistry, path: str, content: str = "x") -> str:
    return tools.execute("write_file", {"path": path, "content": content})


def _remove(tools: ToolRegistry, path: str | None = None) -> str:
    """Invoke the public execute() for remove_file.

    ``path=None`` omits the key entirely (to exercise the missing-key path)."""
    args: dict = {}
    if path is not None:
        args["path"] = path
    return tools.execute("remove_file", args)


def _goal(title: str = "Delete a scaffolded artifact I no longer need") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="remove a file the loop created in its sandbox to keep a clean tree",
        suggested_first_steps=["remove the stale artifact once it is no longer needed"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


# ===========================================================================
# Behavior 1 --- Clean delete of a created artifact
# ===========================================================================


def test_behavior_01_clean_delete_of_created_artifact(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "note.txt", "hello").startswith("error:")
    assert "note.txt" in tools.artifacts()

    obs = _remove(tools, "note.txt")

    assert obs == "removed artifacts/note.txt", obs
    # Gone from disk and dropped from the tracked list (was the only write).
    assert not (art / "note.txt").exists()
    assert "note.txt" not in tools.artifacts()
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 2 --- Nested artifact delete; parent directory survives
# ===========================================================================


def test_behavior_02_nested_delete_relpath_and_parent_survives(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "sub/inner.txt", "x").startswith("error:")

    obs = _remove(tools, "sub/inner.txt")

    # Same forward-slashed relpath form as write_file's message.
    assert obs == "removed artifacts/sub/inner.txt", obs
    assert not (art / "sub" / "inner.txt").exists()
    # Only the FILE is removed --- the parent directory still exists.
    assert (art / "sub").is_dir(), "parent directory must survive a file delete"


# ===========================================================================
# Behavior 3 --- Missing artifact -> observable error, nothing changed
# ===========================================================================


def test_behavior_03_missing_artifact_error(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = _remove(tools, "ghost.txt")

    assert obs == "error: no such artifact: 'ghost.txt'", obs
    # No file created; nothing tracked; artifacts dir untouched.
    assert not (art / "ghost.txt").exists()
    assert tools.artifacts() == [], tools.artifacts()
    assert list(art.iterdir()) == [], list(art.iterdir())


# ===========================================================================
# Behavior 4 --- Directory removal is refused; the directory survives
# ===========================================================================


def test_behavior_04_directory_removal_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "d/f.txt", "x").startswith("error:")  # creates d/

    obs = _remove(tools, "d")

    assert obs == "error: refusing to remove a directory: 'd'", obs
    # The directory AND its contained file both survive.
    assert (art / "d").is_dir(), "directory must survive a refused remove"
    assert (art / "d" / "f.txt").exists(), "contained file must survive"


# ===========================================================================
# Behavior 5 --- Path-traversal refused --- byte-identical to write_file
# ===========================================================================


def test_behavior_05_traversal_refused_byte_identical_to_write(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    remove_obs = _remove(tools, "../escape.txt")
    write_obs = _write(tools, "../escape.txt", "x")

    assert remove_obs == "error: path traversal ('..') is not allowed: '../escape.txt'", remove_obs
    # The delete-side string is BYTE-IDENTICAL to write_file's for this input.
    assert remove_obs == write_obs, (remove_obs, write_obs)
    # Nothing on disk changed anywhere near the sandbox parent.
    assert not (tmp_path / "escape.txt").exists()
    assert list(art.iterdir()) == [], list(art.iterdir())
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 6 --- Absolute path refused --- byte-identical to write_file
# ===========================================================================


def test_behavior_06_absolute_refused_byte_identical_to_write(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    # Assert the STRING only; never touch a real absolute path.
    remove_obs = _remove(tools, "/tmp/x.txt")
    write_obs = _write(tools, "/tmp/x.txt", "x")

    assert remove_obs == "error: absolute paths are not allowed: '/tmp/x.txt'", remove_obs
    assert remove_obs == write_obs, (remove_obs, write_obs)
    assert list(art.iterdir()) == [], list(art.iterdir())
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 7 --- Empty / missing path refused --- byte-identical to write_file
# ===========================================================================


def test_behavior_07_empty_and_missing_path_refused_byte_identical(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    empty_obs = _remove(tools, "")     # {"path": ""}
    missing_obs = _remove(tools)       # {} -- no path key

    # Shared _reject_unsafe message (NOT a tool-specific empty-path message).
    assert empty_obs == "error: empty path is not allowed", empty_obs
    assert missing_obs == "error: empty path is not allowed", missing_obs
    # Byte-identical to write_file's for the same inputs.
    assert empty_obs == _write(tools, "", "x"), empty_obs
    assert missing_obs == tools.execute("write_file", {"content": "x"}), missing_obs
    assert list(art.iterdir()) == [], list(art.iterdir())
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 8 --- NEVER deletes a file in the read-only workspace_root
# ===========================================================================


def test_behavior_08_never_touches_workspace_root(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    # A file DIRECTLY under workspace_root (NOT under artifacts_dir).
    (ws / "real.txt").write_text("important user data")

    obs = _remove(tools, "real.txt")

    # remove_file resolves ONLY against artifacts_dir -> the workspace file is
    # invisible to it and reported as a missing artifact.
    assert obs == "error: no such artifact: 'real.txt'", obs
    # The user's workspace file STILL EXISTS with unchanged content.
    assert (ws / "real.txt").exists(), "workspace file must never be deleted"
    assert (ws / "real.txt").read_text() == "important user data"


# ===========================================================================
# Behavior 9 --- Symlink escaping the sandbox refused; external target intact
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_09_symlink_escape_refused_target_intact(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    # A directory OUTSIDE both sandbox roots, holding a file with known bytes.
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret = outside_dir / "secret.txt"
    secret.write_bytes(b"do-not-touch\n")
    try:
        os.symlink(outside_dir, art / "link")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = _remove(tools, "link/secret.txt")

    # Refused as out-of-sandbox by the resolved-_within guard.
    assert obs == "error: refusing to remove outside artifacts dir: 'link/secret.txt'", obs
    # PRIMARY load-bearing assertions: no deletion leaked through the link ---
    # the external target STILL EXISTS and its bytes are UNCHANGED.
    assert secret.exists(), "external symlink target must not be deleted"
    assert secret.read_bytes() == b"do-not-touch\n", "external target bytes must be untouched"


# ===========================================================================
# Behavior 10 --- Double-remove is observable
# ===========================================================================


def test_behavior_10_double_remove_is_observable(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "note.txt", "hi").startswith("error:")

    first = _remove(tools, "note.txt")
    second = _remove(tools, "note.txt")

    assert first == "removed artifacts/note.txt", first
    # The file is genuinely gone, so the second remove is a missing-artifact error.
    assert second == "error: no such artifact: 'note.txt'", second
    assert not (art / "note.txt").exists()


# ===========================================================================
# Behavior 11 --- Operates on the filesystem, not just the tracked list
# ===========================================================================


def test_behavior_11_removes_untracked_on_disk_artifact(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    # Write DIRECTLY to artifacts_dir, bypassing write_file -> NOT tracked.
    (art / "orphan.txt").write_text("orphan")
    before = list(tools.artifacts())
    assert "orphan.txt" not in before, before

    obs = _remove(tools, "orphan.txt")

    assert obs == "removed artifacts/orphan.txt", obs
    # Removed from disk; the "drop from tracked list" step is conditional on
    # membership, so the untracked case does NOT raise and leaves artifacts()
    # unchanged relative to before the call.
    assert not (art / "orphan.txt").exists()
    assert tools.artifacts() == before, (tools.artifacts(), before)


# ===========================================================================
# Behavior 12 --- remove_file advertised in the unknown-tool message
# ===========================================================================


def test_behavior_12_unknown_tool_lists_remove_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = tools.execute("definitely_not_a_tool", {})

    assert obs.startswith("error:"), obs
    # Substring assertion (order-independent) --- and the prior tools stay listed.
    assert "remove_file" in obs, f"remove_file missing from available-tools list:\n{obs}"
    for tool in (
        "write_file",
        "read_file",
        "list_files",
        "search_files",
        "append_file",
        "find_files",
        "stat_file",
        "head_file",
    ):
        assert tool in obs, f"{tool!r} missing from available-tools list:\n{obs}"


# ===========================================================================
# Behavior 13 --- The PLAN prompt advertises remove_file
# ===========================================================================


def test_behavior_13_plan_prompt_advertises_remove_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    # Substring assertion only -> pre-existing tool advertisements stay green.
    assert "remove_file" in prompt, prompt


# ===========================================================================
# Backward-compat guard --- additive tool, no version bump (mirrors iters 13/29)
# ===========================================================================


def test_version_unchanged_additive_tool() -> None:
    assert proactive_loop.__version__ == "0.1.1"
