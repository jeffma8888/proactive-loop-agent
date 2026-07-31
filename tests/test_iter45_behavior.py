"""Black-box behavior tests for iteration 45 --- the ``move_file`` loop tool,
the L1 sandbox's atomic relocate/rename verb.

Iteration 45 adds ``move_file(src, dst)`` to the L1 ACT sandbox
(``ToolRegistry``), completing the write-side mutation family create
(``write_file``) / update (``append_file``) / read (``read_file`` & friends) /
**move** / delete (``remove_file``). It atomically relocates ONE file under the
artifacts sandbox (``os.replace``) and can NEVER touch anything under the
read-only ``workspace_root``. Both ``src`` and ``dst`` go through the shared
``_reject_unsafe`` refusals (empty / ``..`` traversal / absolute) byte-for-byte
with ``write_file`` and a resolved within-sandbox gate that fires BEFORE any disk
write; it refuses a directory src, a missing src, and an already-existing dst
(no silent clobber). It is additive: existing tool contracts and ``__version__``
are unchanged, and it never raises --- every failure is an observation string
starting ``"error:"``.

ISOLATION: I honored the tester isolation contract. These tests are written from
``SPEC.md`` (§4.4, the public contract) + this iteration's PM spec (the 16
Expected Behaviors) ONLY. They drive the PUBLIC surface ---
``ToolRegistry.execute(...)``, ``ToolRegistry.artifacts()`` and
``GoalLoop._plan_prompt(...)`` for the prompt-advertisement check --- and assert
observable output / on-disk artifacts / exit conditions. They deliberately do
NOT read ``src/`` or any engineer/reviewer note or ``git diff``. Conventions
(``tmp_path`` fixtures, scripted offline provider, symlink-skip idiom, no network
/ no API keys) mirror ``tests/test_iter{13,21,26,29,33}_behavior.py``.
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
# Shared helpers (mirroring tests/test_iter33_behavior.py)
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


def _move(
    tools: ToolRegistry, src: str | None = None, dst: str | None = None
) -> str:
    """Invoke the public execute() for move_file.

    ``src``/``dst`` = ``None`` omits that key entirely (to exercise the
    missing-key path); pass ``""`` to send an explicit empty string."""
    args: dict = {}
    if src is not None:
        args["src"] = src
    if dst is not None:
        args["dst"] = dst
    return tools.execute("move_file", args)


def _goal(title: str = "Relocate a scaffolded artifact to its correct name") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="rename a file the loop created in its sandbox to the right path",
        suggested_first_steps=["move the artifact to its final location once known"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


# ===========================================================================
# Behavior 1 --- Clean move of a created artifact
# ===========================================================================


def test_behavior_01_clean_move_of_created_artifact(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "a.txt", "hello").startswith("error:")
    assert "a.txt" in tools.artifacts()

    obs = _move(tools, src="a.txt", dst="b.txt")

    assert obs == "moved artifacts/a.txt -> artifacts/b.txt", obs
    # Src gone from disk; dst present with the moved bytes.
    assert not (art / "a.txt").exists()
    assert (art / "b.txt").exists()
    assert (art / "b.txt").read_text() == "hello"
    # Tracked list: src dropped, dst appended (was the only write).
    assert tools.artifacts() == ["b.txt"], tools.artifacts()


# ===========================================================================
# Behavior 2 --- Move into a not-yet-existing nested subdirectory
# ===========================================================================


def test_behavior_02_move_into_nested_creates_parents(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "a.txt", "data").startswith("error:")

    obs = _move(tools, src="a.txt", dst="sub/deep/b.txt")

    # Forward-slashed relpaths in the message (matching write_file/remove_file).
    assert obs == "moved artifacts/a.txt -> artifacts/sub/deep/b.txt", obs
    # Missing parents were created; the file landed with its content intact.
    assert (art / "sub" / "deep" / "b.txt").exists()
    assert (art / "sub" / "deep" / "b.txt").read_text() == "data"
    # Src removed; tracked list reflects the POSIX nested relpath in its place.
    assert not (art / "a.txt").exists()
    assert tools.artifacts() == ["sub/deep/b.txt"], tools.artifacts()


# ===========================================================================
# Behavior 3 --- Missing src -> observable error, nothing changes
# ===========================================================================


def test_behavior_03_missing_src_error_nothing_changes(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = _move(tools, src="ghost.txt", dst="b.txt")

    # Error names the SRC (byte-identical to remove_file's missing message).
    assert obs == "error: no such artifact: 'ghost.txt'", obs
    assert not (art / "b.txt").exists()
    assert tools.artifacts() == []
    assert list(art.iterdir()) == [], list(art.iterdir())

    # Stronger guard-ordering check: with a NESTED dst, the src-exists guard
    # must fire BEFORE any dst parent-dir creation -> no 'sub' dir appears.
    obs2 = _move(tools, src="ghost.txt", dst="sub/deep/b.txt")
    assert obs2 == "error: no such artifact: 'ghost.txt'", obs2
    assert not (art / "sub").exists(), "no dst parent dirs before the src-exists guard"
    assert list(art.iterdir()) == [], list(art.iterdir())
    assert tools.artifacts() == []


# ===========================================================================
# Behavior 4 --- src is a directory -> refused, directory survives
# ===========================================================================


def test_behavior_04_directory_src_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    # write_file("sub/inner.txt") creates the directory sub/.
    assert not _write(tools, "sub/inner.txt", "x").startswith("error:")

    obs = _move(tools, src="sub", dst="sub2")

    assert obs == "error: refusing to move a directory: 'sub'", obs
    # The directory AND its contained file survive; no sub2 is created.
    assert (art / "sub").is_dir(), "directory must survive a refused move"
    assert (art / "sub" / "inner.txt").exists(), "contained file must survive"
    assert not (art / "sub2").exists()


# ===========================================================================
# Behavior 5 --- Existing dst -> refused (no silent clobber), both intact
# ===========================================================================


def test_behavior_05_existing_dst_refused_no_clobber(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "a.txt", "AAA").startswith("error:")
    assert not _write(tools, "b.txt", "BBB").startswith("error:")

    obs = _move(tools, src="a.txt", dst="b.txt")

    assert obs == "error: destination already exists: 'b.txt'", obs
    # Neither file changed on disk.
    assert (art / "a.txt").read_text() == "AAA"
    assert (art / "b.txt").read_text() == "BBB"
    # Both still tracked.
    assert "a.txt" in tools.artifacts(), tools.artifacts()
    assert "b.txt" in tools.artifacts(), tools.artifacts()


# ===========================================================================
# Behavior 6 --- Same src and dst -> refused as existing destination
# ===========================================================================


def test_behavior_06_same_src_and_dst_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "a.txt", "x").startswith("error:")

    obs = _move(tools, src="a.txt", dst="a.txt")

    assert obs == "error: destination already exists: 'a.txt'", obs
    # a.txt untouched and still tracked.
    assert (art / "a.txt").read_text() == "x"
    assert "a.txt" in tools.artifacts(), tools.artifacts()


# ===========================================================================
# Behavior 7 --- Path traversal in src refused (byte-identical to write_file)
# ===========================================================================


def test_behavior_07_traversal_in_src_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    move_obs = _move(tools, src="../escape.txt", dst="b.txt")
    write_obs = _write(tools, "../escape.txt", "x")

    assert move_obs == "error: path traversal ('..') is not allowed: '../escape.txt'", move_obs
    # Byte-identical to write_file's message for this input.
    assert move_obs == write_obs, (move_obs, write_obs)
    # Nothing created or moved.
    assert not (tmp_path / "escape.txt").exists()
    assert not (art / "b.txt").exists()
    assert list(art.iterdir()) == [], list(art.iterdir())
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 8 --- Path traversal in dst refused, src intact
# ===========================================================================


def test_behavior_08_traversal_in_dst_refused_src_intact(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "a.txt", "x").startswith("error:")

    obs = _move(tools, src="a.txt", dst="../escape.txt")

    assert obs == "error: path traversal ('..') is not allowed: '../escape.txt'", obs
    # src not moved; nothing created outside the sandbox.
    assert (art / "a.txt").read_text() == "x"
    assert not (tmp_path / "escape.txt").exists()
    assert "a.txt" in tools.artifacts(), tools.artifacts()


# ===========================================================================
# Behavior 9 --- Absolute path in src refused (assert STRING only)
# ===========================================================================


def test_behavior_09_absolute_src_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    move_obs = _move(tools, src="/tmp/x.txt", dst="b.txt")
    write_obs = _write(tools, "/tmp/x.txt", "x")

    assert move_obs == "error: absolute paths are not allowed: '/tmp/x.txt'", move_obs
    assert move_obs == write_obs, (move_obs, write_obs)
    # Nothing changed (never touch a real absolute path).
    assert not (art / "b.txt").exists()
    assert list(art.iterdir()) == [], list(art.iterdir())
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# Behavior 10 --- Absolute path in dst refused, src intact
# ===========================================================================


def test_behavior_10_absolute_dst_refused_src_intact(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "a.txt", "x").startswith("error:")

    obs = _move(tools, src="a.txt", dst="/tmp/x.txt")

    assert obs == "error: absolute paths are not allowed: '/tmp/x.txt'", obs
    # a.txt untouched (never touch a real absolute path).
    assert (art / "a.txt").read_text() == "x"
    assert "a.txt" in tools.artifacts(), tools.artifacts()


# ===========================================================================
# Behavior 11 --- Empty / missing src or dst -> shared empty-path error
# ===========================================================================


def test_behavior_11_empty_or_missing_path_shared_error(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    # src key omitted entirely (dst present) -> shared _reject_unsafe message.
    assert tools.execute("move_file", {"dst": "b.txt"}) == "error: empty path is not allowed"
    # src="" (explicit empty string).
    assert _move(tools, src="", dst="b.txt") == "error: empty path is not allowed"
    # Byte-identical to write_file's empty message.
    assert _move(tools, src="", dst="b.txt") == _write(tools, "", "x")

    # dst="" with a valid src -> src untouched.
    assert not _write(tools, "a.txt", "x").startswith("error:")
    obs = _move(tools, src="a.txt", dst="")
    assert obs == "error: empty path is not allowed", obs
    assert (art / "a.txt").read_text() == "x"
    assert "a.txt" in tools.artifacts(), tools.artifacts()
    # dst key omitted entirely (src present) -> same shared message.
    assert tools.execute("move_file", {"src": "a.txt"}) == "error: empty path is not allowed"

    # src is checked BEFORE dst: an UNSAFE src with an empty dst surfaces the
    # SRC error (a distinguishable message proves the ordering).
    assert (
        _move(tools, src="../escape.txt", dst="")
        == "error: path traversal ('..') is not allowed: '../escape.txt'"
    )
    # a.txt still untouched after all the refusals above.
    assert (art / "a.txt").read_text() == "x"


# ===========================================================================
# Behavior 12 --- Symlink escape on src refused, external target intact
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_12_symlink_escape_on_src_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    # A directory OUTSIDE both sandbox roots, holding a real file.
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret = outside_dir / "secret.txt"
    secret.write_bytes(b"do-not-touch\n")
    try:
        os.symlink(outside_dir, art / "link")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = _move(tools, src="link", dst="b.txt")

    assert obs == "error: refusing to move outside artifacts dir: 'link'", obs
    # External dir + file NOT moved or deleted; no b.txt created.
    assert outside_dir.is_dir()
    assert secret.exists(), "external symlink target must not be moved/deleted"
    assert secret.read_bytes() == b"do-not-touch\n"
    assert not (art / "b.txt").exists()


# ===========================================================================
# Behavior 13 --- Symlink escape on DST refused (dst gate fires before write)
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_13_symlink_escape_on_dst_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    assert not _write(tools, "a.txt", "x").startswith("error:")

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    try:
        os.symlink(outside_dir, art / "link")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = _move(tools, src="a.txt", dst="link/stolen.txt")

    assert obs == "error: refusing to move outside artifacts dir: 'link/stolen.txt'", obs
    # The dst within-gate fired BEFORE any write-through-the-link:
    # a.txt is still present + unchanged, and no stolen.txt appears outside.
    assert (art / "a.txt").read_text() == "x", "src must not be moved"
    assert "a.txt" in tools.artifacts(), tools.artifacts()
    assert not (outside_dir / "stolen.txt").exists(), "no write leaked through the link"


# ===========================================================================
# Behavior 14 --- Untracked on-disk src is still movable
# ===========================================================================


def test_behavior_14_untracked_on_disk_src_is_movable(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    # Write DIRECTLY to artifacts_dir, bypassing write_file -> NOT tracked.
    (art / "orphan.txt").write_text("orphan-bytes")
    assert "orphan.txt" not in tools.artifacts(), tools.artifacts()

    obs = _move(tools, src="orphan.txt", dst="moved.txt")

    assert obs == "moved artifacts/orphan.txt -> artifacts/moved.txt", obs
    # Relocated on disk.
    assert not (art / "orphan.txt").exists()
    assert (art / "moved.txt").read_text() == "orphan-bytes"
    # The conditional src-drop caused no KeyError; dst got appended.
    assert tools.artifacts() == ["moved.txt"], tools.artifacts()


# ===========================================================================
# Behavior 15 --- move_file advertised in the unknown-tool message
# ===========================================================================


def test_behavior_15_unknown_tool_lists_move_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = tools.execute("does_not_exist", {})

    assert obs.startswith("error:"), obs
    assert "move_file" in obs, f"move_file missing from available-tools list:\n{obs}"
    # The prior write-side family stays listed too (order-independent).
    for tool in ("write_file", "append_file", "read_file", "remove_file"):
        assert tool in obs, f"{tool!r} missing from available-tools list:\n{obs}"


# ===========================================================================
# Behavior 16 --- The PLAN prompt advertises move_file
# ===========================================================================


def test_behavior_16_plan_prompt_advertises_move_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "move_file" in prompt, prompt


# ===========================================================================
# Backward-compat guard --- additive tool, no version bump (mirrors iters 13/33)
# ===========================================================================


def test_version_unchanged_additive_tool() -> None:
    assert proactive_loop.__version__ == "0.1.1"
