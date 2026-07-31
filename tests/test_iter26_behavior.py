"""Black-box behavior tests for iteration 26 --- the read-only ``stat_file``
loop tool (a deterministic "describe one path" primitive).

Iteration 26 adds ``stat_file(path)`` to the L1 ACT sandbox (``ToolRegistry``):
the *describe* member of the discovery family (find / list / grep / describe /
read). It returns a single bounded line --- for a file
``<relpath>  type=file  bytes=<st_size>  lines=<byte-level splitlines() count>
ext=<suffix|(none)>`` and for a directory ``<relpath>  type=dir
entries=<direct-child count>`` (all direct children incl. hidden entries and
skip-dirs, non-recursive). It resolves ``artifacts_dir`` FIRST then
``workspace_root`` --- the SAME precedence as ``read_file`` (deliberately the
OPPOSITE of ``list_files`` / ``search_files`` / ``find_files``) so ``stat_file``
and ``read_file`` resolve the same copy. It is strictly read-only, deterministic
(no mtime / timestamp / permission field; the byte-level line count never
decodes so a binary file cannot fault it), and additive: existing tool contracts
and ``__version__`` are unchanged.

ISOLATION: these tests are written from the SPEC (§4.4) + the iteration's PM
spec ONLY. They drive the PUBLIC surface (``ToolRegistry.execute(...)``,
``ToolRegistry.artifacts()``, and ``GoalLoop._plan_prompt(...)`` for the
prompt-advertisement check) and assert observable output / on-disk artifacts.
They deliberately do NOT read ``src/``. Conventions (``tmp_path`` fixtures,
scripted offline provider, no network / no API keys) mirror
``tests/test_iter21_behavior.py``.

PM-FEEDBACK / spec note: Behavior 1's narrative claims the content
``"import os\\nprint(os.getcwd())\\n"`` is "28 bytes", but it is in fact 29
bytes (verified: ``len(content.encode()) == 29``). The spec's own DEFINITION
(``bytes == st_size``) is authoritative and clear, so this test encodes the
*definition* --- it computes the expected byte/line counts from the actual
content rather than pinning the narrative's off-by-one literal. The tool is
correct iff it reports ``st_size`` (29), which is what these tests assert.
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
# Shared helpers (mirroring tests/test_iter21_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _stat(tools: ToolRegistry, path: str | None = None, **extra) -> str:
    """Invoke the public execute() for stat_file with the given args.

    ``path=None`` omits the key entirely (to exercise the missing-key path)."""
    args: dict = dict(extra)
    if path is not None:
        args["path"] = path
    return tools.execute("stat_file", args)


def _lines(observation: str) -> list[str]:
    """Split an observation into its (newline-joined) lines."""
    return observation.split("\n")


def _expected_file(relpath: str, content: str, ext: str) -> str:
    """Build the EXACT expected one-line file-describe string per the spec
    definitions (bytes == st_size, lines == byte-level splitlines count,
    two spaces between fields)."""
    raw = content.encode()
    nbytes = len(raw)
    nlines = len(raw.splitlines())
    return f"{relpath}  type=file  bytes={nbytes}  lines={nlines}  ext={ext}"


def _goal(title: str = "Triage a path before reading it") -> CandidateGoal:
    return CandidateGoal(
        title=title,
        rationale="describe a path cheaply before spending context on a full read",
        suggested_first_steps=["stat the file to decide whether it is worth reading"],
    )


def _loop(tools: ToolRegistry) -> GoalLoop:
    """A GoalLoop wired to an (unused) scripted client --- only its prompt
    rendering is exercised, so no scripted responses are consumed."""
    return GoalLoop(ScriptedLLMClient([]), Settings(), tools, sleep=lambda _: None)


# ===========================================================================
# EB1 --- Describe a file: exact one-line format + determinism on repeat
# ===========================================================================


def test_behavior_01_describe_file_exact_format(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    content = "import os\nprint(os.getcwd())\n"  # 2 lines, 29 bytes (see spec note)
    (ws / "app.py").write_text(content)

    obs = _stat(tools, "app.py")

    expected = _expected_file("app.py", content, ".py")
    assert obs == expected, obs
    # Field-shape guardrails independent of the numeric values.
    assert obs.startswith("app.py  type=file  "), obs
    assert "bytes=29" in obs and "lines=2" in obs and obs.endswith("ext=.py"), obs
    # Two spaces between each field (never a single space).
    assert "  type=file  bytes=" in obs and "  lines=" in obs and "  ext=" in obs, obs
    # Byte-identical on a repeat call (deterministic; no timestamps).
    assert _stat(tools, "app.py") == obs, "stat_file must be deterministic on repeat"


# ===========================================================================
# EB2 --- Empty file -> bytes=0, lines=0
# ===========================================================================


def test_behavior_02_empty_file(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "empty.py").write_text("")

    obs = _stat(tools, "empty.py")

    assert obs == "empty.py  type=file  bytes=0  lines=0  ext=.py", obs


# ===========================================================================
# EB3 --- Trailing newline does not change the line count
# ===========================================================================


def test_behavior_03_trailing_newline_same_line_count(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "no_nl.txt").write_text("a\nb\nc")   # no final newline
    (ws / "with_nl.txt").write_text("a\nb\nc\n")

    obs_no = _stat(tools, "no_nl.txt")
    obs_nl = _stat(tools, "with_nl.txt")

    assert "lines=3" in obs_no, obs_no
    assert "lines=3" in obs_nl, obs_nl
    # And the exact strings match their definitions (bytes differ by 1).
    assert obs_no == _expected_file("no_nl.txt", "a\nb\nc", ".txt"), obs_no
    assert obs_nl == _expected_file("with_nl.txt", "a\nb\nc\n", ".txt"), obs_nl


# ===========================================================================
# EB4 --- ext=(none) for an extensionless file AND for a dotfile
# ===========================================================================


def test_behavior_04_ext_none(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "Makefile").write_text("all:\n")
    (ws / ".gitignore").write_text("*.pyc\n")

    mk = _stat(tools, "Makefile")
    gi = _stat(tools, ".gitignore")

    assert mk == "Makefile  type=file  bytes=5  lines=1  ext=(none)", mk
    assert "type=file" in mk and mk.endswith("ext=(none)"), mk
    # A leading-dot name has no suffix in Python -> ext=(none).
    assert "type=file" in gi and gi.endswith("ext=(none)"), gi
    assert gi.startswith(".gitignore  type=file  "), gi


# ===========================================================================
# EB5 --- Describe a directory: exact one-line format
# ===========================================================================


def test_behavior_05_describe_directory_exact_format(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "pkg").mkdir()
    (ws / "pkg" / "a.py").write_text("a\n")
    (ws / "pkg" / "sub").mkdir()

    obs = _stat(tools, "pkg")

    assert obs == "pkg  type=dir  entries=2", obs
    assert obs.startswith("pkg  type=dir  entries="), obs
    # A directory line carries NO bytes/lines/ext fields.
    assert "bytes=" not in obs and "lines=" not in obs and "ext=" not in obs, obs


# ===========================================================================
# EB6 --- entries counts hidden children and is non-recursive
# ===========================================================================


def test_behavior_06_entries_hidden_and_non_recursive(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    d = ws / "d"
    d.mkdir()
    (d / "visible.py").write_text("v\n")
    (d / ".hidden").write_text("h\n")
    nested = d / "nested"
    nested.mkdir()
    # Files INSIDE nested/ must NOT be counted toward d/'s entries.
    (nested / "inner1.py").write_text("1\n")
    (nested / "inner2.py").write_text("2\n")

    obs = _stat(tools, "d")

    # visible.py + .hidden + nested/  == 3 direct children (hidden counted).
    assert obs == "d  type=dir  entries=3", obs


# ===========================================================================
# EB7 --- Describe the root itself ("." -> type=dir, relpath ".")
# ===========================================================================


def test_behavior_07_describe_root(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    # Precedence is artifacts_dir FIRST for read_file/stat_file, so "." resolves
    # to the artifacts root; seed it with a known, distinct child count.
    (art / "one.txt").write_text("1\n")
    (art / "two.txt").write_text("2\n")
    (art / "sub").mkdir()
    (ws / "unrelated.py").write_text("x\n")  # a different count in the other root

    obs = _stat(tools, ".")

    n = len(list(art.iterdir()))
    assert n == 3, f"fixture sanity: expected 3 direct children in artifacts root, got {n}"
    assert obs == f".  type=dir  entries={n}", obs
    assert obs.startswith(".  type=dir  entries="), obs


# ===========================================================================
# EB8 --- Not found -> exact repr-quoted error
# ===========================================================================


def test_behavior_08_not_found_error(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    obs = _stat(tools, "does_not_exist.py")

    assert obs == "error: no such path: 'does_not_exist.py'", obs
    assert obs.startswith("error:") and "no such path" in obs, obs


# ===========================================================================
# EB9 --- Empty / missing path -> exact tool-specific error
# ===========================================================================


def test_behavior_09_empty_or_missing_path_error(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)

    missing = _stat(tools)      # {} -- no path key
    empty = _stat(tools, "")    # {"path": ""}

    expected = "error: stat_file requires a non-empty 'path'"
    assert missing == expected, missing
    assert empty == expected, empty
    assert missing.startswith("error:") and "path" in missing, missing


# ===========================================================================
# EB10 --- Traversal / absolute paths refused + nothing touched
# ===========================================================================


def test_behavior_10_traversal_and_absolute_refused(tmp_path: Path) -> None:
    tools, _, art = _registry(tmp_path)

    traversal = _stat(tools, "../secret")
    absolute = _stat(tools, "/etc/passwd")

    assert traversal.startswith("error:") and "traversal" in traversal, traversal
    assert absolute.startswith("error:") and "absolute" in absolute, absolute
    # Nothing outside the sandbox is touched on either rejection.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# EB11 --- Read-only: artifacts() unaffected by any call
# ===========================================================================


def test_behavior_11_read_only(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (ws / "f.py").write_text("hello\n")
    (ws / "dir").mkdir()
    (ws / "dir" / "child.py").write_text("c\n")

    file_obs = _stat(tools, "f.py")
    dir_obs = _stat(tools, "dir")
    nf_obs = _stat(tools, "nope.py")

    assert "type=file" in file_obs, file_obs
    assert "type=dir" in dir_obs, dir_obs
    assert nf_obs.startswith("error:"), nf_obs
    # Nothing was ever written: artifacts() empty and artifacts dir untouched.
    assert tools.artifacts() == []
    assert list(art.iterdir()) == []


# ===========================================================================
# EB12 --- Root precedence mirrors read_file (artifacts first)
# ===========================================================================


def test_behavior_12_precedence_artifacts_first(tmp_path: Path) -> None:
    tools, ws, art = _registry(tmp_path)
    (art / "dup.txt").write_text("AA\n")      # 3 bytes, 1 line
    (ws / "dup.txt").write_text("BBBBB\n")     # 6 bytes, 1 line

    stat_obs = _stat(tools, "dup.txt")
    read_obs = tools.execute("read_file", {"path": "dup.txt"})

    # stat_file describes the ARTIFACTS copy (not the workspace copy).
    assert stat_obs == "dup.txt  type=file  bytes=3  lines=1  ext=.txt", stat_obs
    # read_file resolves the SAME copy -> the two tools agree.
    assert "AA" in read_obs, read_obs
    assert "BBBBB" not in read_obs, read_obs


# ===========================================================================
# EB13 --- Workspace fallback when absent from artifacts
# ===========================================================================


def test_behavior_13_workspace_fallback(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    content = "def f():\n    return 1\n"
    (ws / "ws_only.py").write_text(content)

    obs = _stat(tools, "ws_only.py")

    assert obs == _expected_file("ws_only.py", content, ".py"), obs
    assert "type=file" in obs and obs.endswith("ext=.py"), obs


# ===========================================================================
# EB14 --- Symlink escape is not described (in-sandbox file still described)
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_14_symlink_escape_not_described(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "keep.py").write_text("keep\n")

    # A file OUTSIDE both sandbox roots, symlinked into the workspace as link.py.
    outside_file = tmp_path / "outside_target.py"
    outside_file.write_text("escaped file\n")
    try:
        os.symlink(outside_file, ws / "link.py")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    escape = _stat(tools, "link.py")
    ordinary = _stat(tools, "keep.py")

    # The escaping target is never described: it is refused as out-of-sandbox.
    assert escape.startswith("error:"), escape
    assert "no such path" in escape, escape
    # An ordinary in-sandbox file is still described normally.
    assert ordinary == _expected_file("keep.py", "keep\n", ".py"), ordinary


# ===========================================================================
# EB15 --- Unknown-tool hint lists ALL SEVEN tools (incl. stat_file)
# ===========================================================================


def test_behavior_15_unknown_tool_lists_all_seven_tools(tmp_path: Path) -> None:
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
    ):
        assert tool in obs, f"{tool!r} missing from available-tools list:\n{obs}"


# ===========================================================================
# EB16 --- PLAN prompt advertises stat_file
# ===========================================================================


def test_behavior_16_plan_prompt_advertises_stat_file(tmp_path: Path) -> None:
    tools, _, _ = _registry(tmp_path)
    loop = _loop(tools)
    state = RunState(goal=_goal())

    prompt = loop._plan_prompt(state)

    assert "stat_file" in prompt, prompt


# ===========================================================================
# EB17 --- Backward compatibility: version unchanged + prior tools intact
# ===========================================================================


def test_behavior_17_version_unchanged() -> None:
    # Additive tool -> no version bump (mirrors iter-13 search_files / iter-17
    # append_file / iter-21 find_files).
    assert proactive_loop.__version__ == "0.1.1"


def test_behavior_17_prior_tools_unchanged_smoke(tmp_path: Path) -> None:
    """Light smoke over the other six tools' public contracts to confirm the
    additive stat_file handler did not perturb them."""
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
    assert "src.txt:1: needle here" in _lines(s), s

    # find_files -> recursive basename glob.
    f = tools.execute("find_files", {"pattern": "src.txt"})
    assert _lines(f) == ["src.txt"], f
