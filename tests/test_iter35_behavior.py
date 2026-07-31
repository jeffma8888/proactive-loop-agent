"""Iteration-35 black-box behavior suite (ISOLATED tester).

An ADVERSARIAL regression suite that *proves* the L1 ACT-sandbox's remaining
untested security-boundary call sites in ``ToolRegistry``
(``src/proactive_loop/loop/tools.py``):

* the resolved-``_within`` symlink-escape guard on the two WRITE handlers
  ``write_file`` / ``append_file`` (the highest-severity vector --- a symlink
  escaping ``artifacts_dir`` here is an arbitrary out-of-sandbox file OVERWRITE,
  strictly worse than the read leaks proven in iters 13/21/26/29 or the scoped
  delete proven in iter-33), and
* the ``..`` / absolute / symlinked-dir traversal parity of ``list_files``
  (which had no traversal test at all).

SPEC §4.4/§5 promise writes are confined to ``artifacts_dir`` and that
path-traversal / symlink escapes are refused; the L1 loop feeds model-proposed
tool calls straight to these handlers, so on a public portfolio repo a *proven*
boundary beats an *asserted* one. Without this suite a refactor could silently
drop ``if not self._within(...)`` from the write/list handlers and the whole
suite would stay green.

This iteration is TEST-ONLY --- it adds no ``src/`` change and does not bump
``__version__`` (still ``0.1.1``); it only proves guards that are already
correct.

ISOLATION CONTRACT (honored): these tests were written from ``SPEC.md``
(§4.4/§5, the PUBLIC contract) plus this iteration's PM spec (the eight Expected
Behaviors) ONLY, and validated against the live product by driving the PUBLIC
surface --- ``ToolRegistry.execute(...)`` and ``ToolRegistry.artifacts()``.
They read NO ``src/``, monkeypatch no handler internals, and consult no
engineer/reviewer note or ``git diff``. Conventions (``tmp_path`` fixtures, the
portable symlink-skip idiom, no network / no API keys) mirror the established
symlink suites ``tests/test_iter{13,21,26,29,33}_behavior.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import proactive_loop
from proactive_loop.loop.tools import ToolRegistry

# EB1-EB4 exercise symlinks. Skip cleanly (never error) on a host that lacks
# ``os.symlink`` entirely; the per-call try/except below additionally skips a
# host that HAS the symbol but forbids its use (e.g. Windows without developer
# mode). Same portable idiom as iters 13/21/26/29/33.
_requires_symlink = pytest.mark.skipif(
    not hasattr(os, "symlink"),
    reason="os.symlink unavailable on this platform",
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers                                                          #
# --------------------------------------------------------------------------- #
def _sandbox(tmp_path: Path) -> tuple[ToolRegistry, Path, Path]:
    """A ToolRegistry over two SEPARATE, freshly-created dirs under ``tmp_path``.

    Both ``workspace_root`` and ``artifacts_dir`` must exist at construction
    (SPEC §4.4). Keeping them separate --- and putting every escape target under
    ``tmp_path`` itself (see :func:`_escape_target_dir`) --- guarantees the
    symlink destinations genuinely lie OUTSIDE both roots, so the ``_within``
    gate really has to refuse them rather than accidentally admitting them.
    """
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    return ToolRegistry(workspace_root=workspace, artifacts_dir=artifacts), workspace, artifacts


def _escape_target_dir(tmp_path: Path) -> Path:
    """Create + return ``tmp_path/'outside'`` --- a dir OUTSIDE both sandbox
    roots that every write-side / list symlink test points its link at."""
    outside = tmp_path / "outside"
    outside.mkdir()
    return outside


def _link_or_skip(target: Path, link: Path) -> None:
    """``os.symlink(target, link)`` or ``pytest.skip`` if the host forbids it.

    The extra guard (beyond ``_requires_symlink``) means an unprivileged host
    skips the security assertion cleanly instead of failing it for an unrelated
    environmental reason.
    """
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:  # unprivileged / unsupported
        pytest.skip(f"symlink creation not permitted on this host: {exc}")


# --------------------------------------------------------------------------- #
# EB1 --- write_file refuses a symlink resolving to an OUTSIDE file; the        #
#         external file's bytes are UNCHANGED (overwrite defense).             #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_eb1_write_file_symlink_to_outside_file_refused_and_target_intact(
    tmp_path: Path,
) -> None:
    tools, _workspace, artifacts = _sandbox(tmp_path)
    outside = _escape_target_dir(tmp_path)
    secret = outside / "secret.txt"
    secret.write_bytes(b"do-not-touch\n")
    # A textually-clean path INSIDE the sandbox whose final component RESOLVES
    # outside it: only the resolved-``_within`` gate (not ``_reject_unsafe``)
    # can catch this.
    _link_or_skip(secret, artifacts / "link.txt")

    obs = tools.execute("write_file", {"path": "link.txt", "content": "PWNED"})

    assert obs == "error: refusing to write outside artifacts dir: 'link.txt'", obs
    # Load-bearing invariant: nothing was written THROUGH the link.
    assert secret.exists(), "external symlink target was destroyed"
    assert secret.read_bytes() == b"do-not-touch\n", "external target bytes were mutated"
    assert "link.txt" not in tools.artifacts(), tools.artifacts()


# --------------------------------------------------------------------------- #
# EB2 --- write_file refuses a path whose INTERMEDIATE component is a symlinked #
#         dir escaping the sandbox; no file is created outside.                #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_eb2_write_file_intermediate_symlinked_dir_refused_no_outside_file(
    tmp_path: Path,
) -> None:
    tools, _workspace, artifacts = _sandbox(tmp_path)
    outside = _escape_target_dir(tmp_path)
    _link_or_skip(outside, artifacts / "link")  # symlinked DIR inside sandbox

    obs = tools.execute("write_file", {"path": "link/evil.txt", "content": "PWNED"})

    assert obs == "error: refusing to write outside artifacts dir: 'link/evil.txt'", obs
    # The gate must fire BEFORE any ensure_dir / write_text: no file may appear
    # through the escaping intermediate symlink, and the outside dir stays empty.
    assert not (outside / "evil.txt").exists(), "a file was created outside the sandbox"
    assert list(outside.iterdir()) == [], "the escape target dir was polluted"
    assert "link/evil.txt" not in tools.artifacts(), tools.artifacts()


# --------------------------------------------------------------------------- #
# EB3 --- append_file refuses a symlink resolving to an OUTSIDE file; the       #
#         external file's bytes are UNCHANGED (append-through defense).        #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_eb3_append_file_symlink_to_outside_file_refused_and_target_intact(
    tmp_path: Path,
) -> None:
    tools, _workspace, artifacts = _sandbox(tmp_path)
    outside = _escape_target_dir(tmp_path)
    log = outside / "log.txt"
    log.write_bytes(b"original\n")
    _link_or_skip(log, artifacts / "alink.txt")

    obs = tools.execute("append_file", {"path": "alink.txt", "content": "APPENDED"})

    assert obs == "error: refusing to write outside artifacts dir: 'alink.txt'", obs
    # Load-bearing invariant: nothing was appended THROUGH the link.
    assert log.exists(), "external symlink target was destroyed"
    assert log.read_bytes() == b"original\n", "external target bytes were mutated"
    assert "alink.txt" not in tools.artifacts(), tools.artifacts()


# --------------------------------------------------------------------------- #
# EB4 --- list_files refuses a symlinked directory escaping the sandbox and     #
#         leaks no outside filename.                                           #
# --------------------------------------------------------------------------- #
@_requires_symlink
def test_eb4_list_files_symlinked_dir_escape_refused_and_no_filename_leak(
    tmp_path: Path,
) -> None:
    tools, _workspace, artifacts = _sandbox(tmp_path)
    outside = _escape_target_dir(tmp_path)
    # A distinctive marker filename that MUST NOT appear in the observation.
    (outside / "outside_secret_marker.txt").write_text("x")
    _link_or_skip(outside, artifacts / "dlink")

    obs = tools.execute("list_files", {"path": "dlink"})

    # The escaping symlinked dir fails ``_within`` for both roots, so the
    # listing degrades to the not-found sentinel --- it is never enumerated.
    assert obs == "error: directory not found: 'dlink'", obs
    # Load-bearing invariant: no out-of-sandbox filename leaked into the output.
    assert "outside_secret_marker.txt" not in obs, obs


# --------------------------------------------------------------------------- #
# EB5 --- list_files refuses a '..' traversal path (traversal parity).          #
# --------------------------------------------------------------------------- #
def test_eb5_list_files_dotdot_traversal_refused(tmp_path: Path) -> None:
    tools, _workspace, _artifacts = _sandbox(tmp_path)

    obs = tools.execute("list_files", {"path": "../outside"})

    # ``_reject_unsafe`` catches the '..' segment textually, no symlink needed.
    assert obs == "error: path traversal ('..') is not allowed: '../outside'", obs


# --------------------------------------------------------------------------- #
# EB6 --- list_files refuses an absolute path.                                  #
# --------------------------------------------------------------------------- #
def test_eb6_list_files_absolute_path_refused(tmp_path: Path) -> None:
    tools, _workspace, _artifacts = _sandbox(tmp_path)

    # Assert on the STRING only --- never actually enumerate a real absolute dir.
    obs = tools.execute("list_files", {"path": "/etc"})

    assert obs == "error: absolute paths are not allowed: '/etc'", obs


# --------------------------------------------------------------------------- #
# EB7 --- Happy-path regression anchor: the three tools still behave normally   #
#         (guard against over-constraint).                                     #
#                                                                              #
# SPEC-EXAMPLE AMBIGUITY (flagged for PM): the spec phrases EB7 as "a fresh    #
# ToolRegistry over empty dirs" and expects list_files({"path": "."}) to       #
# contain "ok.txt". Verified live via the public API: write_file ALWAYS writes #
# to ``artifacts_dir`` while list_files({"path": "."}) resolves               #
# ``workspace_root`` FIRST --- so with SEPARATE empty roots, list_files(".")   #
# returns "(empty)" and does NOT observe the just-written artifact. The only   #
# ToolRegistry configuration in which the spec's literal assertion holds is    #
# one where the two roots COINCIDE (a valid, if degenerate, config). This test #
# therefore uses a shared root so "listing contains ok.txt" is true for a      #
# GENUINE reason (the file really is in the directory being listed), which is  #
# the most reasonable reading of "the three tools behave normally".            #
# --------------------------------------------------------------------------- #
def test_eb7_happy_path_three_tools_behave_normally(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    tools = ToolRegistry(workspace_root=root, artifacts_dir=root)

    write_obs = tools.execute("write_file", {"path": "ok.txt", "content": "hi"})
    assert write_obs == "wrote 2 chars to artifacts/ok.txt", write_obs
    assert "ok.txt" in tools.artifacts(), tools.artifacts()

    append_obs = tools.execute("append_file", {"path": "ok.txt", "content": "!"})
    assert append_obs == "appended 1 chars to artifacts/ok.txt", append_obs

    list_obs = tools.execute("list_files", {"path": "."})
    # Order-independent substring check: the just-written artifact is enumerated,
    # proving the adversarial suite constrains ONLY the escape path and leaves
    # the normal contracts intact.
    assert not list_obs.startswith("error:"), list_obs
    assert "ok.txt" in list_obs, list_obs


# --------------------------------------------------------------------------- #
# EB8 --- Additive, test-only iteration: no version bump.                       #
# --------------------------------------------------------------------------- #
def test_eb8_version_unchanged_test_only_iteration() -> None:
    assert proactive_loop.__version__ == "0.1.1"
