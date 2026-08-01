"""Black-box behavior tests for iteration 61 --- the read-only ``diff_files``
loop tool (the bounded, deterministic COMPARE primitive that completes the L1
sandbox's read family).

Iteration 61 adds ``diff_files(path_a, path_b)`` to the L1 ACT sandbox
(``ToolRegistry``) as the twelfth tool and the last member of the bounded-observation
read family: read / peek-top(``head_file``) / peek-bottom(``tail_file``) /
describe(``stat_file``) / list / find / grep / **COMPARE**. It returns a bounded,
stdlib-``difflib`` unified diff of two sandbox files so a dispatched goal can verify,
at the loop's CHECK step, WHAT CHANGED between two files (a rewritten artifact vs a
prior version / workspace reference / template / spec) WITHOUT pulling both whole
files into the model context. It resolves ``artifacts_dir`` FIRST then
``workspace_root`` on BOTH paths --- the SAME precedence as
``read_file`` / ``head_file`` / ``stat_file`` --- validates each path with the shared
``_reject_unsafe`` guard (``path_a`` fully resolved BEFORE ``path_b``), is strictly
read-only (``artifacts()`` never mutated), caps its emitted diff at 200 lines with a
trailing ``... (diff truncated at 200 lines)`` line, and never raises: every failure
is an observation string starting ``"error:"``.

ISOLATION CONTRACT (honored): these tests are written from ``SPEC.md`` (the public
contract, §4.4) + this iteration's PM spec (``pm.md``) ONLY. They drive the PUBLIC
surface --- ``ToolRegistry.execute(...)`` / ``ToolRegistry.tool_names()`` /
``ToolRegistry.artifacts()``, ``GoalLoop._plan_prompt(...)`` for the
prompt-advertisement check, and the ``pla`` CLI via ``proactive_loop.cli.main(argv)
-> int`` --- and assert observable output / exit codes / on-disk artifacts. **No file
under ``src/`` was read, no engineer/reviewer note was read, and no ``git diff`` was
consulted.** The thirteen canonical tool names are encoded here as the spec-declared
ground facts, NOT imported from the implementation. Conventions (``tmp_path``
fixtures, scripted offline provider, symlink-skip idiom, no network / no API keys)
mirror ``tests/test_iter54_behavior.py`` (tail_file).
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
EMPTY_ERR = "error: empty path is not allowed"
TRAVERSAL_ERR = "error: path traversal ('..') is not allowed: {p!r}"
ABSOLUTE_ERR = "error: absolute paths are not allowed: {p!r}"
NOT_FOUND = "error: file not found under artifacts or workspace: {p!r}"
TRUNC_TRAILER = "... (diff truncated at 200 lines)"

# The thirteen canonical tool names (order-independent; compared as a set).
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


def _diff(tools: ToolRegistry, a=..., b=..., **extra) -> str:
    """Invoke the public execute() for diff_files.

    Passing ``a``/``b`` as the sentinel ``...`` omits that KEY entirely (to exercise
    the missing-key default path); otherwise the value is used verbatim."""
    args: dict = dict(extra)
    if a is not ...:
        args["path_a"] = a
    if b is not ...:
        args["path_b"] = b
    return tools.execute("diff_files", args)


def _read(tools: ToolRegistry, path: str) -> str:
    return tools.execute("read_file", {"path": path})


def _goal(title: str = "Verify a rewritten artifact against a reference") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="compare two files at the CHECK step without burning context on full reads",
        suggested_first_steps=["diff the rewritten artifact against its prior version"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt rendering
    is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


def _tools_json(capsys) -> dict:
    """Run ``pla tools --json`` and return the parsed object (asserting exit 0)."""
    rc = main(["tools", "--json"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools --json` must exit 0"
    return json.loads(out)


def _all_different(n: int) -> tuple[str, str]:
    """Two texts of ``n`` fully-different single-token lines (no shared context).

    difflib emits header(2) + one hunk header(1) + n '-' lines + n '+' lines =
    ``2n + 3`` diff lines --- a precise knob for the 200-line truncation boundary."""
    a = "".join(f"a{i}\n" for i in range(n))
    b = "".join(f"b{i}\n" for i in range(n))
    return a, b


# ===========================================================================
# EB1 --- Registered & dispatchable (exactly 13 names incl. diff_files)
# ===========================================================================


def test_eb01_registered_and_dispatchable(tmp_path: Path) -> None:
    names = ToolRegistry.tool_names()
    assert len(names) == 13, f"tool_names() must return 13 names; got {len(names)}: {names}"
    assert "diff_files" in names, names
    assert set(names) == CANONICAL_TOOLS, f"names must be exactly the canonical set; got {sorted(names)}"

    tools, ws, _ = _registry(tmp_path)
    (ws / "a.txt").write_text("hi\n")
    (ws / "b.txt").write_text("bye\n")
    # Dispatch reaches the handler (not the unknown-tool path).
    obs = _diff(tools, "a.txt", "b.txt")
    assert not obs.startswith("error: unknown tool"), obs

    # A bogus name lists diff_files among the available tools.
    unknown = tools.execute("__no_such_tool__", {})
    assert unknown.startswith("error:"), unknown
    assert "diff_files" in unknown, f"unknown-tool obs must list diff_files:\n{unknown}"


# ===========================================================================
# EB2 --- Differing files -> a unified diff; the call NEVER writes
# ===========================================================================


def test_eb02_differing_files_unified_diff(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "a.txt").write_text("alpha\nshared\nbeta\n")
    (ws / "b.txt").write_text("alpha\nshared\ngamma\n")

    obs = _diff(tools, "a.txt", "b.txt")

    # (a) begins exactly with the ---/+++ file labels (caller paths, verbatim).
    assert obs.startswith("--- a.txt\n+++ b.txt\n"), repr(obs)
    lines = obs.splitlines()
    # (b) at least one hunk header line beginning with '@@'.
    assert any(ln.startswith("@@") for ln in lines), obs
    # (c) removed line prefixed '-', added line prefixed '+'.
    assert any(ln.startswith("-") and not ln.startswith("---") for ln in lines), obs
    assert any(ln.startswith("+") and not ln.startswith("+++") for ln in lines), obs
    assert "-beta" in lines, obs
    assert "+gamma" in lines, obs
    # (d) at least one context line prefixed with a single leading space.
    assert " alpha" in lines, obs
    assert " shared" in lines, obs

    # The call NEVER writes: artifacts() unchanged (nothing else written -> empty).
    assert tools.artifacts() == [], tools.artifacts()
    assert sorted(p.name for p in art.iterdir()) == [], list(art.iterdir())


def test_eb02_no_shared_context_still_valid_diff(tmp_path: Path) -> None:
    # Files with no shared context still produce a well-formed header + hunk.
    tools, ws, _ = _registry(tmp_path)
    (ws / "c1.txt").write_text("only\n")
    (ws / "c2.txt").write_text("changed\n")
    obs = _diff(tools, "c1.txt", "c2.txt")
    assert obs == "--- c1.txt\n+++ c2.txt\n@@ -1 +1 @@\n-only\n+changed\n", repr(obs)


# ===========================================================================
# EB3 --- Identical files -> explicit line, never empty
# ===========================================================================


def test_eb03_identical_files_explicit_line(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "a.txt").write_text("alpha\nbeta\n")
    (ws / "twin.txt").write_text("alpha\nbeta\n")  # byte-identical content, different name

    # Distinct paths, identical content.
    two = _diff(tools, "a.txt", "twin.txt")
    assert two == "files are identical: a.txt == twin.txt", repr(two)

    # The SAME path passed twice.
    same = _diff(tools, "a.txt", "a.txt")
    assert same == "files are identical: a.txt == a.txt", repr(same)

    # Never empty, and none of the diff markers appear.
    for out in (two, same):
        assert out != "", repr(out)
        assert "---" not in out and "+++" not in out and "@@" not in out, repr(out)


# ===========================================================================
# EB4 --- Precedence: artifacts_dir FIRST, then workspace_root
# ===========================================================================


def test_eb04_precedence_artifacts_first(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    # Same name 'x.txt' in BOTH roots, with DIFFERENT content.
    (art / "x.txt").write_text("ARTIFACT\ncontent\n")
    (ws / "x.txt").write_text("WORKSPACE\nis\ndifferent\n")

    # diff_files(x, x): BOTH sides resolve to the artifacts copy -> identical.
    same = _diff(tools, "x.txt", "x.txt")
    assert same == "files are identical: x.txt == x.txt", repr(same)
    # And it resolves the SAME copy read_file sees (the artifacts one).
    assert _read(tools, "x.txt") == "ARTIFACT\ncontent\n", _read(tools, "x.txt")


def test_eb04_artifact_diffed_against_workspace_only(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (art / "art.txt").write_text("one\n")
    (ws / "ref.txt").write_text("two\n")  # workspace-only reference

    obs = _diff(tools, "art.txt", "ref.txt")
    assert obs.startswith("--- art.txt\n+++ ref.txt\n"), repr(obs)
    assert "-one" in obs.splitlines(), obs
    assert "+two" in obs.splitlines(), obs


# ===========================================================================
# EB5 --- Path safety on EACH path; path_a validated before path_b
# ===========================================================================


def test_eb05_path_safety_each_side(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "safe.txt").write_text("s\n")

    # --- unsafe path_a (path_b safe+existing) -> path_a's error ---
    assert _diff(tools, "", "safe.txt") == EMPTY_ERR, _diff(tools, "", "safe.txt")
    assert _diff(tools, "../x", "safe.txt") == TRAVERSAL_ERR.format(p="../x"), _diff(
        tools, "../x", "safe.txt"
    )
    assert _diff(tools, "/etc/passwd", "safe.txt") == ABSOLUTE_ERR.format(p="/etc/passwd"), _diff(
        tools, "/etc/passwd", "safe.txt"
    )

    # --- unsafe path_b (path_a safe+existing) -> the SAME three errors ---
    assert _diff(tools, "safe.txt", "") == EMPTY_ERR, _diff(tools, "safe.txt", "")
    assert _diff(tools, "safe.txt", "../x") == TRAVERSAL_ERR.format(p="../x"), _diff(
        tools, "safe.txt", "../x"
    )
    assert _diff(tools, "safe.txt", "/etc/passwd") == ABSOLUTE_ERR.format(p="/etc/passwd"), _diff(
        tools, "safe.txt", "/etc/passwd"
    )

    # --- BOTH unsafe -> path_a's error wins (path_a validated first) ---
    both = _diff(tools, "../a", "/abs")
    assert both == TRAVERSAL_ERR.format(p="../a"), both
    assert both != ABSOLUTE_ERR.format(p="/abs"), both


# ===========================================================================
# EB6 --- Missing file -> not-found; path_a resolved before path_b
# ===========================================================================


def test_eb06_missing_file_not_found(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "safe.txt").write_text("s\n")

    # path_a (safe) exists under neither root -> path_a not-found.
    assert _diff(tools, "nope.txt", "safe.txt") == NOT_FOUND.format(p="nope.txt"), _diff(
        tools, "nope.txt", "safe.txt"
    )
    # path_a exists but path_b (safe) does not -> path_b not-found.
    assert _diff(tools, "safe.txt", "gone.txt") == NOT_FOUND.format(p="gone.txt"), _diff(
        tools, "safe.txt", "gone.txt"
    )
    # Same not-found string read_file returns for a missing target.
    assert _diff(tools, "nope.txt", "safe.txt") == _read(tools, "nope.txt"), _read(
        tools, "nope.txt"
    )


# ===========================================================================
# EB7 --- Truncation cap at 200 lines (trailer on its own fresh line)
# ===========================================================================


def test_eb07_truncation_over_200(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    # 300 fully-different lines each side -> 2*300+3 = 603 diff lines pre-truncation.
    a, b = _all_different(300)
    (ws / "big_a.txt").write_text(a)
    (ws / "big_b.txt").write_text(b)

    obs = _diff(tools, "big_a.txt", "big_b.txt")
    out_lines = obs.splitlines()

    # Trailer is present exactly once, and is the final line on its own fresh line.
    assert obs.count(TRUNC_TRAILER) == 1, obs[-200:]
    assert out_lines[-1] == TRUNC_TRAILER, out_lines[-3:]
    assert obs.endswith("\n" + TRUNC_TRAILER), obs[-80:]
    # Exactly 200 diff lines precede the trailer (200 body + 1 trailer = 201).
    assert len(out_lines) == 201, f"expected 200 diff lines + trailer = 201; got {len(out_lines)}"
    # The diff body still begins with the proper header.
    assert obs.startswith("--- big_a.txt\n+++ big_b.txt\n"), obs[:80]


def test_eb07_no_trailer_at_or_below_200(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)

    # Small diff (7 lines) -> no trailer.
    (ws / "s_a.txt").write_text("alpha\nshared\nbeta\n")
    (ws / "s_b.txt").write_text("alpha\nshared\ngamma\n")
    small = _diff(tools, "s_a.txt", "s_b.txt")
    assert TRUNC_TRAILER not in small, small

    # Boundary just under: 98 fully-different lines -> 2*98+3 = 199 diff lines (<=200).
    a, b = _all_different(98)
    (ws / "u_a.txt").write_text(a)
    (ws / "u_b.txt").write_text(b)
    under = _diff(tools, "u_a.txt", "u_b.txt")
    assert TRUNC_TRAILER not in under, under.splitlines()[-3:]
    assert len(under.splitlines()) == 199, len(under.splitlines())

    # Boundary just over: 99 fully-different lines -> 201 diff lines (>200) -> truncated.
    a2, b2 = _all_different(99)
    (ws / "o_a.txt").write_text(a2)
    (ws / "o_b.txt").write_text(b2)
    over = _diff(tools, "o_a.txt", "o_b.txt")
    assert over.splitlines()[-1] == TRUNC_TRAILER, over.splitlines()[-3:]
    assert len(over.splitlines()) == 201, len(over.splitlines())


# ===========================================================================
# EB8 --- Symlink escape refused on each side (target never read)
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_eb08_symlink_escape_refused(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "safe.txt").write_text("safe-content\n")

    outside = tmp_path / "outside_target.txt"
    outside.write_text("SECRET-ESCAPED\n")
    try:
        os.symlink(outside, ws / "link.txt")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    # As path_a: falls through to not-found; the target is never read.
    as_a = _diff(tools, "link.txt", "safe.txt")
    assert as_a == NOT_FOUND.format(p="link.txt"), as_a
    assert "SECRET-ESCAPED" not in as_a, as_a

    # As path_b: same refusal.
    as_b = _diff(tools, "safe.txt", "link.txt")
    assert as_b == NOT_FOUND.format(p="link.txt"), as_b
    assert "SECRET-ESCAPED" not in as_b, as_b


# ===========================================================================
# EB9 --- Binary / undecodable file -> error, never raises
# ===========================================================================


def test_eb09_binary_file_never_raises(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "safe.txt").write_text("text\n")
    (ws / "bin.dat").write_bytes(b"\xff\xfe\x00\x01not-text\xff\xff")

    # Binary on either side degrades to an error observation (never raises).
    a_bin = _diff(tools, "bin.dat", "safe.txt")
    b_bin = _diff(tools, "safe.txt", "bin.dat")
    assert a_bin.startswith("error: tool 'diff_files' failed:"), a_bin
    assert b_bin.startswith("error: tool 'diff_files' failed:"), b_bin


# ===========================================================================
# EB10 --- `pla tools` catalogs diff_files as read-only (human + --json)
# ===========================================================================


def test_eb10_pla_tools_human_catalogs_diff_files_read_only(capsys) -> None:
    rc = main(["tools"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools` must exit 0"

    diff_line = None
    for raw in out.splitlines():
        stripped = raw.strip()
        if stripped and stripped.split()[0] == "diff_files":
            diff_line = raw
            break
    assert diff_line is not None, f"human catalog must have a diff_files line:\n{out}"

    parts = diff_line.split()
    assert parts[1] == "read-only", f"diff_files access must be 'read-only'; line: {diff_line!r}"
    for other in ("create-update", "move", "delete"):
        assert other not in diff_line, f"diff_files line must emit no other access word; got {diff_line!r}"


def test_eb10_pla_tools_json_diff_files_object(capsys) -> None:
    obj = _tools_json(capsys)
    tools = obj["tools"]

    assert len(tools) == 13, f"--json tools array must have 13 elements; got {len(tools)}"

    by_name = {t["name"]: t for t in tools}
    assert "diff_files" in by_name, f"--json catalog must include diff_files; got {sorted(by_name)}"
    df = by_name["diff_files"]
    assert set(df.keys()) == {"name", "access", "description"}, df
    assert df["access"] == "read-only", df
    assert isinstance(df["description"], str) and df["description"].strip(), df

    # Drift-guard: JSON name set EQUALS ToolRegistry.tool_names() and the canonical set.
    catalog_names = {t["name"] for t in tools}
    assert catalog_names == set(ToolRegistry.tool_names()), (
        f"drift-guard: catalog names must equal registry names.\n"
        f"catalog-only : {catalog_names - set(ToolRegistry.tool_names())}\n"
        f"registry-only: {set(ToolRegistry.tool_names()) - catalog_names}"
    )
    assert catalog_names == CANONICAL_TOOLS, sorted(catalog_names)


def test_eb10_pla_tools_human_lists_all_thirteen(capsys) -> None:
    rc = main(["tools"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools` must exit 0"
    for name in CANONICAL_TOOLS:
        assert name in out, f"human catalog must name {name!r}; got:\n{out}"


# ===========================================================================
# EB11 --- PLAN prompt advertises diff_files (and keeps prior tools)
# ===========================================================================


def test_eb11_plan_prompt_advertises_diff_files(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "diff_files" in prompt, prompt
    # Out-of-scope contract intact: earlier read-family tools still advertised.
    for prior in ("read_file", "head_file", "tail_file", "search_files"):
        assert prior in prompt, f"{prior} must remain advertised in the PLAN prompt"


# ===========================================================================
# EB12 --- Missing args -> empty-path error (path_a defaults to "")
# ===========================================================================


def test_eb12_missing_args_empty_path_error(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "safe.txt").write_text("s\n")

    # No args at all.
    assert _diff(tools) == EMPTY_ERR, _diff(tools)
    # Only path_b supplied (path_a defaults to "" -> empty error, validated first).
    assert _diff(tools, b="safe.txt") == EMPTY_ERR, _diff(tools, b="safe.txt")
    # Only path_a supplied (path_b defaults to "" -> empty error).
    assert _diff(tools, "safe.txt") == EMPTY_ERR, _diff(tools, "safe.txt")

    # None of these ever wrote anything.
    assert tools.artifacts() == [], tools.artifacts()
    assert list(art.iterdir()) == [], list(art.iterdir())


# ===========================================================================
# Read-only invariant across a mixed call sequence + version guard
# ===========================================================================


def test_read_only_no_artifacts_across_sequence(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "ok.txt").write_text("x\ny\nz\n")
    (ws / "ok2.txt").write_text("x\nY\nz\n")
    (art / "art_only.txt").write_text("p\nq\n")

    # A mix of success + error paths across both roots.
    _diff(tools, "ok.txt", "ok2.txt")           # unified diff
    _diff(tools, "ok.txt", "ok.txt")            # identical line
    _diff(tools, "art_only.txt", "ok.txt")      # artifact vs workspace
    _diff(tools, "missing.txt", "ok.txt")       # not-found path_a
    _diff(tools, "ok.txt", "missing.txt")       # not-found path_b
    _diff(tools, "../escape", "ok.txt")         # traversal
    _diff(tools, "ok.txt", "/abs")              # absolute
    _diff(tools)                                 # empty

    # Nothing was ever tracked or written; the pre-existing artifact survives.
    assert tools.artifacts() == [], tools.artifacts()
    assert sorted(p.name for p in art.iterdir()) == ["art_only.txt"], list(art.iterdir())


def test_version_unchanged() -> None:
    # Additive tool -> no version bump (mirrors iter-13 / 17 / 21 / 26 / 29 / 54).
    assert proactive_loop.__version__ == "0.1.1"
