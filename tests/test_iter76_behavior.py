"""Black-box behavior tests for iteration 76 --- the read-only ``read_lines`` loop
tool (a FREE-anchor interior line-window primitive; the fourth and final reader).

Iteration 76 adds ``read_lines(path, start, end)`` to the L1 ACT sandbox
(``ToolRegistry``) as the FOURTH and final reader anchor, completing the reader
family full(``read_file``) / top(``head_file``) / bottom(``tail_file``) /
**window(``read_lines``)**. It returns the **1-based inclusive** line range
``[start, end]`` of a file --- an arbitrary INTERIOR window --- so a dispatched goal
can read the context AROUND a ``search_files`` hit (whose line numbers are 1-based)
without pulling the whole file through the unbounded ``read_file``. Its load-bearing
distinction from ``head_file``/``tail_file`` (FIXED-anchor peeks that emit a
truncation TRAILER) is that the return is a pure, byte-clean window
``"".join(text.splitlines(keepends=True)[start-1:end])`` with NO trailer and NO
decoration, round-tripping the file's own terminators verbatim. It resolves
``artifacts_dir`` FIRST then ``workspace_root`` (SAME precedence as
``read_file``/``head_file``/``tail_file``/``stat_file``), is strictly read-only,
additive (existing tool contracts and ``__version__`` unchanged), and never raises:
every failure is an observation string starting ``"error:"``.

ISOLATION CONTRACT (honored): these tests are written from ``SPEC.md`` (§4.4, the
public contract) + this iteration's PM spec (``pm.md``) ONLY. They drive the PUBLIC
surface --- ``ToolRegistry.execute(...)`` / ``ToolRegistry.tool_names()`` /
``ToolRegistry.artifacts()``, ``GoalLoop._plan_prompt(...)`` for the
prompt-advertisement check, and the ``pla`` CLI via ``proactive_loop.cli.main(argv)
-> int`` --- and assert observable output / exit codes / on-disk artifacts. **No file
under ``src/`` was read, no engineer/reviewer note was read, and no ``git diff`` was
consulted.** The fourteen canonical tool names are encoded here as the spec-declared
ground facts, NOT imported from the implementation. Conventions (``tmp_path``
fixtures, scripted offline provider, symlink-skip idiom, no network / no API keys)
mirror ``tests/test_iter54_behavior.py`` (tail_file) and
``tests/test_iter48_behavior.py`` (the tool catalog / drift-guard).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.cli import main
from proactive_loop.config import Settings
from proactive_loop.llm.client import ScriptedLLMClient
from proactive_loop.loop.executor import GoalLoop
from proactive_loop.loop.tools import ToolRegistry
from proactive_loop.models import CandidateGoal, RunState

# Exact strings the spec (SPEC.md §4.4) pins verbatim.
START_INT_ERR = "error: read_lines 'start' must be a positive integer"
END_INT_ERR = "error: read_lines 'end' must be a positive integer"
PATH_ERR = "error: read_lines requires a non-empty 'path'"
NOT_FOUND = "error: file not found under artifacts or workspace: {p!r}"
TRAVERSAL = "error: path traversal ('..') is not allowed: {p!r}"
ABSOLUTE = "error: absolute paths are not allowed: {p!r}"

# The fourteen canonical tool names (order-independent; compared as a set).
CANONICAL_TOOLS = {
    "write_file",
    "read_file",
    "list_files",
    "search_files",
    "append_file",
    "find_files",
    "stat_file",
    "head_file",
    "remove_file",
    "move_file",
    "tail_file",
    "diff_files",
    "replace_in_file",
    "read_lines",
}


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_iter54_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _rl(tools: ToolRegistry, path: str | None = None, **extra) -> str:
    """Invoke the public execute() for read_lines.

    ``path=None`` omits the key entirely (to exercise the missing-key path).
    A ``start``/``end`` of the sentinel ``...`` (Ellipsis) is treated as "omit
    the key" so we can exercise the missing-arg paths distinctly from a value."""
    args: dict = {}
    if path is not None:
        args["path"] = path
    for k in ("start", "end"):
        if k in extra and extra[k] is not ...:
            args[k] = extra[k]
    return tools.execute("read_lines", args)


def _read(tools: ToolRegistry, path: str) -> str:
    return tools.execute("read_file", {"path": path})


def _expected_slice(text: str, start: int, end: int) -> str:
    """The spec's exact definition of the in-range return."""
    return "".join(text.splitlines(keepends=True)[start - 1 : end])


def _goal(title: str = "Read the context around a grep hit") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="read a bounded interior window around a search_files line number",
        suggested_first_steps=["read_lines the window around the matched line"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


def _tools_json(capsys) -> dict:
    """Run ``pla tools --json`` and return the parsed object (asserting exit 0)."""
    rc = main(["tools", "--json"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools --json` must exit 0"
    return json.loads(out)


# ===========================================================================
# EB1 --- In-range interior slice (byte-equal, no trailer, read-only)
# ===========================================================================


def test_eb01_in_range_interior_slice(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    text = "L1\nL2\nL3\nL4\nL5\n"
    (ws / "f.txt").write_text(text)

    obs = _rl(tools, "f.txt", start=2, end=4)
    # Exactly lines 2..4 inclusive, terminators preserved.
    assert obs == "L2\nL3\nL4\n", repr(obs)
    # Byte-equal to the spec's slice definition.
    assert obs == _expected_slice(text, 2, 4), repr(obs)

    # NO trailer / NO decoration (unlike head_file/tail_file).
    assert "showing" not in obs, obs
    assert "..." not in obs, obs
    assert "of 5 lines" not in obs, obs

    # Whole-file window == read_file (byte-identical) when [1, total].
    assert _rl(tools, "f.txt", start=1, end=5) == text, repr(obs)
    assert _rl(tools, "f.txt", start=1, end=5) == _read(tools, "f.txt")

    # Read-only: no artifacts tracked by any read.
    assert tools.artifacts() == []


# ===========================================================================
# EB2 --- Single line (start == end == k)
# ===========================================================================


def test_eb02_single_line(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    text = "alpha\nbeta\ngamma\ndelta\n"
    (ws / "f.txt").write_text(text)

    for k, want in ((1, "alpha\n"), (2, "beta\n"), (4, "delta\n")):
        obs = _rl(tools, "f.txt", start=k, end=k)
        assert obs == want, (k, repr(obs))
        assert obs == _expected_slice(text, k, k), (k, repr(obs))

    # The last line without a terminator is returned unterminated.
    (ws / "noeol.txt").write_text("a\nb\nc")  # 3 lines, last no EOL
    assert _rl(tools, "noeol.txt", start=3, end=3) == "c", repr(
        _rl(tools, "noeol.txt", start=3, end=3)
    )


# ===========================================================================
# EB3 --- end clamps to EOF (no error, no trailer)
# ===========================================================================


def test_eb03_end_clamps_to_eof(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    text = "one\ntwo\nthree\n"  # T = 3
    (ws / "f.txt").write_text(text)

    # end just over EOF.
    obs = _rl(tools, "f.txt", start=2, end=99)
    assert obs == "two\nthree\n", repr(obs)
    assert obs == _expected_slice(text, 2, 999), repr(obs)
    assert not obs.startswith("error:"), obs
    assert "showing" not in obs and "..." not in obs, obs

    # start == T, end huge -> just the last line.
    assert _rl(tools, "f.txt", start=3, end=100) == "three\n", repr(
        _rl(tools, "f.txt", start=3, end=100)
    )

    # A no-EOL final line still clamps cleanly (terminator preserved verbatim).
    (ws / "noeol.txt").write_text("a\nb\nc")  # 3 lines, last no EOL
    assert _rl(tools, "noeol.txt", start=2, end=50) == "b\nc", repr(
        _rl(tools, "noeol.txt", start=2, end=50)
    )


# ===========================================================================
# EB4 --- artifacts_dir-first precedence (same copy as read_file)
# ===========================================================================


def test_eb04_precedence_artifacts_first(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (art / "dup.txt").write_text("AA\nBB\nCC\n")       # artifacts copy
    (ws / "dup.txt").write_text("XX\nYY\nZZ\nWW\n")    # workspace copy (different)

    win = _rl(tools, "dup.txt", start=1, end=2)
    # read_lines reads the ARTIFACTS copy --- the SAME copy read_file sees.
    assert win == "AA\nBB\n", repr(win)
    assert win == _expected_slice((art / "dup.txt").read_text(), 1, 2), repr(win)
    # A line unique to the artifacts copy is present; the workspace copy's is not.
    assert "AA" in win and "XX" not in win, win
    # Same underlying copy as read_file (which resolves artifacts first).
    assert _rl(tools, "dup.txt", start=1, end=3) == _read(tools, "dup.txt")


# ===========================================================================
# EB5 --- start past end of file -> error, nothing read
# ===========================================================================


def test_eb05_start_past_eof(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "f.txt").write_text("L1\nL2\nL3\n")  # T = 3

    obs = _rl(tools, "f.txt", start=9, end=10)
    assert obs.startswith("error:"), obs
    assert "read_lines 'start'" in obs, obs
    assert "is past end of file" in obs, obs
    # No file content returned.
    for gone in ("L1", "L2", "L3"):
        assert gone not in obs, (gone, obs)

    # An empty file (T == 0) makes start=1 already past EOF.
    (ws / "e.txt").write_text("")
    empty = _rl(tools, "e.txt", start=1, end=1)
    assert empty.startswith("error:"), empty
    assert "is past end of file" in empty, empty

    # start == total + 1 is the boundary (still past EOF).
    boundary = _rl(tools, "f.txt", start=4, end=4)
    assert boundary.startswith("error:") and "is past end of file" in boundary, boundary
    # start == total is valid (NOT past EOF).
    assert _rl(tools, "f.txt", start=3, end=3) == "L3\n"

    assert tools.artifacts() == []


# ===========================================================================
# EB6 --- start > end -> error, nothing read
# ===========================================================================


def test_eb06_start_greater_than_end(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "f.txt").write_text("L1\nL2\nL3\nL4\nL5\n")

    obs = _rl(tools, "f.txt", start=5, end=2)
    assert obs.startswith("error:"), obs
    assert "read_lines 'start'" in obs, obs
    assert "must be <= 'end'" in obs, obs
    for gone in ("L1", "L2", "L3", "L4", "L5"):
        assert gone not in obs, (gone, obs)

    # start == end is NOT an error (boundary).
    assert not _rl(tools, "f.txt", start=3, end=3).startswith("error:")
    assert tools.artifacts() == []


# ===========================================================================
# EB7 --- non-positive / non-integer / missing start -> error
# ===========================================================================


def test_eb07_invalid_start(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "f.txt").write_text("L1\nL2\nL3\n")

    for bad in (0, -1, 2.5, True, False, "abc", None):
        obs = _rl(tools, "f.txt", start=bad, end=3)
        assert obs == START_INT_ERR, f"start={bad!r} -> {obs!r}"

    # MISSING start key entirely.
    assert _rl(tools, "f.txt", start=..., end=3) == START_INT_ERR, _rl(
        tools, "f.txt", start=..., end=3
    )

    # An integer-VALUED string is accepted (mirrors head_file's max_lines).
    assert _rl(tools, "f.txt", start="1", end="2") == "L1\nL2\n", _rl(
        tools, "f.txt", start="1", end="2"
    )

    # Nothing read, nothing written.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# EB8 --- invalid end -> error; start validated FIRST
# ===========================================================================


def test_eb08_invalid_end_start_validated_first(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "f.txt").write_text("L1\nL2\nL3\n")

    # Valid start, bad end -> the 'end' error.
    for bad in (0, -1, 2.5, True, False, "abc", None):
        obs = _rl(tools, "f.txt", start=2, end=bad)
        assert obs == END_INT_ERR, f"end={bad!r} -> {obs!r}"

    # MISSING end key entirely (start valid).
    assert _rl(tools, "f.txt", start=2, end=...) == END_INT_ERR, _rl(
        tools, "f.txt", start=2, end=...
    )

    # BOTH bad -> the START error wins (start validated before end).
    both = _rl(tools, "f.txt", start=0, end=0)
    assert both == START_INT_ERR, both
    assert both != END_INT_ERR, both

    # An integer-valued string end is accepted.
    assert _rl(tools, "f.txt", start=1, end="2") == "L1\nL2\n"

    assert tools.artifacts() == []


# ===========================================================================
# EB9 --- path-safety errors reported BEFORE numeric validation
# ===========================================================================


def test_eb09_path_safety_before_numeric(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    # Empty path / missing path -> exact non-empty-path error.
    assert _rl(tools, "", start=1, end=1) == PATH_ERR, _rl(tools, "", start=1, end=1)
    assert _rl(tools, None, start=1, end=1) == PATH_ERR, _rl(tools, None, start=1, end=1)

    # Traversal / absolute -> the shared _reject_unsafe strings.
    assert _rl(tools, "../x", start=1, end=1) == TRAVERSAL.format(p="../x")
    assert _rl(tools, "/etc/passwd", start=1, end=1) == ABSOLUTE.format(p="/etc/passwd")

    # Path-safety wins even when start/end are ALSO invalid (checked first).
    assert _rl(tools, "", start=0, end=0) == PATH_ERR, _rl(tools, "", start=0, end=0)
    assert _rl(tools, "../x", start=0, end=0) == TRAVERSAL.format(p="../x")
    assert _rl(tools, "/abs", start="nope", end=-1) == ABSOLUTE.format(p="/abs")
    # Missing path + bad numbers still reports the path error (not the numeric one).
    assert _rl(tools, None, start=..., end=...) == PATH_ERR

    assert tools.artifacts() == []


# ===========================================================================
# EB10 --- missing file -> not-found error (the read_file string)
# ===========================================================================


def test_eb10_missing_file_not_found(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "adir").mkdir()

    missing = _rl(tools, "does_not_exist.txt", start=1, end=1)
    assert missing == NOT_FOUND.format(p="does_not_exist.txt"), missing
    # Identical to what read_file returns for the same target.
    assert missing == _read(tools, "does_not_exist.txt"), missing

    # A directory resolves to no readable file -> not-found.
    directory = _rl(tools, "adir", start=1, end=1)
    assert directory == NOT_FOUND.format(p="adir"), directory


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_eb10_symlink_escape_refused(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "keep.txt").write_text("keep-me\nsecond\n")

    outside_file = tmp_path / "outside_target.txt"
    outside_file.write_text("escaped\nsecret\n")
    try:
        os.symlink(outside_file, ws / "link.txt")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    escape = _rl(tools, "link.txt", start=1, end=1)
    assert escape == NOT_FOUND.format(p="link.txt"), escape
    assert "escaped" not in escape and "secret" not in escape, escape
    # An ordinary in-sandbox file is still windowed normally.
    assert _rl(tools, "keep.txt", start=1, end=1) == "keep-me\n"


# ===========================================================================
# EB11 --- registry + catalog integration (drift-guarded at 14)
# ===========================================================================


def test_eb11_registry_dispatchable_and_listed(tmp_path: Path) -> None:
    names = ToolRegistry.tool_names()
    assert len(names) == 14, f"tool_names() must return 14 names; got {len(names)}: {names}"
    assert set(names) == CANONICAL_TOOLS, f"names must be exactly canonical set; got {sorted(names)}"
    assert "read_lines" in names, names

    tools, ws, _ = _registry(tmp_path)
    (ws / "a.txt").write_text("hi\nthere\n")
    obs = _rl(tools, "a.txt", start=1, end=1)
    assert not obs.startswith("error: unknown tool"), obs

    # A bogus name lists read_lines among the available tools.
    unknown = tools.execute("__no_such_tool__", {})
    assert unknown.startswith("error:"), unknown
    assert "read_lines" in unknown, f"unknown-tool obs must list read_lines:\n{unknown}"


def test_eb11_pla_tools_human_catalogs_read_lines_read_only(capsys) -> None:
    rc = main(["tools"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools` must exit 0"

    line = None
    for raw in out.splitlines():
        stripped = raw.strip()
        if stripped and stripped.split()[0] == "read_lines":
            line = raw
            break
    assert line is not None, f"human catalog must have a read_lines line:\n{out}"

    parts = line.split()
    assert parts[1] == "read-only", f"read_lines access must be 'read-only'; line: {line!r}"
    for other in ("create-update", "move", "delete"):
        assert other not in line, f"read_lines line must emit no other access word; got {line!r}"


def test_eb11_pla_tools_json_read_lines_object(capsys) -> None:
    obj = _tools_json(capsys)
    tools = obj["tools"]
    assert len(tools) == 14, f"--json tools array must have 14 elements; got {len(tools)}"

    by_name = {t["name"]: t for t in tools}
    assert "read_lines" in by_name, f"--json catalog must include read_lines; got {sorted(by_name)}"
    rl = by_name["read_lines"]
    assert set(rl.keys()) == {"name", "access", "description"}, rl
    assert rl["access"] == "read-only", rl
    assert isinstance(rl["description"], str) and rl["description"].strip(), rl

    # Drift-guard: JSON name set EQUALS ToolRegistry.tool_names() (the anti-rot guard).
    catalog_names = {t["name"] for t in tools}
    assert catalog_names == set(ToolRegistry.tool_names()), (
        f"drift-guard: catalog names must equal registry names.\n"
        f"catalog-only : {catalog_names - set(ToolRegistry.tool_names())}\n"
        f"registry-only: {set(ToolRegistry.tool_names()) - catalog_names}"
    )
    assert catalog_names == CANONICAL_TOOLS, sorted(catalog_names)


def test_eb11_pla_tools_human_lists_all_fourteen(capsys) -> None:
    rc = main(["tools"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools` must exit 0"
    for name in CANONICAL_TOOLS:
        assert name in out, f"human catalog must name {name!r}; got:\n{out}"


def test_eb11_spec_tools_count_matches_registry() -> None:
    """SPEC §4.4 'array of 14 {name, access, description} objects' == registry len."""
    import re

    spec = (Path(__file__).resolve().parents[1] / "SPEC.md").read_text()
    matches = re.findall(r"array of (\d+) `\{name, access, description\}` objects", spec)
    assert len(matches) == 1, f"SPEC must pin the tools-count phrase exactly once; got {matches}"
    assert int(matches[0]) == len(ToolRegistry.tool_names()) == 14, (
        f"SPEC count {matches[0]} must equal registry len {len(ToolRegistry.tool_names())}"
    )


# ===========================================================================
# EB12 --- never raises; binary degrades cleanly
# ===========================================================================


def test_eb12_binary_and_bad_inputs_never_raise(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "bin.dat").write_bytes(b"\xff\xfe\x00\x01\xff\xffnot-text")

    # A binary target degrades to an error observation, not a traceback.
    obs = _rl(tools, "bin.dat", start=1, end=1)
    assert obs.startswith("error:"), obs

    # A whole gauntlet of bad inputs never raises out of execute().
    for call in (
        lambda: _rl(tools, "bin.dat", start=1, end=1),
        lambda: _rl(tools, "missing.txt", start=1, end=1),
        lambda: _rl(tools, "../escape", start=1, end=1),
        lambda: _rl(tools, "/abs", start=1, end=1),
        lambda: _rl(tools, "", start=1, end=1),
        lambda: _rl(tools, None, start=..., end=...),
        lambda: _rl(tools, "bin.dat", start=0, end=0),
        lambda: _rl(tools, "bin.dat", start=5, end=2),
    ):
        result = call()  # must not raise
        assert isinstance(result, str), result

    assert tools.artifacts() == []


# ===========================================================================
# Prompt advertisement + backward compatibility (acceptance criteria)
# ===========================================================================


def test_plan_prompt_advertises_read_lines(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)
    assert "read_lines" in prompt, prompt
    # Sibling readers' advertisements are preserved (out-of-scope contract intact).
    for sib in ("read_file", "head_file", "tail_file"):
        assert sib in prompt, (sib, prompt)


def test_version_unchanged() -> None:
    # Additive tool -> no version bump (mirrors iter-13 / 29 / 54 / 56).
    assert proactive_loop.__version__ == "0.1.1"


def test_sibling_reader_contracts_unchanged(tmp_path: Path) -> None:
    """Out-of-scope guard: head_file/tail_file KEEP their truncation trailers;
    read_lines is the trailer-free window. read_file is unchanged."""
    tools, ws, _ = _registry(tmp_path)
    (ws / "l.txt").write_text("a\nb\nc\nd\ne\n")  # total = 5

    head_obs = tools.execute("head_file", {"path": "l.txt", "max_lines": 2})
    tail_obs = tools.execute("tail_file", {"path": "l.txt", "max_lines": 2})
    window = _rl(tools, "l.txt", start=2, end=3)

    # head/tail still emit their trailers; read_lines never does.
    assert "showing first 2 of 5 lines" in head_obs, head_obs
    assert "showing last 2 of 5 lines" in tail_obs, tail_obs
    assert "showing" not in window and "..." not in window, window
    # The interior window is exactly lines 2..3, byte-clean.
    assert window == "b\nc\n", repr(window)
