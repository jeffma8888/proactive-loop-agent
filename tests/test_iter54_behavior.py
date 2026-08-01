"""Black-box behavior tests for iteration 54 --- the read-only ``tail_file``
loop tool (a bounded, bottom-of-file "peek" primitive).

Iteration 54 adds ``tail_file(path, max_lines=40)`` to the L1 ACT sandbox
(``ToolRegistry``) as the mirror of iter-29's ``head_file``: the bottom-of-file
PEEK member of the bounded-observation family
(find / list / grep / describe(stat) / PEEK-top(head) / PEEK-bottom(tail) / read).
It returns the LAST ``max_lines`` lines of a file so a dispatched goal can inspect
the END of a grown artifact / log / config (the block just ``append_file``d, the
tail where errors surface) WITHOUT the unbounded ``read_file``. For a file with
``<= max_lines`` lines the return is **byte-identical** to ``read_file`` (no
trailer, original terminators preserved). Its ONE deliberate difference from
``head_file`` is the truncation shape: the trailer is a **LEADING** line
``... (showing last {max_lines} of {total} lines)`` followed by the file's last
``max_lines`` lines --- the exact opposite of ``head_file``'s **TRAILING** note
(so the actual tail lines sit last, closest to the model's next reasoning step).
It resolves ``artifacts_dir`` FIRST then ``workspace_root`` --- the SAME precedence
as ``read_file`` / ``head_file`` / ``stat_file`` --- is strictly read-only, additive
(existing tool contracts and ``__version__`` unchanged), and never raises: every
failure is an observation string starting ``"error:"``.

ISOLATION CONTRACT (honored): these tests are written from ``SPEC.md`` (§4.4, the
public contract) + this iteration's PM spec ONLY. They drive the PUBLIC surface
(``ToolRegistry.execute(...)``, ``ToolRegistry.tool_names()``,
``ToolRegistry.artifacts()``, ``GoalLoop._plan_prompt(...)`` for the
prompt-advertisement check, and the ``pla`` CLI via
``proactive_loop.cli.main(argv) -> int``) and assert observable output / exit codes
/ on-disk artifacts. **No file under ``src/`` was read, no engineer/reviewer note
was read, and no ``git diff`` was consulted.** The twelve canonical tool names and
the access mapping are encoded here as the spec-declared ground facts, NOT imported
from the implementation. Conventions (``tmp_path`` fixtures, scripted offline
provider, symlink-skip idiom, no network / no API keys) mirror
``tests/test_iter29_behavior.py`` (head_file) and ``tests/test_iter48_behavior.py``
(the tool catalog / drift-guard).
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

# Exact strings the spec pins verbatim.
ML_ERR = "error: tail_file 'max_lines' must be a positive integer"
PATH_ERR = "error: tail_file requires a non-empty 'path'"
NOT_FOUND = "error: file not found under artifacts or workspace: {p!r}"

# The twelve canonical tool names (order-independent; compared as a set).
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
}


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


def _tail(tools: ToolRegistry, path: str | None = None, **extra) -> str:
    """Invoke the public execute() for tail_file with the given args.

    ``path=None`` omits the key entirely (to exercise the missing-key path)."""
    args: dict = dict(extra)
    if path is not None:
        args["path"] = path
    return tools.execute("tail_file", args)


def _head(tools: ToolRegistry, path: str, **extra) -> str:
    args: dict = dict(extra)
    args["path"] = path
    return tools.execute("head_file", args)


def _read(tools: ToolRegistry, path: str) -> str:
    return tools.execute("read_file", {"path": path})


def _goal(title: str = "Inspect the tail of a grown artifact") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="peek at the bottom of a file cheaply before spending context on a full read",
        suggested_first_steps=["tail the file to inspect its most recently appended block"],
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
# EB1 --- Registered and dispatchable (12 names incl. tail_file)
# ===========================================================================


def test_eb01_registered_and_dispatchable(tmp_path: Path) -> None:
    names = ToolRegistry.tool_names()
    # Exactly 12 names, including tail_file.
    assert len(names) == 12, f"tool_names() must return 12 names; got {len(names)}: {names}"
    assert set(names) == CANONICAL_TOOLS, f"names must be exactly canonical set; got {sorted(names)}"
    assert "tail_file" in names, names

    tools, ws, _ = _registry(tmp_path)
    (ws / "a.txt").write_text("hi\n")
    # Dispatch reaches the handler (not the unknown-tool path).
    obs = _tail(tools, "a.txt")
    assert not obs.startswith("error: unknown tool"), obs

    # A bogus name lists tail_file among the available tools.
    unknown = tools.execute("__no_such_tool__", {})
    assert unknown.startswith("error:"), unknown
    assert "tail_file" in unknown, f"unknown-tool obs must list tail_file:\n{unknown}"


# ===========================================================================
# EB2 --- Short file (total <= N) -> byte-identical to read_file (no trailer)
# ===========================================================================


def test_eb02_short_file_byte_identical_to_read(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)

    # The spec's concrete pin: content "a\nb\n" with default N=40 -> "a\nb\n".
    (ws / "s.txt").write_text("a\nb\n")
    obs = _tail(tools, "s.txt")
    assert obs == "a\nb\n", obs
    assert obs == _read(tools, "s.txt"), obs
    assert "showing last" not in obs, obs

    # total == N exactly still gets NO trailer (boundary at the cap).
    (ws / "exact.txt").write_text("L1\nL2\nL3\n")  # 3 lines
    exact = _tail(tools, "exact.txt", max_lines=3)
    assert exact == "L1\nL2\nL3\n", exact
    assert exact == _read(tools, "exact.txt"), exact
    assert "showing last" not in exact, exact

    # max_lines LARGER than the line count -> full file, no trailer.
    big_cap = _tail(tools, "exact.txt", max_lines=999)
    assert big_cap == _read(tools, "exact.txt"), big_cap
    assert "showing last" not in big_cap, big_cap


# ===========================================================================
# EB3 --- Long file (total > N) -> LEADING trailer + LAST N lines
# ===========================================================================


def test_eb03_long_file_leading_trailer_and_last_n(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "l.txt").write_text("a\nb\nc\nd\ne\n")  # total = 5

    obs = _tail(tools, "l.txt", max_lines=2)

    # Exact spec string: leading trailer, then the LAST 2 lines with terminators.
    assert obs == "... (showing last 2 of 5 lines)\nd\ne\n", obs

    out_lines = obs.splitlines(keepends=True)
    # (a) first line is exactly the trailer.
    assert out_lines[0] == "... (showing last 2 of 5 lines)\n", out_lines
    # (b) remaining lines are the file's LAST N lines, in order, terminators kept.
    assert out_lines[1:] == ["d\n", "e\n"], out_lines
    # (c) earlier lines are absent.
    for gone in ("a\n", "b\n", "c\n"):
        assert gone not in "".join(out_lines[1:]), (gone, obs)

    # A final line without a trailing newline is preserved unterminated.
    (ws / "noeol.txt").write_text("a\nb\nc")  # total = 3, last line no EOL
    noeol = _tail(tools, "noeol.txt", max_lines=2)
    assert noeol == "... (showing last 2 of 3 lines)\nb\nc", noeol

    # total == N + 1 -> trailer appears (boundary just over the cap).
    over = _tail(tools, "l.txt", max_lines=4)
    assert over == "... (showing last 4 of 5 lines)\nb\nc\nd\ne\n", over


# ===========================================================================
# EB4 --- Complement to head_file (same file/N: head=FIRST, tail=LAST)
# ===========================================================================


def test_eb04_complement_to_head_file(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "l.txt").write_text("a\nb\nc\nd\ne\n")  # total = 5

    head_obs = _head(tools, "l.txt", max_lines=2)
    tail_obs = _tail(tools, "l.txt", max_lines=2)

    # head_file: FIRST N under a TRAILING note (out-of-scope contract preserved).
    assert head_obs == "a\nb\n... (showing first 2 of 5 lines)", head_obs
    # tail_file: LAST N under a LEADING note.
    assert tail_obs == "... (showing last 2 of 5 lines)\nd\ne\n", tail_obs
    # The two observations differ, and each is the correct end.
    assert head_obs != tail_obs, (head_obs, tail_obs)
    # head shows the first lines a,b; tail shows the last lines d,e.
    assert head_obs.startswith("a\nb\n"), head_obs
    assert tail_obs.endswith("d\ne\n"), tail_obs


# ===========================================================================
# EB5 --- max_lines defaults to 40
# ===========================================================================


def test_eb05_default_max_lines_is_40(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)

    # Exactly 40 lines and no max_lines -> byte-identical to read (no trailer).
    forty = "".join(f"line{i}\n" for i in range(1, 41))  # 40 lines
    (ws / "forty.txt").write_text(forty)
    forty_obs = _tail(tools, "forty.txt")
    assert forty_obs == forty, forty_obs
    assert forty_obs == _read(tools, "forty.txt"), forty_obs
    assert "showing last" not in forty_obs, forty_obs

    # 41 lines and no max_lines -> last 40 + '... (showing last 40 of 41 lines)' leading.
    fortyone = "".join(f"line{i}\n" for i in range(1, 42))  # 41 lines
    (ws / "fortyone.txt").write_text(fortyone)
    last_40 = "".join(f"line{i}\n" for i in range(2, 42))  # lines 2..41
    obs = _tail(tools, "fortyone.txt")
    assert obs == "... (showing last 40 of 41 lines)\n" + last_40, obs
    # Concretely: line1 dropped, line41 kept.
    assert "line1\n" not in obs.split("\n", 1)[1], obs  # not among the body lines
    assert obs.endswith("line41\n"), obs


# ===========================================================================
# EB6 --- max_lines accepts an integer-valued string
# ===========================================================================


def test_eb06_max_lines_integer_string(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "l.txt").write_text("a\nb\nc\nd\ne\n")  # total = 5

    as_int = _tail(tools, "l.txt", max_lines=5)
    as_str = _tail(tools, "l.txt", max_lines="5")
    assert as_int == as_str, (as_int, as_str)

    # Also for the truncating case.
    trunc_int = _tail(tools, "l.txt", max_lines=2)
    trunc_str = _tail(tools, "l.txt", max_lines="2")
    assert trunc_int == trunc_str == "... (showing last 2 of 5 lines)\nd\ne\n", (
        trunc_int,
        trunc_str,
    )


# ===========================================================================
# EB7 --- Invalid max_lines rejected (exact msg); nothing read
# ===========================================================================


def test_eb07_invalid_max_lines_rejected(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "f.txt").write_text("a\nb\nc\n")

    # 0, negative, non-integer string, float, both bools, and None -> exact error.
    for bad in (0, -1, "abc", 2.5, True, False, None):
        obs = _tail(tools, "f.txt", max_lines=bad)
        assert obs == ML_ERR, f"max_lines={bad!r} -> {obs!r}"

    # Nothing read, nothing written on rejection.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# EB8 --- Resolution precedence: artifacts_dir FIRST, then workspace_root
# ===========================================================================


def test_eb08_precedence_artifacts_first(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (art / "dup.txt").write_text("AA\nBB\n")      # artifacts copy
    (ws / "dup.txt").write_text("XX\nYY\nZZ\n")   # workspace copy (different)

    tail_obs = _tail(tools, "dup.txt")
    read_obs = _read(tools, "dup.txt")
    head_obs = _head(tools, "dup.txt")

    # tail_file resolves the ARTIFACTS copy --- the SAME copy read_file/head_file see.
    assert tail_obs == "AA\nBB\n", tail_obs
    assert tail_obs == read_obs, (tail_obs, read_obs)
    assert tail_obs == head_obs, (tail_obs, head_obs)
    assert "XX" not in tail_obs, tail_obs


# ===========================================================================
# EB9 --- Path-safety validated BEFORE max_lines
# ===========================================================================


def test_eb09_path_safety_before_max_lines(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    # Empty path -> exact non-empty-path error.
    assert _tail(tools, "") == PATH_ERR, _tail(tools, "")
    assert _tail(tools) == PATH_ERR, _tail(tools)  # missing key entirely

    # Traversal -> exact traversal error.
    assert _tail(tools, "../x") == "error: path traversal ('..') is not allowed: '../x'", _tail(
        tools, "../x"
    )
    # Absolute -> exact absolute-path error.
    assert _tail(tools, "/etc/passwd") == "error: absolute paths are not allowed: '/etc/passwd'", _tail(
        tools, "/etc/passwd"
    )

    # Unsafe path + bad max_lines -> the PATH-SAFETY error wins (not the ML error).
    trav = _tail(tools, "../x", max_lines=0)
    assert trav == "error: path traversal ('..') is not allowed: '../x'", trav
    assert trav != ML_ERR, trav

    empty_bad = _tail(tools, "", max_lines="abc")
    assert empty_bad == PATH_ERR, empty_bad
    assert empty_bad != ML_ERR, empty_bad


# ===========================================================================
# EB10 --- Missing / directory / symlink-escape -> not-found; never raises
# ===========================================================================


def test_eb10_missing_and_directory_not_found(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "adir").mkdir()

    missing = _tail(tools, "does_not_exist.txt")
    directory = _tail(tools, "adir")

    assert missing == NOT_FOUND.format(p="does_not_exist.txt"), missing
    assert directory == NOT_FOUND.format(p="adir"), directory
    # Identical to what read_file / head_file return for the same targets.
    assert missing == _read(tools, "does_not_exist.txt"), missing
    assert directory == _head(tools, "adir"), directory


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_eb10_symlink_escape_refused(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "keep.txt").write_text("keep-me\n")

    outside_file = tmp_path / "outside_target.txt"
    outside_file.write_text("escaped\n")
    try:
        os.symlink(outside_file, ws / "link.txt")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    escape = _tail(tools, "link.txt")
    ordinary = _tail(tools, "keep.txt")

    assert escape == NOT_FOUND.format(p="link.txt"), escape
    assert "escaped" not in escape, escape
    # An ordinary in-sandbox file is still read normally.
    assert ordinary == "keep-me\n", ordinary


def test_eb10_binary_file_never_raises(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "bin.dat").write_bytes(b"\xff\xfe\x00\x01\xff\xffnot-text")

    # Degrades to an error observation via execute()'s never-raise wrapper.
    obs = _tail(tools, "bin.dat")
    assert obs.startswith("error:"), obs


# ===========================================================================
# EB11 --- Read-only: artifacts() unaffected by any call sequence
# ===========================================================================


def test_eb11_read_only_no_artifacts(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "ok.txt").write_text("x\ny\nz\n")
    (art / "art_only.txt").write_text("p\nq\n")

    # A mix of success + error paths across both roots.
    _tail(tools, "ok.txt")
    _tail(tools, "ok.txt", max_lines=1)
    _tail(tools, "art_only.txt")
    _tail(tools, "missing.txt")
    _tail(tools, "../escape")
    _tail(tools, "/abs")
    _tail(tools, "ok.txt", max_lines=0)
    _tail(tools)

    # Nothing was ever tracked or written.
    assert tools.artifacts() == []
    # The pre-existing artifact file survives; no new file created.
    assert sorted(p.name for p in art.iterdir()) == ["art_only.txt"], list(art.iterdir())


# ===========================================================================
# EB12 --- Empty file (total == 0) -> "" byte-identical to read_file
# ===========================================================================


def test_eb12_empty_file(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "e.txt").write_text("")

    obs = _tail(tools, "e.txt")
    assert obs == "", repr(obs)
    assert obs == _read(tools, "e.txt"), repr(obs)
    assert "showing last" not in obs, obs
    # Default N and an explicit N both yield "" (0 <= N).
    assert _tail(tools, "e.txt", max_lines=1) == "", repr(_tail(tools, "e.txt", max_lines=1))


# ===========================================================================
# EB13 --- `pla tools` catalogs tail_file as read-only (human + --json)
# ===========================================================================


def test_eb13_pla_tools_human_catalogs_tail_file_read_only(capsys) -> None:
    rc = main(["tools"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools` must exit 0"

    # Find the tail_file catalog line (first token == tool name).
    tail_line = None
    for raw in out.splitlines():
        stripped = raw.strip()
        if stripped and stripped.split()[0] == "tail_file":
            tail_line = raw
            break
    assert tail_line is not None, f"human catalog must have a tail_file line:\n{out}"

    # Its access token is exactly 'read-only' and no OTHER access word appears.
    parts = tail_line.split()
    assert parts[1] == "read-only", f"tail_file access must be 'read-only'; line: {tail_line!r}"
    for other in ("create-update", "move", "delete"):
        assert other not in tail_line, f"tail_file line must emit no other access word; got {tail_line!r}"


def test_eb13_pla_tools_json_tail_file_object(capsys) -> None:
    obj = _tools_json(capsys)
    tools = obj["tools"]

    # 12 tools total in the --json array.
    assert len(tools) == 12, f"--json tools array must have 12 elements; got {len(tools)}"

    by_name = {t["name"]: t for t in tools}
    assert "tail_file" in by_name, f"--json catalog must include tail_file; got {sorted(by_name)}"
    tf = by_name["tail_file"]
    # Exactly the three keys, access read-only, description a non-empty str.
    assert set(tf.keys()) == {"name", "access", "description"}, tf
    assert tf["access"] == "read-only", tf
    assert isinstance(tf["description"], str) and tf["description"].strip(), tf

    # Drift-guard: JSON name set EQUALS ToolRegistry.tool_names().
    catalog_names = {t["name"] for t in tools}
    assert catalog_names == set(ToolRegistry.tool_names()), (
        f"drift-guard: catalog names must equal registry names.\n"
        f"catalog-only : {catalog_names - set(ToolRegistry.tool_names())}\n"
        f"registry-only: {set(ToolRegistry.tool_names()) - catalog_names}"
    )
    assert catalog_names == CANONICAL_TOOLS, sorted(catalog_names)


def test_eb13_pla_tools_human_lists_all_twelve(capsys) -> None:
    rc = main(["tools"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools` must exit 0"
    for name in CANONICAL_TOOLS:
        assert name in out, f"human catalog must name {name!r}; got:\n{out}"


# ===========================================================================
# Prompt advertisement + backward compatibility (acceptance criteria)
# ===========================================================================


def test_plan_prompt_advertises_tail_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "tail_file" in prompt, prompt
    # head_file's advertisement is preserved (out-of-scope contract intact).
    assert "head_file" in prompt, prompt


def test_version_unchanged() -> None:
    # Additive tool -> no version bump (mirrors iter-13 / 17 / 21 / 26 / 29).
    assert proactive_loop.__version__ == "0.1.1"


def test_head_file_contract_unchanged(tmp_path: Path) -> None:
    """Out-of-scope guard: head_file KEEPS its TRAILING note (not changed to a
    leading one to match tail_file)."""
    tools, ws, _ = _registry(tmp_path)
    (ws / "l.txt").write_text("a\nb\nc\nd\ne\n")  # total = 5
    head_obs = _head(tools, "l.txt", max_lines=2)
    assert head_obs == "a\nb\n... (showing first 2 of 5 lines)", head_obs
