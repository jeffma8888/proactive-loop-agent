"""Black-box behavior tests for iteration 96 --- the structural (behavior-
preserving) refactor of the L1 ACT-sandbox escape guard in ``search_files`` and
``find_files``.

Iteration 96 (bite 2 of the "fully type-hinted" mypy oracle) changes how
``_search_files`` / ``_find_files`` derive their ``(search_root, base_root)``
pair --- from two separate ``Path | None`` locals to a single ``Optional`` so
the ``None``-guard narrows BOTH structurally --- clearing the last 2
``mypy src/proactive_loop`` errors. The refactor is BEHAVIOR-PRESERVING: the
observable tool contracts are byte-identical.

These tests therefore RE-PIN the observable behavior across the refactor,
focusing on the two discriminating branches the PM spec calls out:
  * the second-root (``artifacts_dir``) ``base_root`` branch (a botched refactor
    would leave ``base_root`` ``None``/wrong on the fallback root), and
  * the security escape guard ``_within(full, base_root)`` still firing on a
    symlink that points OUTSIDE the sandbox.

ISOLATION: written from the SPEC + this iteration's PM spec ONLY. They drive the
PUBLIC surface (``ToolRegistry.execute(...)``) and assert observable output.
They deliberately do NOT read ``src/``. Conventions (``tmp_path`` fixtures, no
network / no API keys) mirror ``tests/test_iter13_behavior.py`` and
``tests/test_iter21_behavior.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.loop.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Shared helpers (mirroring tests/test_iter13_behavior.py + test_iter21_behavior.py)
# ---------------------------------------------------------------------------


def _registry(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """Build a ToolRegistry over a fresh (created) workspace + artifacts dir and
    return (registry, workspace_root, artifacts_dir)."""
    ws = tmp_path / "workspace"
    art = tmp_path / "artifacts"
    ws.mkdir()
    art.mkdir()
    return ToolRegistry(workspace_root=ws, artifacts_dir=art), ws, art


def _lines(observation: str) -> list[str]:
    """Split an observation into its (newline-joined) lines."""
    return observation.split("\n")


# ===========================================================================
# Behavior 1 --- search_files over a workspace_root directory
#   (workspace_root branch preserved by the refactor)
# ===========================================================================


def test_behavior_01_search_files_workspace_root_dir(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "sub").mkdir()
    (ws / "sub" / "a.txt").write_text("line one\nhello QTOKEN world\n")

    obs = tools.execute("search_files", {"query": "QTOKEN", "path": "sub"})

    # relpath is relative to the searched dir; 1-based line number, verbatim line.
    assert obs == "a.txt:2: hello QTOKEN world", obs
    assert "a.txt:2: hello QTOKEN world" in _lines(obs), obs


# ===========================================================================
# Behavior 2 (DISCRIMINATOR) --- search_files over an artifacts_dir-ONLY dir
#   Proves base_root is correctly set to artifacts_dir on the second-root
#   branch (not left None/wrong). workspace_root is searched FIRST; when the
#   dir exists ONLY under artifacts_dir the fallback root must win.
# ===========================================================================


def test_behavior_02_search_files_artifacts_dir_only(tmp_path: Path) -> None:
    tools, _ws, art = _registry(tmp_path)
    # 'onlyart/' exists ONLY under artifacts_dir, never under workspace_root.
    (art / "onlyart").mkdir()
    (art / "onlyart" / "b.txt").write_text("hello QTOKEN here\n")

    obs = tools.execute("search_files", {"query": "QTOKEN", "path": "onlyart"})

    assert obs == "b.txt:1: hello QTOKEN here", obs
    assert "b.txt:1: hello QTOKEN here" in _lines(obs), obs


# ===========================================================================
# Behavior 3 --- search_files unknown directory -> exact repr-quoted sentinel
#   (the `resolved is None` early-return guard)
# ===========================================================================


def test_behavior_03_search_files_unknown_directory(tmp_path: Path) -> None:
    tools, _ws, _art = _registry(tmp_path)

    obs = tools.execute("search_files", {"query": "QTOKEN", "path": "nope"})

    assert obs == "error: directory not found: 'nope'", obs
    assert obs.startswith("error:") and "directory not found" in obs


# ===========================================================================
# Behavior 4 --- search_files symlink-escape guard still fires
#   A file OUTSIDE the sandbox, symlinked in as link.txt, is excluded by
#   _within(full, base_root) before it is read. The escaping CONTENT must not
#   surface; an in-sandbox file that also matches proves the walk still ran.
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_04_search_files_symlink_escape_guard(tmp_path: Path) -> None:
    tools, ws, _art = _registry(tmp_path)
    # An in-sandbox file that DOES match -> proves the search actually ran.
    (ws / "inside.txt").write_text("needle INSIDE_OK\n")
    # A file OUTSIDE the sandbox root, symlinked in as link.txt.
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("needle SECRET_OUTSIDE_ROOT\n")
    try:
        os.symlink(outside, ws / "link.txt")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = tools.execute("search_files", {"query": "needle", "path": "."})

    # The in-sandbox file is found ...
    assert "inside.txt:1: needle INSIDE_OK" in _lines(obs), obs
    # ... but the escaping symlink is NOT read: neither its relpath nor its
    # (outside) content appears. (search_files' no-match sentinel echoes the
    # QUERY, not a filename, so "link.txt" as a substring is a safe assertion.)
    assert "link.txt" not in obs, obs
    assert "SECRET_OUTSIDE_ROOT" not in obs, obs

    # Direct probe: searching for the escaping content alone yields no matches.
    obs2 = tools.execute("search_files", {"query": "SECRET_OUTSIDE_ROOT", "path": "."})
    assert obs2 == "(no matches for 'SECRET_OUTSIDE_ROOT')", obs2


# ===========================================================================
# Behavior 5 --- find_files over a workspace_root directory
#   (workspace_root branch preserved by the refactor)
# ===========================================================================


def test_behavior_05_find_files_workspace_root_dir(tmp_path: Path) -> None:
    tools, ws, _ = _registry(tmp_path)
    (ws / "sub").mkdir()
    (ws / "sub" / "a.txt").write_text("content\n")

    obs = tools.execute("find_files", {"pattern": "a.txt", "path": "sub"})

    assert obs == "a.txt", obs
    assert _lines(obs) == ["a.txt"], obs


# ===========================================================================
# Behavior 6 (DISCRIMINATOR) --- find_files over an artifacts_dir-ONLY dir
#   base_root correctly resolves to artifacts_dir on the fallback root.
# ===========================================================================


def test_behavior_06_find_files_artifacts_dir_only(tmp_path: Path) -> None:
    tools, _ws, art = _registry(tmp_path)
    (art / "onlyart").mkdir()
    (art / "onlyart" / "b.txt").write_text("content\n")

    obs = tools.execute("find_files", {"pattern": "b.txt", "path": "onlyart"})

    assert obs == "b.txt", obs
    assert _lines(obs) == ["b.txt"], obs


# ===========================================================================
# Behavior 7 --- find_files unknown directory -> exact repr-quoted sentinel
# ===========================================================================


def test_behavior_07_find_files_unknown_directory(tmp_path: Path) -> None:
    tools, _ws, _art = _registry(tmp_path)

    obs = tools.execute("find_files", {"pattern": "x", "path": "nope"})

    assert obs == "error: directory not found: 'nope'", obs
    assert obs.startswith("error:") and "directory not found" in obs


# ===========================================================================
# Behavior 8 --- find_files symlink-escape guard still fires
#   A symlink to an OUTSIDE file, named link.py, is excluded by _within before
#   being listed. NOTE: find_files' no-match sentinel ECHOES the pattern
#   ("(no files matching 'link.py')"), so a naive `"link.py" not in obs`
#   substring check would FALSE-FAIL. Assert on OUTPUT SHAPE instead: the exact
#   no-match sentinel proves the only basename matching was filtered out, and
#   no `link.py` appears as a FOUND-file relpath line.
# ===========================================================================


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="os.symlink unavailable on this platform")
def test_behavior_08_find_files_symlink_escape_guard(tmp_path: Path) -> None:
    tools, ws, _art = _registry(tmp_path)
    outside = tmp_path / "outside_target.py"
    outside.write_text("escaped file\n")
    try:
        os.symlink(outside, ws / "link.py")
    except (OSError, NotImplementedError) as exc:  # unprivileged (e.g. Windows)
        pytest.skip(f"symlink creation not permitted: {exc}")

    obs = tools.execute("find_files", {"pattern": "link.py", "path": "."})

    # The escaping symlink is the only basename matching 'link.py' and it is
    # excluded -> the exact no-match sentinel (proves the guard fired).
    assert obs == "(no files matching 'link.py')", obs
    # And it never appears as a FOUND-file line (a bare `link.py` relpath line).
    # (The sentinel line as a whole != "link.py", so this is trap-safe.)
    assert "link.py" not in _lines(obs), obs

    # Corroboration: a broad *.py find also lists no escaping symlink.
    obs2 = tools.execute("find_files", {"pattern": "*.py", "path": "."})
    assert obs2 == "(no files matching '*.py')", obs2
    assert "link.py" not in _lines(obs2), obs2


# ===========================================================================
# Supplementary --- behavior-preserving refactor implies no version bump
#   (spec AC: __version__ stays 0.1.1). Cheap regression pin.
# ===========================================================================


def test_behavior_supplementary_version_unchanged() -> None:
    assert proactive_loop.__version__ == "0.1.1"
