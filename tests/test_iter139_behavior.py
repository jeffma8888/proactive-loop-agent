"""Black-box behavior tests for commit-seq **factory iter 139** (state dir iter-132):
ONE workspace-relative namespace for every published ``ContextSignal.path``.

ISOLATION CONTRACT (honored): every expectation below was derived from this
iteration's spec (``pm.md`` "Expected Behaviors" 1-11) plus the conventions of the
existing modules under ``tests/`` (the ``_git_env``/``_git`` helpers follow
``tests/test_iter137_behavior.py``; the console-script driver follows
``tests/test_iter138_behavior.py``).  Nothing under ``src/`` was read, no upstream
stage note (engineer / reviewer / fix-review) was opened, and no ``git diff`` was
consulted.  Where the SHAPE of the output was needed it was obtained by RUNNING the
installed ``pla`` console script against throwaway fixture trees and reading stdout.

Fully offline and deterministic: synthetic ``tmp_path_factory`` trees only (never the
in-repo tree, so no collector can leak repo state -- iter-15 lesson), no network, no
API key, and NO DURATION IS ASSERTED ANYWHERE (roadmap row #129's standing
constraint).  Two behaviors need a signal that a non-git tree cannot produce (a
``path is None`` branch, and a path that is not expressible relative to the
workspace); those use a LOCAL ``git init`` -- an offline subprocess, run with global
and system config pointed at ``os.devnull`` so no developer alias, hook or config can
change the result -- and are skipped when ``git`` is absent.

SPEC AMBIGUITY, recorded as PM feedback rather than asserted (see ``tester.md``):
behavior 7's concrete clause ("at a sub-directory workspace no published path starts
with the sub-directory's own name") is measurably FALSE for the ``working_tree`` kind,
which publishes git-repo-root-relative paths and therefore forms a THIRD namespace the
spec's own two family lists do not contain -- behavior 5 in fact assumes
``working_tree`` has NO path at all.  The guarantee is asserted over the two families
the spec enumerates, and the ``working_tree`` case is asserted as behavior 11
(unnormalizable path published unchanged, scan still complete, no exception), which is
the reading the spec's own family definitions support.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# The spec's two families, quoted verbatim from "Expected Behaviors".
_PREFIXER_KINDS = frozenset(
    {
        "recent_file",
        "test_posture",
        "ci_config",
        "license",
        "git_commit",
        "dependency",
        "lockfile_drift",
        "large_file",
        "secret_file",
    }
)
_RELATIVIZER_KINDS = frozenset({"todo", "note", "syntax_error", "merge_conflict"})
_SPEC_FAMILIES = _PREFIXER_KINDS | _RELATIVIZER_KINDS

_requires_git = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="a local git is required for the no-path and git-root-relative cases",
)


def _console_script() -> Path:
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, "the `pla` console script must be installed"
    return script


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _scan(cwd: Path, workspace: str, *extra: str) -> dict:
    """The whole ``--json`` document for one scan, asserting a clean exit first."""
    proc = _run("signals", "--workspace", workspace, "--json", *extra, cwd=cwd)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    assert "Traceback" not in proc.stderr, proc.stderr
    return dict(json.loads(proc.stdout))


def _records(cwd: Path, workspace: str, *extra: str) -> list[dict]:
    return list(_scan(cwd, workspace, *extra)["signals"])


def _strip_line(path: str) -> str:
    """Drop a trailing ``:LINE`` suffix, which the spec allows on a published path."""
    head, sep, tail = path.rpartition(":")
    return head if sep and tail.isdigit() else path


def _pairs(records: list[dict]) -> list[tuple[str, str | None]]:
    return sorted((str(r["kind"]), r["path"]) for r in records)


def _paths(records: list[dict]) -> list[str]:
    return [str(r["path"]) for r in records if r["path"] is not None]


def _build(root: Path) -> None:
    """A tree where ONE file (``sub/pkg/mod.py``) is reported by BOTH families."""
    (root / "sub" / "pkg").mkdir(parents=True)
    (root / "sub" / "pkg" / "mod.py").write_text(
        "x = 1\n# TODO: alpha\n", encoding="utf-8"
    )
    (root / "keep.py").write_text("k = 5\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('name = "x"\n', encoding="utf-8")


@pytest.fixture(scope="module")
def ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("iter139_ws")
    _build(root)
    return root


def _git_env() -> dict[str, str]:
    """Deterministic identity, and a git that cannot see the developer's global or
    system config (convention borrowed from ``tests/test_iter137_behavior.py``)."""
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "t@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "t@test.com",
        "GIT_TERMINAL_PROMPT": "0",
    }


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=30,
    )
    assert result.returncode == 0, (
        f"test setup `git {' '.join(args)}` failed rc={result.returncode}: "
        f"{result.stderr.strip()!r}"
    )
    return result.stdout


def _committed_repo(root: Path) -> None:
    _build(root)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-qm", "init")


@pytest.fixture(scope="module")
def stashed_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A git repo with a stash entry -- the cheapest offline source of a signal whose
    ``path`` is None (``git_stash`` reports about the repo, not about a file)."""
    root = tmp_path_factory.mktemp("iter139_stash")
    _committed_repo(root)
    (root / "keep.py").write_text("k = 6\n", encoding="utf-8")
    _git(root, "stash", "-q")
    return root


@pytest.fixture(scope="module")
def dirty_git_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A git repo with a dirty TRACKED file under ``sub/pkg/`` -- this makes
    ``working_tree`` fire, whose path is relative to the GIT ROOT and therefore is not
    expressible relative to a ``sub`` workspace given as an absolute path."""
    root = tmp_path_factory.mktemp("iter139_dirty")
    _committed_repo(root)
    with (root / "sub" / "pkg" / "mod.py").open("a", encoding="utf-8") as handle:
        handle.write("dirty = 1\n")
    return root


# ======================================================================================
# Behavior 1 -- no published path is ever absolute.
# ======================================================================================
def test_b01_no_published_path_is_absolute_at_an_absolute_workspace(ws: Path) -> None:
    records = _records(ws, str(ws))
    assert records, "fixture precondition: the workspace must emit signals"
    offenders = [
        (r["kind"], r["path"])
        for r in records
        if r["path"] is not None and os.path.isabs(_strip_line(str(r["path"])))
    ]
    assert offenders == [], f"absolute paths published: {offenders}"
    # Every kind present is covered by the sweep above, prefixer and relativizer alike.
    kinds = {str(r["kind"]) for r in records}
    assert kinds & _PREFIXER_KINDS, f"no prefixer-family kind in the fixture: {kinds}"
    assert kinds & _RELATIVIZER_KINDS, f"no relativizer-family kind: {kinds}"


def test_b01_the_home_directory_never_leaks_into_the_published_artifact(ws: Path) -> None:
    """The README invites the user to commit a saved scan, so a machine-specific
    ``/Users/<name>/...`` string in it is a hygiene defect on a public repo."""
    home = str(Path.home())
    leaks = [(r["kind"], r["path"]) for r in _records(ws, str(ws)) if r["path"] and home in str(r["path"])]
    assert leaks == [], f"$HOME leaked into published paths: {leaks}"


# ======================================================================================
# Behavior 2 -- a file under the workspace is published workspace-relative, POSIX.
# ======================================================================================
def test_b02_a_file_under_the_workspace_is_published_workspace_relative_posix(ws: Path) -> None:
    recent = sorted(p for r in _records(ws, str(ws)) if r["kind"] == "recent_file" for p in [str(r["path"])])
    assert "sub/pkg/mod.py" in recent, recent
    assert str(ws / "sub" / "pkg" / "mod.py") not in recent, recent
    assert not any(p.startswith("./") for p in recent), recent
    assert not any("\\" in p for p in recent), f"non-POSIX separator published: {recent}"


# ======================================================================================
# Behavior 3 -- the workspace directory itself is spelled ".".
# ======================================================================================
@pytest.mark.parametrize("spelling", ["ABSOLUTE", "."])
def test_b03_the_workspace_directory_itself_is_spelled_dot(ws: Path, spelling: str) -> None:
    given = str(ws) if spelling == "ABSOLUTE" else spelling
    records = _records(ws, given)
    root_kinds = {str(r["kind"]) for r in records if r["path"] == "."}
    assert {"license", "ci_config", "test_posture"} <= root_kinds, (
        f"workspace-root signals must publish '.', got {_pairs(records)}"
    )


# ======================================================================================
# Behavior 4 -- a trailing ":LINE" suffix survives normalization.
# ======================================================================================
@pytest.mark.parametrize("spelling", ["ABSOLUTE", "."])
def test_b04_a_trailing_line_suffix_survives_normalization(ws: Path, spelling: str) -> None:
    given = str(ws) if spelling == "ABSOLUTE" else spelling
    todos = [str(r["path"]) for r in _records(ws, given) if r["kind"] == "todo"]
    assert todos == ["sub/pkg/mod.py:2"], todos


# ======================================================================================
# Behavior 5 -- `path is None` stays None.
# ======================================================================================
@_requires_git
@pytest.mark.parametrize("spelling", ["ABSOLUTE", "."])
def test_b05_a_signal_published_with_no_path_keeps_path_none(stashed_ws: Path, spelling: str) -> None:
    given = str(stashed_ws) if spelling == "ABSOLUTE" else spelling
    records = _records(stashed_ws, given)
    nopath = [r for r in records if str(r["kind"]) == "git_stash"]
    assert nopath, f"fixture precondition: a stash entry must emit git_stash; got {_pairs(records)}"
    assert [r["path"] for r in nopath] == [None] * len(nopath), (
        f"a no-path signal was rewritten: {_pairs(nopath)}"
    )


# ======================================================================================
# Behavior 6 -- the default `--workspace .` scan does not move.
# ======================================================================================
def test_b06_the_default_dot_workspace_publishes_no_absolute_and_no_dot_slash_path(ws: Path) -> None:
    records = _records(ws, ".")
    assert records, "fixture precondition: the workspace must emit signals"
    assert [(r["kind"], r["path"]) for r in records if r["path"] and os.path.isabs(str(r["path"]))] == []
    assert [(r["kind"], r["path"]) for r in records if str(r["path"]).startswith("./")] == []


def test_b06_the_namespace_does_not_depend_on_how_the_workspace_was_spelled(ws: Path) -> None:
    """The invocation-independence half of behavior 6: the SAME directory scanned as
    "." and as an absolute path publishes the same (kind, path) set."""
    assert _pairs(_records(ws, ".")) == _pairs(_records(ws, str(ws)))


# ======================================================================================
# Behavior 7 -- a sub-directory workspace publishes ONE namespace, not two.
# ======================================================================================
def test_b07_a_sub_directory_workspace_publishes_one_namespace(ws: Path) -> None:
    relative = _records(ws, "sub")
    absolute = _records(ws, str(ws / "sub"))
    assert _pairs(relative) == _pairs(absolute), (
        f"relative spelling {_pairs(relative)} != absolute spelling {_pairs(absolute)}"
    )
    for label, records in (("relative", relative), ("absolute", absolute)):
        prefixer = {_strip_line(p) for r in records if str(r["kind"]) in _PREFIXER_KINDS for p in _paths([r])}
        relativizer = {_strip_line(p) for r in records if str(r["kind"]) in _RELATIVIZER_KINDS for p in _paths([r])}
        assert "pkg/mod.py" in prefixer, f"{label}: prefixer paths {sorted(prefixer)}"
        assert "pkg/mod.py" in relativizer, f"{label}: relativizer paths {sorted(relativizer)}"
        offenders = [p for p in _paths(records) if _strip_line(p).split("/")[0] == "sub"]
        assert offenders == [], f"{label}: paths still carry the sub-dir's own name: {offenders}"


def test_b07_every_kind_present_agrees_on_the_namespace(ws: Path) -> None:
    """Registry-driven rather than a two-collector spot check (acceptance criterion):
    NO kind may publish a path outside the one namespace, so the two families cannot
    silently re-diverge as collectors are added."""
    records = _records(ws, str(ws / "sub"))
    kinds = {str(r["kind"]) for r in records}
    assert len(kinds) >= 4, f"fixture too thin to be a registry check: {sorted(kinds)}"
    bad = [
        (r["kind"], r["path"])
        for r in records
        if r["path"] is not None
        and (os.path.isabs(str(r["path"])) or str(r["path"]).startswith("./") or "\\" in str(r["path"]))
    ]
    assert bad == [], f"kinds outside the namespace: {bad}"


@_requires_git
def test_b07_the_two_spec_families_agree_even_inside_a_git_repo(dirty_git_ws: Path) -> None:
    """Same guarantee with the git-backed kinds present. Scoped to the two families the
    spec enumerates: `working_tree` is a THIRD, git-root-relative namespace and is
    covered by behavior 11 instead -- see the module docstring's ambiguity note."""
    sub = dirty_git_ws / "sub"
    relative = [r for r in _records(dirty_git_ws, "sub") if str(r["kind"]) in _SPEC_FAMILIES]
    absolute = [r for r in _records(dirty_git_ws, str(sub)) if str(r["kind"]) in _SPEC_FAMILIES]
    assert relative, "fixture precondition: the sub workspace must emit family signals"
    assert _pairs(relative) == _pairs(absolute), (
        f"relative {_pairs(relative)} != absolute {_pairs(absolute)}"
    )
    offenders = [p for p in _paths(relative) + _paths(absolute) if _strip_line(p).split("/")[0] == "sub"]
    assert offenders == [], offenders


# ======================================================================================
# Behavior 8 -- a baseline recorded at one spelling suppresses at another.
# ======================================================================================
def test_b08_a_baseline_recorded_at_one_spelling_suppresses_at_another(ws: Path, tmp_path: Path) -> None:
    proc = _run("signals", "--workspace", "sub", "--json", cwd=ws)
    assert proc.returncode == 0, proc.stderr
    baseline = tmp_path / "baseline.json"
    baseline.write_text(proc.stdout, encoding="utf-8")
    recorded = {
        str(r["kind"]) for r in json.loads(proc.stdout)["signals"] if str(r["kind"]) in _PREFIXER_KINDS
    }
    assert recorded, "fixture precondition: the baseline must hold prefixer-family findings"
    after = _records(ws, str(ws / "sub"), "--baseline", str(baseline))
    survivors = [(r["kind"], r["path"]) for r in after if str(r["kind"]) in recorded]
    assert survivors == [], (
        "a baseline recorded at the relative spelling failed to suppress the same "
        f"prefixer findings at the absolute spelling: {survivors}"
    )


# ======================================================================================
# Behavior 9 -- one `--exclude-path` pattern narrows both families together.
# ======================================================================================
def test_b09_one_exclude_path_pattern_narrows_both_families(ws: Path) -> None:
    sub = str(ws / "sub")
    before = _records(ws, sub)
    hits = {str(r["kind"]) for r in before if _strip_line(str(r["path"])) == "pkg/mod.py"}
    assert {"recent_file", "todo"} <= hits, (
        f"fixture precondition: both families must report pkg/mod.py; got {_pairs(before)}"
    )
    after = _records(ws, sub, "--exclude-path", "pkg/*")
    remaining = [(r["kind"], r["path"]) for r in after if _strip_line(str(r["path"])) == "pkg/mod.py"]
    assert remaining == [], f"one pattern narrowed only one family: {remaining}"


# ======================================================================================
# Behavior 10 -- the recorded workspace root is unchanged (still exactly as given).
# ======================================================================================
def test_b10_the_recorded_workspace_root_is_exactly_as_given(ws: Path) -> None:
    for given in (".", str(ws), "sub", str(ws / "sub")):
        assert _scan(ws, given)["workspace_root"] == given, given


# ======================================================================================
# Behavior 11 -- a path not under the workspace is left unchanged and never raises.
# ======================================================================================
@_requires_git
def test_b11_a_path_not_under_the_workspace_is_published_unchanged_without_raising(
    dirty_git_ws: Path,
) -> None:
    sub = dirty_git_ws / "sub"
    proc = _run("signals", "--workspace", str(sub), "--json", cwd=dirty_git_ws)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    assert "Traceback" not in proc.stderr, proc.stderr
    records = list(json.loads(proc.stdout)["signals"])
    unnormalizable = [str(r["path"]) for r in records if str(r["kind"]) == "working_tree"]
    assert unnormalizable, (
        "fixture precondition: a dirty tracked file must emit working_tree, whose path "
        f"is git-root-relative and so is not under the sub workspace; got {_pairs(records)}"
    )
    # Published unchanged, not rewritten to "." or "" and not made absolute.
    for path in unnormalizable:
        assert path not in (".", ""), unnormalizable
        assert not os.path.isabs(path), unnormalizable
    # The snapshot is COMPLETE, not partial: the normal kinds still came through.
    kinds = {str(r["kind"]) for r in records}
    assert {"recent_file", "todo"} <= kinds, sorted(kinds)
