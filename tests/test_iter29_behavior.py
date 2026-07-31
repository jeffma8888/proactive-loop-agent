"""Black-box behavior tests for iteration 29 --- the read-only ``head_file``
loop tool (a bounded, top-of-file "peek" primitive).

Iteration 29 adds ``head_file(path, max_lines=40)`` to the L1 ACT sandbox
(``ToolRegistry``): the *peek* member of the bounded-observation family
(find / list / grep / describe(stat) / PEEK(head) / read). It returns the first
``max_lines`` lines of a file so a dispatched goal can judge relevance BEFORE
committing context to a full ``read_file`` (the sandbox's only unbounded reader).
For a file with ``<= max_lines`` lines the return is **byte-identical** to
``read_file`` (no trailer, original terminators preserved); a longer file returns
its first ``max_lines`` lines plus a single trailer
``... (showing first {max_lines} of {total} lines)`` emitted ONLY when truncated
(``total > max_lines``). It resolves ``artifacts_dir`` FIRST then
``workspace_root`` --- the SAME precedence as ``read_file`` / ``stat_file`` --- so
``head_file(x)`` and ``read_file(x)`` read the same copy. It is strictly read-only,
additive (existing tool contracts and ``__version__`` unchanged), and never raises:
every failure is an observation string starting ``"error:"``.

ISOLATION: these tests are written from ``SPEC.md`` (§4.4, public contract) + this
iteration's PM spec ONLY. They drive the PUBLIC surface
(``ToolRegistry.execute(...)``, ``ToolRegistry.artifacts()`` and
``GoalLoop._plan_prompt(...)`` for the prompt-advertisement check) and assert
observable output / on-disk artifacts. They deliberately do NOT read ``src/`` or
any engineer/reviewer note or ``git diff``. Conventions (``tmp_path`` fixtures,
scripted offline provider, symlink-skip idiom, no network / no API keys) mirror
``tests/test_iter26_behavior.py``.
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

# Exact error strings the spec pins verbatim.
ML_ERR = "error: head_file 'max_lines' must be a positive integer"
PATH_ERR = "error: head_file requires a non-empty 'path'"


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_iter26_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _head(tools: ToolRegistry, path: str | None = None, **extra) -> str:
    """Invoke the public execute() for head_file with the given args.

    ``path=None`` omits the key entirely (to exercise the missing-key path)."""
    args: dict = dict(extra)
    if path is not None:
        args["path"] = path
    return tools.execute("head_file", args)


def _read(tools: ToolRegistry, path: str) -> str:
    return tools.execute("read_file", {"path": path})


def _goal(title: str = "Peek at a file before reading it") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="peek at the top of a file cheaply before spending context on a full read",
        suggested_first_steps=["head the file to decide whether it is worth reading in full"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


# ===========================================================================
# Behavior 1 --- Short file passthrough is byte-identical to read_file
# ===========================================================================


def test_behavior_01_short_file_byte_identical(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    content = "one\ntwo\nthree\n"
    (ws / "a.txt").write_text(content)

    obs = _head(tools, "a.txt")

    # Byte-identical to the original content: no trailer, terminators preserved.
    assert obs == content, obs
    # And identical to what read_file would return for the SAME path/copy.
    assert obs == _read(tools, "a.txt"), obs
    assert "showing first" not in obs, obs

    # A file with EXACTLY max_lines lines also gets no trailer (total == cap).
    (ws / "exact.txt").write_text("L1\nL2\nL3\n")  # 3 lines
    exact = _head(tools, "exact.txt", max_lines=3)
    assert exact == "L1\nL2\nL3\n", exact
    assert exact == _read(tools, "exact.txt"), exact
    assert "showing first" not in exact, exact


# ===========================================================================
# Behavior 2 --- Long file truncation + exact trailer marker
# ===========================================================================


def test_behavior_02_long_file_truncation_trailer(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "big.txt").write_text("L1\nL2\nL3\nL4\nL5\n")  # 5 lines

    obs = _head(tools, "big.txt", max_lines=2)

    # First 2 lines (terminators preserved) + the exact trailer for 5 total.
    assert obs == "L1\nL2\n... (showing first 2 of 5 lines)", obs

    # total == max_lines -> NO trailer, full content returned (== read_file).
    no_trailer = _head(tools, "big.txt", max_lines=5)
    assert no_trailer == "L1\nL2\nL3\nL4\nL5\n", no_trailer
    assert no_trailer == _read(tools, "big.txt"), no_trailer
    assert "showing first" not in no_trailer, no_trailer

    # total == max_lines + 1 -> trailer appears (boundary just over the cap).
    over = _head(tools, "big.txt", max_lines=4)
    assert over == "L1\nL2\nL3\nL4\n... (showing first 4 of 5 lines)", over


# ===========================================================================
# Behavior 3 --- Default max_lines is 40
# ===========================================================================


def test_behavior_03_default_max_lines_is_40(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)

    # <= 40 lines and no max_lines arg -> full content, no trailer.
    small = "".join(f"line{i}\n" for i in range(1, 11))  # 10 lines
    (ws / "small.txt").write_text(small)
    small_obs = _head(tools, "small.txt")
    assert small_obs == small, small_obs
    assert small_obs == _read(tools, "small.txt"), small_obs
    assert "showing first" not in small_obs, small_obs

    # Exactly 40 lines and no max_lines -> full content, no trailer.
    forty = "".join(f"line{i}\n" for i in range(1, 41))  # 40 lines
    (ws / "forty.txt").write_text(forty)
    forty_obs = _head(tools, "forty.txt")
    assert forty_obs == forty, forty_obs
    assert "showing first" not in forty_obs, forty_obs

    # > 40 lines and no max_lines -> first 40 + '... (showing first 40 of {total})'.
    big = "".join(f"line{i}\n" for i in range(1, 46))  # 45 lines
    (ws / "big40.txt").write_text(big)
    first_40 = "".join(f"line{i}\n" for i in range(1, 41))
    big_obs = _head(tools, "big40.txt")
    assert big_obs == first_40 + "... (showing first 40 of 45 lines)", big_obs


# ===========================================================================
# Behavior 4 --- max_lines accepts an int or an integer-valued string
# ===========================================================================


def test_behavior_04_max_lines_int_or_intlike_string(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "f.txt").write_text("a\nb\nc\nd\ne\n")  # 5 lines

    as_int = _head(tools, "f.txt", max_lines=3)
    as_str = _head(tools, "f.txt", max_lines="3")

    # Identical results; first 3 lines + trailer for 5 total.
    assert as_int == as_str, (as_int, as_str)
    assert as_int == "a\nb\nc\n... (showing first 3 of 5 lines)", as_int

    # max_lines LARGER than the line count -> full file, no trailer (Behavior 1).
    big_cap = _head(tools, "f.txt", max_lines=999)
    assert big_cap == "a\nb\nc\nd\ne\n", big_cap
    assert big_cap == _read(tools, "f.txt"), big_cap
    assert "showing first" not in big_cap, big_cap
    # A large integer-valued string behaves the same.
    assert _head(tools, "f.txt", max_lines="999") == big_cap


# ===========================================================================
# Behavior 5 --- Non-positive / non-integer max_lines rejected (exact msg)
# ===========================================================================


def test_behavior_05_bad_max_lines_rejected(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "f.txt").write_text("a\nb\nc\n")

    for bad in (0, -1, "abc", None, [1]):
        obs = _head(tools, "f.txt", max_lines=bad)
        assert obs == ML_ERR, f"max_lines={bad!r} -> {obs!r}"

    # Reads nothing and writes nothing on rejection.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


def test_behavior_05_path_safety_checked_before_max_lines(tmp_path: Path) -> None:
    """Check ORDER: a path-safety fault (Behaviors 6-7) is reported BEFORE
    max_lines validation, even when BOTH are invalid."""
    tools, _, _ = _registry(tmp_path)

    # Traversal path + bad max_lines -> traversal error wins (not the ML error).
    trav = _head(tools, "../secret", max_lines=0)
    assert trav.startswith("error:") and "traversal" in trav, trav
    assert trav != ML_ERR, trav

    # Empty path + bad max_lines -> non-empty-path error wins.
    empty = _head(tools, "", max_lines="abc")
    assert empty == PATH_ERR, empty


# ===========================================================================
# Behavior 6 --- Empty / missing path -> exact tool-specific error
# ===========================================================================


def test_behavior_06_empty_or_missing_path_error(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    missing = _head(tools)      # {} -- no path key
    empty = _head(tools, "")    # {"path": ""}

    assert missing == PATH_ERR, missing
    assert empty == PATH_ERR, empty
    assert missing.startswith("error:") and "path" in missing, missing


# ===========================================================================
# Behavior 7 --- Traversal / absolute paths refused + nothing touched
# ===========================================================================


def test_behavior_07_traversal_and_absolute_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    traversal = _head(tools, "../secret")
    absolute = _head(tools, "/etc/passwd")

    assert traversal.startswith("error:") and "traversal" in traversal, traversal
    assert absolute.startswith("error:") and "absolute" in absolute, absolute
    # Nothing read, no artifact created.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# Behavior 8 --- Missing file / directory target -> not-found error
# ===========================================================================


def test_behavior_08_missing_and_directory_target_not_found(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "adir").mkdir()

    missing = _head(tools, "does_not_exist.txt")
    directory = _head(tools, "adir")

    assert missing == "error: file not found under artifacts or workspace: 'does_not_exist.txt'", missing
    assert directory == "error: file not found under artifacts or workspace: 'adir'", directory
    for obs in (missing, directory):
        assert obs.startswith("error:") and "not found" in obs, obs


# ===========================================================================
# Behavior 9 --- Precedence: artifacts copy wins (same as read_file/stat_file)
# ===========================================================================


def test_behavior_09_precedence_artifacts_first(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (art / "dup.txt").write_text("AA\nBB\n")     # artifacts copy
    (ws / "dup.txt").write_text("XX\nYY\nZZ\n")  # workspace copy (different)

    head_obs = _head(tools, "dup.txt")
    read_obs = _read(tools, "dup.txt")

    # head_file returns the ARTIFACTS copy (not the workspace copy).
    assert head_obs == "AA\nBB\n", head_obs
    # read_file resolves the SAME copy -> the two tools agree.
    assert head_obs == read_obs, (head_obs, read_obs)
    assert "XX" not in head_obs, head_obs


# ===========================================================================
# Behavior 10 --- Workspace fallback when absent from artifacts
# ===========================================================================


def test_behavior_10_workspace_fallback(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    content = "def f():\n    return 1\n"
    (ws / "ws_only.py").write_text(content)

    obs = _head(tools, "ws_only.py")

    assert obs == content, obs
    assert obs == _read(tools, "ws_only.py"), obs


# ===========================================================================
# Behavior 11 --- Read-only: artifacts() unaffected by any call sequence
# ===========================================================================


def test_behavior_11_read_only_no_artifacts(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "ok.txt").write_text("x\ny\nz\n")

    # A mix of success and error paths.
    _head(tools, "ok.txt")
    _head(tools, "ok.txt", max_lines=1)
    _head(tools, "missing.txt")
    _head(tools, "../escape")
    _head(tools, "/abs")
    _head(tools, "ok.txt", max_lines=0)
    _head(tools)

    # Nothing was ever written: artifacts() empty and artifacts dir untouched.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# Behavior 12 --- Symlink escape refused (in-sandbox file still read)
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_12_symlink_escape_refused(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "keep.txt").write_text("keep-me\n")

    # A file OUTSIDE both sandbox roots, symlinked into the workspace as link.txt.
    outside_file = tmp_path / "outside_target.txt"
    outside_file.write_text("escaped\n")
    try:
        os.symlink(outside_file, ws / "link.txt")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    escape = _head(tools, "link.txt")
    ordinary = _head(tools, "keep.txt")

    # The escaping target is never read through: refused as out-of-sandbox.
    assert escape.startswith("error:") and "not found" in escape, escape
    assert "escaped" not in escape, escape
    # An ordinary in-sandbox file is still read normally.
    assert ordinary == "keep-me\n", ordinary


# ===========================================================================
# Behavior 13 --- Undecodable (binary) file never crashes
# ===========================================================================


def test_behavior_13_binary_file_never_crashes(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "bin.dat").write_bytes(b"\xff\xfe\x00\x01\xff\xffnot-text")

    obs = _head(tools, "bin.dat")

    # Degrades to an error observation via execute()'s never-raise wrapper.
    assert obs.startswith("error:"), obs


# ===========================================================================
# Behavior 14 --- PLAN prompt advertises head_file
# ===========================================================================


def test_behavior_14_plan_prompt_advertises_head_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "head_file" in prompt, prompt


# ===========================================================================
# Behavior 15 --- Unknown-tool hint lists head_file + all eight prior tools
# ===========================================================================


def test_behavior_15_unknown_tool_lists_head_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = tools.execute("no_such_tool", {})

    assert obs.startswith("error:"), obs
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
# Behavior 16 --- Backward compatibility: version unchanged + prior tools intact
# ===========================================================================


def test_behavior_16_version_unchanged() -> None:
    # Additive tool -> no version bump (mirrors iter-13 / 17 / 21 / 26).
    assert proactive_loop.__version__ == "0.1.1"


def test_behavior_16_prior_tools_unchanged_smoke(tmp_path: Path) -> None:
    """Light smoke over the prior tools' public contracts to confirm the
    additive head_file handler did not perturb them."""
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

    # list_files -> lists the artifact / workspace source.
    (ws / "src.txt").write_text("needle here\n")
    lst = tools.execute("list_files", {"path": "."})
    assert "src.txt" in lst, lst

    # search_files -> greps content (name/line/text form).
    s = tools.execute("search_files", {"query": "needle"})
    assert "src.txt:1: needle here" in s.split("\n"), s

    # find_files -> recursive basename glob.
    f = tools.execute("find_files", {"pattern": "src.txt"})
    assert f.split("\n") == ["src.txt"], f

    # stat_file -> the iter-26 describe primitive still works.
    st = tools.execute("stat_file", {"path": "src.txt"})
    assert "type=file" in st, st
