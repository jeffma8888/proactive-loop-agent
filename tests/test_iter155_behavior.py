"""Black-box behavior tests for commit-seq **factory iter 155** (state dir iter-149):
``pla signals --exclude-path GLOB`` gains an ANCESTOR-DIRECTORY match arm.

Feature under test: the pattern is matched against every ancestor directory prefix of a
signal's path in addition to the whole path, so the gitignore-shaped spelling of "ignore
this directory" -- a bare directory name -- excludes the whole subtree instead of being
accepted, exiting 0 and silently excluding nothing.

ISOLATION CONTRACT (honored): every assertion below was derived from this iteration's
spec (``pm.md`` "Expected Behaviors" 1-10) plus the conventions of the existing modules
under ``tests/`` (``test_iter132_behavior.py`` is the shipped ``--exclude-path`` module
and its fixture recipe is reused, as the spec instructs).  **No file under ``src/`` was
read, no engineer / reviewer / fix note was opened, and no ``git diff`` was consulted.**
Where the shape of the output was needed it was obtained by RUNNING the installed
``pla`` console script against throwaway fixture trees and reading its stdout / stderr /
exit status.

Fully offline and deterministic: synthetic ``tmp_path_factory`` trees only -- NEVER the
ambient repo tree, its signal count, or any gitignored path (a fresh clone differs), no
network, no API key, no ``git`` subprocess (the path-less fixture hand-writes the stash
reflog marker the way ``test_iter53_behavior.py`` does), and no duration is asserted.

HARNESS FACT every path assertion depends on: the reported ``path`` is rendered relative
to the ``--workspace`` argument AS GIVEN, so every invocation runs with ``cwd`` set to
the fixture root and ``--workspace .`` (iter-132's measured convention).

AMBIGUITY NOTES (PM feedback):

* Behavior 10 names THREE prose sites, one of which is the ``_path_excluded`` docstring
  in ``cli.py``.  That is implementation source, which this role may not read, so it is
  NOT asserted here; the two OBSERVABLE sites are -- the ``--exclude-path`` entry of
  ``pla signals --help`` (run, not read) and ``README.md`` (a published artifact).  The
  docstring is left to the reviewer.
* Behavior 10's help assertion is deliberately whitespace-insensitive: Python 3.13
  strips the common leading indent from docstrings at compile time while 3.12 does not,
  so asserting on help-text indentation is a known 3.13-only breakage.  Tokens are
  matched against a whitespace-normalised rendering.
* Behavior 8's "byte-identical to a bare run" is asserted for a bare-directory pattern
  naming a directory that does not exist (``nope``) as well as iter-132's ``no-such-dir/*``:
  the ancestor arm must not make a non-matching bare name start matching something.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_MARKER = "PORTFOLIO INTRO"
_GATE_PREFIX = "gate:"


# ---------------------------------------------------------------------------
# Harness -- drive the shipped console script, read observable output only.
# ---------------------------------------------------------------------------


def _console_script() -> Path:
    """The installed ``pla`` console script (iter-114's resolution convention)."""
    bindir = Path(sys.executable).parent
    candidates = [bindir / "pla", bindir / "pla.exe"]
    which = shutil.which("pla")
    if which:
        candidates.append(Path(which))
    script = next((c for c in candidates if c.is_file()), None)
    assert script is not None, (
        "the `pla` console script must be installed (declared in pyproject and "
        f"installed by `uv sync`); searched {[str(c) for c in candidates]}"
    )
    return script


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(_console_script()), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _signals(ws: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run("signals", "--workspace", ".", *extra, cwd=ws)


def _doc(ws: Path, *extra: str) -> dict:
    proc = _signals(ws, "--json", *extra)
    assert proc.returncode == 0, f"exit {proc.returncode}; stderr={proc.stderr!r}"
    doc = json.loads(proc.stdout)
    assert isinstance(doc, dict)
    assert set(doc) == {"workspace_root", "signals"}, sorted(doc)
    return doc


def _records(ws: Path, *extra: str) -> list[dict]:
    return list(_doc(ws, *extra)["signals"])


def _paths(records: list[dict]) -> list[str | None]:
    return [r["path"] for r in records]


def _gate_lines(stderr: str) -> list[str]:
    return [ln for ln in stderr.splitlines() if ln.startswith(_GATE_PREFIX)]


# ---------------------------------------------------------------------------
# Fixtures -- built fresh in tmp_path from the spec's worked example.
# ---------------------------------------------------------------------------

_TODO_FILLER = "\n".join(f"line {i}" for i in range(1, 12))
_TODO_BODY = _TODO_FILLER + "\n- TODO: alpha here\n- TODO: beta here\n"


def _build_main(root: Path) -> None:
    """A ``sub/`` subtree (nested dir + a ``:LINE``-bearing markdown file), a decoy
    ``top/sub/`` at depth 2, and a top-level file matching none of the patterns."""
    (root / "sub" / "a").mkdir(parents=True)
    (root / "top" / "sub").mkdir(parents=True)
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "sub" / "a" / "b.py").write_text("q = 4\n", encoding="utf-8")
    (root / "sub" / "notes.md").write_text(_TODO_BODY, encoding="utf-8")
    (root / "top" / "sub" / "b.py").write_text("y = 2\n", encoding="utf-8")
    (root / "keep.py").write_text("k = 5\n", encoding="utf-8")


@pytest.fixture(scope="module")
def ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Main workspace: every ``todo`` signal lives under ``sub/`` (behavior 9, arm 1)."""
    root = tmp_path_factory.mktemp("iter155_main")
    _build_main(root)
    return root


@pytest.fixture(scope="module")
def gate_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Same, plus a top-level markdown file, so a bare ``sub`` exclusion leaves
    ``todo`` survivors for the gate to count (behavior 9, arm 2)."""
    root = tmp_path_factory.mktemp("iter155_gate")
    _build_main(root)
    (root / "notes.md").write_text(_TODO_BODY, encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def stash_ws(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace emitting a PATH-LESS signal (``git_stash``) alongside path-carrying
    ones. No ``git`` subprocess: the reflog marker is hand-written (iter-53 discipline)."""
    root = tmp_path_factory.mktemp("iter155_stash")
    reflog = root / ".git" / "logs" / "refs" / "stash"
    reflog.parent.mkdir(parents=True)
    zeros = "0" * 40
    reflog.write_text(
        f"{zeros} f7a3af3 Tester <t@t.com> 1785545283 -0700\tWIP on main: shelved\n",
        encoding="utf-8",
    )
    (root / "sub").mkdir()
    (root / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    return root


# ===========================================================================
# Behavior 1 -- a bare directory pattern excludes the SUBTREE.
# ===========================================================================


def test_b01_bare_directory_pattern_excludes_the_whole_subtree(ws: Path) -> None:
    base = _paths(_records(ws))
    assert "sub/a.py" in base, f"fixture precondition; paths={base}"
    assert "sub/a/b.py" in base, f"fixture precondition; paths={base}"
    proc = _signals(ws, "--json", "--exclude-path", "sub")
    assert proc.returncode == 0, proc.stderr
    paths = _paths(_records(ws, "--exclude-path", "sub"))
    assert "sub/a.py" not in paths, (
        "a bare directory name must exclude its contents (this is the iter-155 defect: "
        f"today the pattern silently excludes nothing); paths={paths}"
    )
    assert "sub/a/b.py" not in paths, f"a nested descendant must go too; paths={paths}"


def test_b01_positive_control_survives_so_the_fixture_cannot_pass_vacuously(
    ws: Path,
) -> None:
    """Two-sided proof: the run must still REPORT something, so an empty listing (a
    broken fixture, or an over-broad predicate) cannot masquerade as a pass."""
    records = _records(ws, "--exclude-path", "sub")
    paths = _paths(records)
    assert records, "the filtered run must not be empty"
    assert "keep.py" in paths, f"a signal outside the excluded subtree must survive; {paths}"


# ===========================================================================
# Behavior 2 -- the same pattern still excludes the bare-directory signal itself.
# ===========================================================================


def test_b02_the_bare_directory_signal_itself_is_also_excluded(ws: Path) -> None:
    base = _records(ws)
    assert "sub" in _paths(base), f"fixture precondition; paths={_paths(base)}"
    assert {r["kind"] for r in base if r["path"] == "sub"} == {"test_posture"}
    paths = _paths(_records(ws, "--exclude-path", "sub"))
    assert "sub" not in paths, (
        "one spelling must cover the directory AND its contents; the whole-path arm "
        f"already matched the bare signal and must keep doing so; paths={paths}"
    )


# ===========================================================================
# Behavior 3 -- ancestor matching stays ANCHORED at the start of the path.
# ===========================================================================


def test_b03_ancestor_match_is_anchored_so_a_nested_namesake_survives(ws: Path) -> None:
    base = _paths(_records(ws))
    assert "top/sub/b.py" in base, f"fixture precondition; paths={base}"
    paths = _paths(_records(ws, "--exclude-path", "sub"))
    assert "top/sub/b.py" in paths, (
        "an ancestor match is anchored at the start of the path, so naming a top-level "
        f"directory must not hide a same-named directory nested elsewhere; {paths}"
    )


# ===========================================================================
# Behavior 4 -- any-depth still needs a leading `*`, and ancestors are globbed.
# ===========================================================================


def test_b04_leading_star_makes_the_ancestor_match_any_depth(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "*sub"))
    assert "top/sub/b.py" not in paths, (
        f"'*sub' must glob the ancestor 'top/sub' ('*' crosses '/'); paths={paths}"
    )
    assert "sub/a.py" not in paths, f"the top-level subtree goes too; paths={paths}"


def test_b04_the_shipped_any_depth_glob_still_excludes_it(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "*sub/*"))
    assert "top/sub/b.py" not in paths
    assert "sub/a.py" not in paths
    assert "sub/a/b.py" not in paths


# ===========================================================================
# Behavior 5 -- ancestor components match WHOLE, never as string prefixes.
# ===========================================================================


def test_b05_a_file_pattern_does_not_become_a_directory_pattern(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "sub/a.py"))
    assert "sub/a.py" not in paths, "the whole-path arm still matches"
    assert "sub/a/b.py" in paths, (
        "the ancestors of 'sub/a/b.py' are 'sub' and 'sub/a'; neither equals "
        f"'sub/a.py', so it must survive; paths={paths}"
    )


def test_b05_a_component_prefix_is_not_an_ancestor_match(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "su"))
    assert "sub/a.py" in paths, f"'su' must not match the component 'sub'; paths={paths}"
    assert "sub/a/b.py" in paths
    assert "sub" in paths, "the bare directory signal must survive a prefix-only pattern"


# ===========================================================================
# Behavior 6 -- the shipped glob spelling is unchanged (iter-132 contract 7).
# ===========================================================================


def test_b06_trailing_glob_still_excludes_the_subtree(ws: Path) -> None:
    paths = _paths(_records(ws, "--exclude-path", "sub/*"))
    assert "sub/a.py" not in paths
    assert "sub/a/b.py" not in paths


def test_b06_trailing_glob_still_reports_the_bare_directory_signal(ws: Path) -> None:
    """A top-level path has NO ancestors, so the new arm cannot widen this case."""
    records = _records(ws, "--exclude-path", "sub/*")
    assert "sub" in _paths(records)
    assert {r["kind"] for r in records if r["path"] == "sub"} == {"test_posture"}


# ===========================================================================
# Behavior 7 -- a trailing `:LINE` suffix does not defeat an ancestor match.
# ===========================================================================


def test_b07_line_suffixed_path_is_excluded_by_its_ancestor(ws: Path) -> None:
    base = _paths(_records(ws))
    assert "sub/notes.md:12" in base, f"fixture precondition; paths={base}"
    paths = _paths(_records(ws, "--exclude-path", "sub"))
    assert "sub/notes.md:12" not in paths, (
        "ancestors are derived from the path with one trailing ':<digits>' group "
        f"removed, so 'sub' must hide 'sub/notes.md:12'; paths={paths}"
    )
    assert not [p for p in paths if p and p.startswith("sub/")], (
        f"no descendant of the excluded directory may survive; paths={paths}"
    )


# ===========================================================================
# Behavior 8 -- regressions: path-less, non-matching, and empty patterns.
# ===========================================================================


def test_b08_a_path_less_signal_is_never_excluded(stash_ws: Path) -> None:
    base = _records(stash_ws)
    assert None in _paths(base), f"fixture precondition; paths={_paths(base)}"
    assert {r["kind"] for r in base if r["path"] is None} == {"git_stash"}
    for pattern in ("*", "sub", "*sub", "."):
        paths = _paths(_records(stash_ws, "--exclude-path", pattern))
        assert None in paths, f"pattern {pattern!r} must not touch a path-less signal"


def test_b08_path_less_signal_survives_a_bare_directory_exclusion(stash_ws: Path) -> None:
    paths = _paths(_records(stash_ws, "--exclude-path", "sub"))
    assert "sub/a.py" not in paths, f"the subtree is excluded; paths={paths}"
    assert None in paths, "the repo-level signal has no path, so nothing can match it"


@pytest.mark.parametrize("pattern", ["no-such-dir/*", "nope", "*nope"])
def test_b08_a_pattern_matching_nothing_is_byte_identical_to_a_bare_run(
    ws: Path, pattern: str
) -> None:
    bare = _signals(ws)
    inert = _signals(ws, "--exclude-path", pattern)
    assert inert.returncode == bare.returncode == 0, inert.stderr
    assert inert.stdout == bare.stdout, f"pattern {pattern!r} must be inert"
    assert _records(ws, "--exclude-path", pattern) == _records(ws)


def test_b08_a_dot_pattern_hides_only_the_repo_level_dot_paths(ws: Path) -> None:
    """MEASURED, and my first draft of this test was wrong about it: repo-level findings
    render their path as the literal ``.`` (3 of the 12 signals here), so ``.`` is not a
    no-op -- it matches those via the pre-existing WHOLE-PATH arm.  What the ancestor arm
    must not do is turn the shell's commonest bare-directory token into a
    match-everything pattern: reported paths carry no ``./`` prefix, so no ancestor
    prefix can equal ``.`` and every relative path must survive."""
    base = _records(ws)
    assert [r for r in base if r["path"] == "."], (
        f"fixture precondition: some repo-level signal reports path '.'; {_paths(base)}"
    )
    filtered = _records(ws, "--exclude-path", ".")
    assert filtered == [r for r in base if r["path"] != "."], (
        "'.' may remove exactly the signals whose whole path is '.' and nothing else"
    )
    for survivor in ("keep.py", "sub/a.py", "sub/a/b.py", "top/sub/b.py", "sub"):
        assert survivor in _paths(filtered), (
            f"'{survivor}' has no ancestor equal to '.', so it must survive"
        )


@pytest.mark.parametrize("pattern", ["", "   ", "\t"])
def test_b08_empty_or_whitespace_pattern_is_still_a_parse_time_usage_error(
    ws: Path, pattern: str
) -> None:
    proc = _signals(ws, "--exclude-path", pattern)
    assert proc.returncode == 2, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert proc.stdout == "", "a parse-time error must emit no collection output"
    assert "usage:" in proc.stderr
    assert "--exclude-path" in proc.stderr


# ===========================================================================
# Behavior 9 -- the exit gate narrows with the view.
# ===========================================================================


def test_b09_gate_trips_without_the_filter(ws: Path) -> None:
    todos = [r for r in _records(ws) if r["kind"] == "todo"]
    assert len(todos) == 2, f"fixture precondition; got {_paths(todos)}"
    proc = _signals(ws, "--fail-on-kind", "todo")
    assert proc.returncode == 5
    assert _gate_lines(proc.stderr) == ["gate: fail-on-kind tripped -- todo=2"]


def test_b09_bare_directory_exclusion_that_empties_the_kind_exits_zero(ws: Path) -> None:
    assert [r for r in _records(ws, "--exclude-path", "sub") if r["kind"] == "todo"] == []
    proc = _signals(ws, "--fail-on-kind", "todo", "--exclude-path", "sub")
    assert proc.returncode == 0, proc.stderr
    assert _gate_lines(proc.stderr) == []
    assert _GATE_PREFIX not in proc.stderr


def test_b09_gate_count_equals_the_survivors_of_the_same_filtered_listing(
    gate_ws: Path,
) -> None:
    survivors = [
        r for r in _records(gate_ws, "--exclude-path", "sub") if r["kind"] == "todo"
    ]
    assert len(survivors) == 2, f"top-level TODOs must survive; got {_paths(survivors)}"
    proc = _signals(gate_ws, "--fail-on-kind", "todo", "--exclude-path", "sub")
    assert proc.returncode == 5
    assert _gate_lines(proc.stderr) == [
        f"gate: fail-on-kind tripped -- todo={len(survivors)}"
    ]


# ===========================================================================
# Behavior 10 -- discoverability and published prose agree with the code.
# ===========================================================================


def _help_text(ws: Path) -> str:
    proc = _run("signals", "--help", cwd=ws)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _exclude_path_entry(help_text: str) -> str:
    """The ``--exclude-path`` block of the help output, whitespace-normalised.

    Indentation is deliberately not asserted (3.13 strips docstring indents; argparse
    re-wraps to terminal width), so the block is located by option boundaries only.
    """
    lines = help_text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if "--exclude-path" in ln and ln.strip().startswith("-")),
        None,
    )
    assert start is not None, f"no --exclude-path option line in help:\n{help_text}"
    body = [lines[start]]
    for ln in lines[start + 1 :]:
        if not ln.strip():
            break
        if re.match(r"^\s+-{1,2}[A-Za-z]", ln):
            break
        body.append(ln)
    return " ".join(" ".join(body).split())


@pytest.mark.parametrize(
    "token",
    ["repeatable", "case-insensitive", "crosses", "'/'", "leading", "never excluded"],
)
def test_b10_help_entry_keeps_every_shipped_iter132_token(ws: Path, token: str) -> None:
    entry = _exclude_path_entry(_help_text(ws)).lower()
    assert token in entry, f"token {token!r} missing from --exclude-path help: {entry!r}"


def test_b10_help_entry_documents_the_subtree_ancestor_semantics(ws: Path) -> None:
    entry = _exclude_path_entry(_help_text(ws)).lower()
    assert "subtree" in entry or "ancestor" in entry, (
        "the help must state that a bare directory name excludes the subtree, not just "
        f"that matching is anchored; entry={entry!r}"
    )


def test_b10_readme_publishes_the_two_arm_matching_rule() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert _MARKER in text
    body = text.split(_MARKER, 1)[1]
    assert "--exclude-path" in body
    rows = [ln for ln in body.splitlines() if "--exclude-path" in ln]
    blob = " ".join(rows).lower()
    assert "anchored" in blob, f"the shipped anchoring clause must survive; rows={rows}"
    assert "subtree" in blob or "ancestor" in blob, (
        f"README must describe the new ancestor/subtree arm; rows={rows}"
    )


def test_b10_readme_human_owned_intro_does_not_mention_the_flag() -> None:
    """The portfolio intro above the marker is human-owned; this change adds no
    collector and no CLI verb, so nothing above the marker may move."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    intro = text.split(_MARKER, 1)[0]
    assert "--exclude-path" not in intro
