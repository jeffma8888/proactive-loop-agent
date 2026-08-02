"""Black-box behavior tests for iteration 66 --- the ``replace_in_file`` loop tool
(the write-side EDIT primitive that completes the L1 sandbox's mutation family).

Iteration 66 adds ``replace_in_file(path, old, new)`` to the L1 ACT sandbox
(``ToolRegistry``) as the thirteenth tool and the missing in-place EDIT verb, sitting
between append and move in the write-side family: create(``write_file``) /
append(``append_file``) / **edit** / move(``move_file``) / delete(``remove_file``).
It substitutes EVERY literal occurrence of ``old`` with ``new`` inside ONE existing
artifact in a single deterministic ``str.replace`` call (reporting an accurate
``str.count`` count), so a dispatched goal can surgically change an artifact without a
read-whole-file / write-whole-file round trip. It resolves ``artifacts_dir`` ONLY
(never ``workspace_root``), validates the path with the shared ``_reject_unsafe``
guard FIRST, then a non-empty-``old`` arg check AFTER path-safety, then a resolved
``_within`` gate BEFORE any read/write, then existence and directory checks, and never
raises: every failure is an observation string starting ``"error:"``.

ISOLATION CONTRACT (honored): these tests are written from ``SPEC.md`` (the public
contract, S4.4) + this iteration's PM spec (``pm.md``) ONLY. They drive the PUBLIC
surface --- ``ToolRegistry.execute(...)`` / ``ToolRegistry.tool_names()`` /
``ToolRegistry.artifacts()``, ``GoalLoop._plan_prompt(...)`` for the
prompt-advertisement check, and the ``pla`` CLI via ``proactive_loop.cli.main(argv)
-> int`` --- and assert observable output / exit codes / on-disk artifacts. **No file
under ``src/`` was read, no engineer/reviewer note was read, and no ``git diff`` was
consulted.** The fourteen canonical tool names are encoded here as the spec-declared
ground facts, NOT imported from the implementation. Conventions (``tmp_path``
fixtures, scripted offline provider, symlink-skip idiom, no network / no API keys)
mirror ``tests/test_iter61_behavior.py`` (diff_files) and ``tests/test_iter35_behavior.py``
(the write-side symlink-escape idiom).
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
OLD_EMPTY_ERR = "error: replace_in_file 'old' must be non-empty"

# The 12 prior tool names (before iter-66) + the new one.
PRIOR_TOOLS = {
    "write_file",
    "append_file",
    "read_file",
    "list_files",
    "search_files",
    "find_files",
    "stat_file",
    "head_file",
    "remove_file",
    "move_file",
    "tail_file",
    "diff_files",
}
CANONICAL_TOOLS = PRIOR_TOOLS | {"replace_in_file", "read_lines"}


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_iter61_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _replace(tools: ToolRegistry, path=..., old=..., new=...) -> str:
    """Invoke the public execute() for replace_in_file.

    Passing a sentinel ``...`` for ``path``/``old``/``new`` OMITS that KEY entirely
    (to exercise the missing-key default path); otherwise the value is used verbatim.
    """
    args: dict = {}
    if path is not ...:
        args["path"] = path
    if old is not ...:
        args["old"] = old
    if new is not ...:
        args["new"] = new
    return tools.execute("replace_in_file", args)


def _write(tools: ToolRegistry, path: str, content: str) -> str:
    return tools.execute("write_file", {"path": path, "content": content})


def _read(tools: ToolRegistry, path: str) -> str:
    return tools.execute("read_file", {"path": path})


def _goal(title: str = "Surgically edit a generated artifact in place") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="change one substring in an artifact without a full read+rewrite round trip",
        suggested_first_steps=["replace the stale token in the drafted artifact"],
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


_requires_symlink = pytest.mark.skipif(
    not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform"
)


# ===========================================================================
# EB1 --- Registered in the tool surface (exactly 14 names)
# ===========================================================================


def test_eb01_registered_in_tool_surface(tmp_path: Path) -> None:
    names = ToolRegistry.tool_names()
    assert len(names) == 14, f"tool_names() must return 14 names; got {len(names)}: {names}"
    assert "replace_in_file" in names, names
    # All 12 prior names survive.
    for prior in PRIOR_TOOLS:
        assert prior in names, f"prior tool {prior!r} must still be registered; got {sorted(names)}"
    assert set(names) == CANONICAL_TOOLS, f"names must be exactly the canonical set; got {sorted(names)}"

    # Dispatch reaches the handler (not the unknown-tool path).
    tools, _, _ = _registry(tmp_path)
    _write(tools, "a.txt", "hello world")
    obs = _replace(tools, "a.txt", "world", "there")
    assert not obs.startswith("error: unknown tool"), obs

    # A bogus tool name lists replace_in_file among the available tools.
    unknown = tools.execute("__no_such_tool__", {})
    assert unknown.startswith("error:"), unknown
    assert "replace_in_file" in unknown, f"unknown-tool obs must list replace_in_file:\n{unknown}"


# ===========================================================================
# EB2 --- Advertised in the `pla tools` catalog (json + human)
# ===========================================================================


def test_eb02_pla_tools_json_replace_in_file_object(capsys) -> None:
    obj = _tools_json(capsys)
    tools = obj["tools"]

    assert len(tools) == 14, f"--json tools array must have 14 elements; got {len(tools)}"

    by_name = {t["name"]: t for t in tools}
    assert "replace_in_file" in by_name, f"--json catalog must include replace_in_file; got {sorted(by_name)}"
    rif = by_name["replace_in_file"]
    assert set(rif.keys()) == {"name", "access", "description"}, rif
    assert rif["access"] == "create-update", rif
    assert isinstance(rif["description"], str) and rif["description"].strip(), rif

    # Access token comes from the closed set --- no new access class introduced.
    for t in tools:
        assert t["access"] in {"read-only", "create-update", "move", "delete"}, t

    # Drift-guard: JSON name set EQUALS ToolRegistry.tool_names() and the canonical set.
    catalog_names = {t["name"] for t in tools}
    assert catalog_names == set(ToolRegistry.tool_names()), (
        f"drift-guard: catalog names must equal registry names.\n"
        f"catalog-only : {catalog_names - set(ToolRegistry.tool_names())}\n"
        f"registry-only: {set(ToolRegistry.tool_names()) - catalog_names}"
    )
    assert catalog_names == CANONICAL_TOOLS, sorted(catalog_names)


def test_eb02_pla_tools_human_replace_in_file_access(capsys) -> None:
    rc = main(["tools"])
    out = capsys.readouterr().out
    assert rc == 0, "`pla tools` must exit 0"

    # Every canonical tool is named.
    for name in CANONICAL_TOOLS:
        assert name in out, f"human catalog must name {name!r}; got:\n{out}"

    # Locate the replace_in_file line; its access token is exactly 'create-update'.
    line = None
    for raw in out.splitlines():
        stripped = raw.strip()
        if stripped and stripped.split()[0] == "replace_in_file":
            line = raw
            break
    assert line is not None, f"human catalog must have a replace_in_file line:\n{out}"

    parts = line.split()
    assert parts[1] == "create-update", f"replace_in_file access must be 'create-update'; line: {line!r}"
    for other in ("read-only", "move", "delete"):
        assert other not in line, f"replace_in_file line must emit no other access word; got {line!r}"


# ===========================================================================
# EB3 --- Advertised in the PLAN prompt (and keeps prior tools)
# ===========================================================================


def test_eb03_plan_prompt_advertises_replace_in_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "replace_in_file" in prompt, prompt
    for prior in ("write_file", "append_file", "read_file", "move_file", "remove_file", "diff_files"):
        assert prior in prompt, f"{prior} must remain advertised in the PLAN prompt"


# ===========================================================================
# EB4 --- Happy path, single occurrence
# ===========================================================================


def test_eb04_happy_path_single_occurrence(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    _write(tools, "notes.txt", "hello world")

    obs = _replace(tools, "notes.txt", "world", "there")

    assert obs == "replaced 1 occurrence(s) in artifacts/notes.txt", obs
    assert _read(tools, "notes.txt") == "hello there", _read(tools, "notes.txt")


# ===========================================================================
# EB5 --- Replaces ALL occurrences with an accurate count
# ===========================================================================


def test_eb05_replaces_all_occurrences(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    _write(tools, "seq.txt", "a-a-a")

    obs = _replace(tools, "seq.txt", "a", "b")

    assert obs == "replaced 3 occurrence(s) in artifacts/seq.txt", obs
    assert _read(tools, "seq.txt") == "b-b-b", _read(tools, "seq.txt")


# ===========================================================================
# EB6 --- Empty `new` deletes the substring (explicit "" AND omitted key)
# ===========================================================================


def test_eb06_empty_new_deletes_substring(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    # Explicit empty new.
    _write(tools, "a.txt", "foobar")
    obs_explicit = _replace(tools, "a.txt", "foo", "")
    assert obs_explicit == "replaced 1 occurrence(s) in artifacts/a.txt", obs_explicit
    assert _read(tools, "a.txt") == "bar", _read(tools, "a.txt")

    # Equivalently, OMITTING the `new` key entirely.
    _write(tools, "b.txt", "foobar")
    obs_omitted = _replace(tools, "b.txt", "foo")  # new key absent
    assert obs_omitted == "replaced 1 occurrence(s) in artifacts/b.txt", obs_omitted
    assert _read(tools, "b.txt") == "bar", _read(tools, "b.txt")


# ===========================================================================
# EB7 --- Text not found -> error, file untouched
# ===========================================================================


def test_eb07_text_not_found_untouched(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    _write(tools, "a.txt", "hello")

    obs = _replace(tools, "a.txt", "xyz", "q")

    assert obs == "error: text not found in artifacts/a.txt: 'xyz'", obs
    # No write occurred.
    assert _read(tools, "a.txt") == "hello", _read(tools, "a.txt")


# ===========================================================================
# EB8 --- Empty `old` rejected, file untouched (AFTER path-safety)
# ===========================================================================


def test_eb08_empty_old_rejected(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    _write(tools, "a.txt", "hello")

    # Explicit empty old.
    obs_explicit = _replace(tools, "a.txt", "", "x")
    assert obs_explicit == OLD_EMPTY_ERR, obs_explicit
    assert _read(tools, "a.txt") == "hello", _read(tools, "a.txt")

    # Equivalently, OMITTING the `old` key entirely.
    obs_omitted = _replace(tools, "a.txt", new="x")  # old key absent
    assert obs_omitted == OLD_EMPTY_ERR, obs_omitted
    assert _read(tools, "a.txt") == "hello", _read(tools, "a.txt")


def test_eb08_path_safety_precedes_old_check(tmp_path: Path) -> None:
    # The spec pins: the empty-`old` arg check is reported AFTER path-safety, so an
    # unsafe path + empty old must surface the PATH error, not the old error.
    tools, _, _ = _registry(tmp_path)

    assert _replace(tools, "../evil.txt", "") == TRAVERSAL_ERR.format(p="../evil.txt"), _replace(
        tools, "../evil.txt", ""
    )
    assert _replace(tools, "/etc/passwd", "") == ABSOLUTE_ERR.format(p="/etc/passwd"), _replace(
        tools, "/etc/passwd", ""
    )
    # Empty path + empty old -> the empty-path (path-safety) error wins.
    assert _replace(tools, "", "") == EMPTY_ERR, _replace(tools, "", "")


# ===========================================================================
# EB9 --- Missing target under artifacts
# ===========================================================================


def test_eb09_missing_target(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = _replace(tools, "nope.txt", "a", "b")

    assert obs == "error: no such artifact: 'nope.txt'", obs
    assert list(art.iterdir()) == [], list(art.iterdir())
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# EB10 --- Workspace-only path degrades to no-such-artifact (never writes through)
# ===========================================================================


def test_eb10_workspace_only_path_not_edited(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    # A file that exists ONLY under workspace_root (written directly, not via sandbox).
    (ws / "ws_only.txt").write_text("KEEP-token-KEEP")

    obs = _replace(tools, "ws_only.txt", "token", "X")

    assert obs == "error: no such artifact: 'ws_only.txt'", obs
    # Mutations resolve against artifacts_dir ONLY: the workspace file is untouched,
    # and nothing leaked into the artifacts dir either.
    assert (ws / "ws_only.txt").read_text() == "KEEP-token-KEEP", "workspace file was mutated"
    assert not (art / "ws_only.txt").exists(), "an artifact was created for a workspace-only path"
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# EB11 --- Path traversal refused (nothing read/written)
# ===========================================================================


def test_eb11_path_traversal_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    obs = _replace(tools, "../evil.txt", "a", "b")

    assert obs == TRAVERSAL_ERR.format(p="../evil.txt"), obs
    assert not (tmp_path / "evil.txt").exists()
    assert tools.artifacts() == [], tools.artifacts()


# ===========================================================================
# EB12 --- Absolute path refused
# ===========================================================================


def test_eb12_absolute_path_refused(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = _replace(tools, "/etc/passwd", "root", "x")

    assert obs == ABSOLUTE_ERR.format(p="/etc/passwd"), obs


# ===========================================================================
# EB13 --- Empty path refused (generic write-family message; explicit "" AND omitted)
# ===========================================================================


def test_eb13_empty_path_refused(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    assert _replace(tools, "", "a", "b") == EMPTY_ERR, _replace(tools, "", "a", "b")
    # OMITTING the path key entirely defaults to "" -> the same generic message.
    assert _replace(tools, old="a", new="b") == EMPTY_ERR, _replace(tools, old="a", new="b")


# ===========================================================================
# EB14 --- Symlink escaping the sandbox refused BEFORE any write
# ===========================================================================


@_requires_symlink
def test_eb14_symlink_escape_refused_target_intact(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    outside = tmp_path / "outside_target.txt"
    outside.write_text("SECRET-token-SECRET\n")
    try:
        os.symlink(outside, art / "link.txt")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = _replace(tools, "link.txt", "token", "X")

    assert obs == "error: refusing to edit outside artifacts dir: 'link.txt'", obs
    # Load-bearing invariant: nothing was written THROUGH the link.
    assert outside.read_text() == "SECRET-token-SECRET\n", "external target bytes were mutated"
    assert "link.txt" not in tools.artifacts(), tools.artifacts()


# ===========================================================================
# EB15 --- Directory refused
# ===========================================================================


def test_eb15_directory_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    (art / "subdir").mkdir()

    obs = _replace(tools, "subdir", "a", "b")

    assert obs == "error: refusing to edit a directory: 'subdir'", obs
    assert (art / "subdir").is_dir(), "directory must survive a refused edit"


# ===========================================================================
# EB16 --- A successful edit records the artifact in artifacts() exactly once
# ===========================================================================


def test_eb16_artifact_tracked_exactly_once_after_write_then_edit(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    _write(tools, "a.txt", "hello world")  # tracked once by write_file
    assert tools.artifacts().count("a.txt") == 1, tools.artifacts()

    _replace(tools, "a.txt", "world", "there")  # editing a file already tracked

    # No duplicate entry from the edit.
    assert tools.artifacts().count("a.txt") == 1, tools.artifacts()


def test_eb16_on_disk_only_file_is_added_to_artifacts(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    # A file that exists on disk under artifacts but was NOT written this run.
    (art / "preexisting.txt").write_text("alpha beta")
    assert tools.artifacts() == [], "pre-existing on-disk file must not be tracked yet"

    obs = _replace(tools, "preexisting.txt", "alpha", "gamma")

    assert obs == "replaced 1 occurrence(s) in artifacts/preexisting.txt", obs
    assert tools.artifacts().count("preexisting.txt") == 1, tools.artifacts()
    assert _read(tools, "preexisting.txt") == "gamma beta", _read(tools, "preexisting.txt")


# ===========================================================================
# EB17 --- Binary/undecodable file degrades to an error (never raises)
# ===========================================================================


def test_eb17_binary_file_never_raises(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)
    # Raw bytes that are not valid UTF-8.
    (art / "blob.bin").write_bytes(b"\xff\xfe\x00\x01binary\x80")

    obs = _replace(tools, "blob.bin", "a", "b")

    assert obs.startswith("error: tool 'replace_in_file' failed:"), obs


# ===========================================================================
# Backward-compat guard --- additive tool, NO __version__ bump
# ===========================================================================


def test_no_version_bump_additive_tool() -> None:
    assert proactive_loop.__version__ == "0.1.1", (
        f"replace_in_file is an additive tool: __version__ must stay '0.1.1'; "
        f"got {proactive_loop.__version__!r}"
    )
